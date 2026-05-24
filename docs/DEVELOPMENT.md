# Development Guide (v0.3)

## Supported Python

Runtime target:
- Python 3.12+

Development/smoke target:
- Python 3.12 or 3.13

Why smoke does not target Python 3.14 host runtime:
- Current dependency/test matrix is validated on 3.12/3.13.
- Windows integration tooling and typing baselines are pinned to stable 3.12-era behavior.
- 3.14 host can be used for editing, but smoke uses an isolated 3.12/3.13 virtual environment.

## Linux Development

1. Create venv and install dev deps:
```bash
python3.13 -m venv .venv/dev
. .venv/dev/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
```
2. Run checks:
```bash
make lint
make typecheck
make test
```
3. Run dry-run CLI:
```bash
python -m linux_vhd_launcher.cli doctor
python -m linux_vhd_launcher.cli plan-install --iso ./sample.iso --vhd ./sample.vhdx --size-gb 20 --format vhdx --dry-run
python -m linux_vhd_launcher.cli plan-windows-lab
```

## Windows Development

1. Use elevated terminal for real-operation experiments.
2. Always start in dry-run mode first.
3. Real ops require all explicit safety flags:
```bash
python -m linux_vhd_launcher.cli install \
  --iso .\sample.iso \
  --vhd .\sample.vhdx \
  --size-gb 20 \
  --format vhdx \
  --bcd-backup-path .\bcd-backups\before.bcd \
  --execute-real-windows-ops \
  --i-understand-this-is-experimental
```
4. Use disposable VM snapshot before any real boot/disk mutation.

## Smoke Modes

Online full smoke:
```bash
bash scripts/smoke_arch.sh
```

Reuse existing venv:
```bash
bash scripts/smoke_arch.sh --reuse-venv
```

Skip install (preinstalled deps only):
```bash
bash scripts/smoke_arch.sh --reuse-venv --skip-install
```

Offline verification mode:
```bash
bash scripts/smoke_arch.sh --offline --reuse-venv
```

Offline mode behavior:
- Never attempts package downloads.
- Fails with actionable messages:
  - `network unavailable`
  - `venv missing`
  - `ruff missing`
  - `mypy missing`
  - `PyQt6 missing`
