"""Command execution abstraction with dry-run support."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess, run

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    """Result of a command execution."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Executes system commands in a controlled and testable way."""

    def __init__(self, *, dry_run: bool = False, cwd: Path | None = None) -> None:
        self.dry_run = dry_run
        self.cwd = cwd

    def run(
        self,
        command: Sequence[str],
        *,
        elevated_required: bool = False,
        check: bool = True,
    ) -> CommandResult:
        """Run a command and return structured output."""
        cmd = tuple(command)
        logger.info(
            "run_command dry_run=%s elevated_required=%s cmd=%s",
            self.dry_run,
            elevated_required,
            " ".join(cmd),
        )
        if self.dry_run:
            return CommandResult(command=cmd, returncode=0, stdout="", stderr="")

        proc: CompletedProcess[str] = run(
            cmd,
            cwd=str(self.cwd) if self.cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )
        result = CommandResult(
            command=cmd,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
            )
        return result
