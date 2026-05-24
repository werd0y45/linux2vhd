from __future__ import annotations

import pytest

from linux_vhd_launcher.system.runner import CommandRunner


def test_command_runner_dry_run() -> None:
    runner = CommandRunner(dry_run=True)
    result = runner.run(["echo", "hello"])
    assert result.returncode == 0
    assert result.command == ("echo", "hello")


def test_command_runner_check_raises() -> None:
    runner = CommandRunner(dry_run=False)
    with pytest.raises(RuntimeError):
        runner.run(["bash", "-lc", "exit 2"], check=True)
