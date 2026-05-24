#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="$ROOT_DIR/.tools"
VENV_DIR="$ROOT_DIR/.venv/smoke"
UV_CACHE_DIR="$TOOLS_DIR/uv-cache"
UV_PYTHON_INSTALL_DIR="$TOOLS_DIR/uv-python"
PIP_CACHE_DIR="$TOOLS_DIR/pip-cache"
REUSE_VENV=0
SKIP_INSTALL=0
OFFLINE=0

usage() {
  cat <<'USAGE'
Usage: scripts/smoke_arch.sh [--reuse-venv] [--skip-install] [--offline]

Options:
  --reuse-venv   Reuse existing .venv/smoke if present.
  --skip-install Skip dependency install step.
  --offline      Do not perform network operations; verify only preinstalled environment.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reuse-venv)
      REUSE_VENV=1
      shift
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --offline)
      OFFLINE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$TOOLS_DIR" "$ROOT_DIR/.venv" "$UV_CACHE_DIR" "$PIP_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"

log() {
  printf '[smoke] %s\n' "$*" >&2
}

die() {
  printf '[smoke] ERROR: %s\n' "$*" >&2
  exit 1
}

network_available() {
  python - <<'PY' >/dev/null 2>&1
import socket
socket.gethostbyname("pypi.org")
PY
}

py_version_ok() {
  local py_bin="$1"
  local ver
  ver="$($py_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  [[ "$ver" == "3.12" || "$ver" == "3.13" ]]
}

pick_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    PYTHON_BIN="$VENV_DIR/bin/python"
    return
  fi

  if command -v python3.13 >/dev/null 2>&1; then
    PYTHON_BIN="python3.13"
    return
  fi

  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
    return
  fi

  if command -v uv >/dev/null 2>&1; then
    if [[ $OFFLINE -eq 1 ]]; then
      die "network unavailable"
    fi

    log "Using uv-managed Python 3.13"
    export UV_CACHE_DIR
    export UV_PYTHON_INSTALL_DIR
    uv python install 3.13 >/tmp/smoke_uv_python.log 2>&1 || {
      if network_available; then
        cat /tmp/smoke_uv_python.log >&2
        die "uv failed to fetch Python runtime"
      fi
      die "network unavailable"
    }
    uv venv --python 3.13 "$VENV_DIR" >/tmp/smoke_uv_venv.log 2>&1 || {
      cat /tmp/smoke_uv_venv.log >&2
      die "uv failed to create virtualenv"
    }
    PYTHON_BIN="$VENV_DIR/bin/python"
    return
  fi

  die "No Python 3.12/3.13 runtime found"
}

if [[ $REUSE_VENV -eq 0 && $OFFLINE -eq 0 ]]; then
  rm -rf "$VENV_DIR"
fi

log "Selecting Python runtime"
PYTHON_BIN=""
pick_python

if ! py_version_ok "$PYTHON_BIN"; then
  die "Smoke runtime must be Python 3.12 or 3.13"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  if [[ $OFFLINE -eq 1 ]]; then
    die "venv missing"
  fi
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PYTHON_BIN="$VENV_DIR/bin/python"
log "Using Python: $($PYTHON_BIN --version 2>&1)"

if [[ $OFFLINE -eq 1 ]]; then
  SKIP_INSTALL=1
  log "Offline mode enabled; dependency installation disabled"
fi

if [[ $SKIP_INSTALL -eq 0 ]]; then
  "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
  PIP_CACHE_DIR="$PIP_CACHE_DIR" "$PYTHON_BIN" -m pip install --upgrade pip >/tmp/smoke_pip_upgrade.log 2>&1 || {
    if network_available; then
      cat /tmp/smoke_pip_upgrade.log >&2
      die "pip upgrade failed"
    fi
    die "network unavailable"
  }

  PIP_CACHE_DIR="$PIP_CACHE_DIR" "$PYTHON_BIN" -m pip install -e '.[dev]' >/tmp/smoke_pip_install.log 2>&1 || {
    if network_available; then
      cat /tmp/smoke_pip_install.log >&2
      die "dependency install failed"
    fi
    die "network unavailable"
  }
else
  log "Skipping dependency installation"
fi

"$PYTHON_BIN" -c "import PyQt6" >/dev/null 2>&1 || die "PyQt6 missing"
"$PYTHON_BIN" -m ruff --version >/dev/null 2>&1 || die "ruff missing"
"$PYTHON_BIN" -m mypy --version >/dev/null 2>&1 || die "mypy missing"

log "CLI help"
"$PYTHON_BIN" -m linux_vhd_launcher.cli --help >/dev/null

TMP_DIR="$(mktemp -d)"
printf 'iso' > "$TMP_DIR/test.iso"

log "CLI doctor"
"$PYTHON_BIN" -m linux_vhd_launcher.cli doctor >/dev/null

log "CLI doctor JSON"
"$PYTHON_BIN" -m linux_vhd_launcher.cli doctor --json >/dev/null

log "CLI dry-run plan"
"$PYTHON_BIN" -m linux_vhd_launcher.cli plan-install --iso "$TMP_DIR/test.iso" --vhd "$TMP_DIR/test.vhdx" --size-gb 20 --format vhdx --dry-run >/dev/null

log "CLI dry-run plan JSON"
"$PYTHON_BIN" -m linux_vhd_launcher.cli plan-install --iso "$TMP_DIR/test.iso" --vhd "$TMP_DIR/test.vhdx" --size-gb 20 --format vhdx --dry-run --json >/dev/null

log "CLI Windows lab plan"
"$PYTHON_BIN" -m linux_vhd_launcher.cli plan-windows-lab >/dev/null

log "CLI Windows lab plan JSON"
"$PYTHON_BIN" -m linux_vhd_launcher.cli plan-windows-lab --json >/dev/null

REPORT_DIR="$TMP_DIR/validation_report"

log "Validation init"
"$PYTHON_BIN" -m linux_vhd_launcher.cli validation init --report-dir "$REPORT_DIR" >/dev/null

log "Validation run-dry"
"$PYTHON_BIN" -m linux_vhd_launcher.cli validation run-dry --report-dir "$REPORT_DIR" >/dev/null

log "Validation collect"
"$PYTHON_BIN" -m linux_vhd_launcher.cli validation collect --report-dir "$REPORT_DIR" >/dev/null

log "Validation render"
"$PYTHON_BIN" -m linux_vhd_launcher.cli validation render --report-dir "$REPORT_DIR" >/dev/null

log "Validation status"
"$PYTHON_BIN" -m linux_vhd_launcher.cli validation status --report-dir "$REPORT_DIR" >/dev/null

log "ruff check"
"$PYTHON_BIN" -m ruff check .

log "mypy"
"$PYTHON_BIN" -m mypy linux_vhd_launcher

log "pytest"
"$PYTHON_BIN" -m pytest

rm -rf "$TMP_DIR"
log "Smoke test complete"
