.PHONY: install-dev smoke structure test quick check

PIP_INSTALL ?= python3 -m pip install --user --break-system-packages

install-dev:
	$(PIP_INSTALL) -e '.[dev]'

smoke:
	python3 -m compileall -q tuna_core tuna_blackbox tuna_fcs tuna_console tests

structure:
	python3 scripts/check_structure.py

test:
	python3 -m pytest

quick: smoke structure
	python3 -m pytest tests/test_tune_workflow.py tests/test_tune_cli.py tests/fcs/test_blackbox_download.py

check: smoke structure test
