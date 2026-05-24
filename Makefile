PYTHON ?= python

.PHONY: test lint typecheck smoke doctor doctor-json

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy linux_vhd_launcher

smoke:
	bash scripts/smoke_arch.sh

doctor:
	$(PYTHON) -m linux_vhd_launcher.cli doctor

doctor-json:
	$(PYTHON) -m linux_vhd_launcher.cli doctor --json
