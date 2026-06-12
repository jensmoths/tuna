.PHONY: install-dev smoke test check

PIP_INSTALL ?= python3 -m pip install --user --break-system-packages

install-dev:
	$(PIP_INSTALL) -e '.[dev]'

smoke:
	python3 -m compileall -q tuna_core tuna_blackbox tuna_fcs tuna_console tests

test:
	python3 -m pytest

check: smoke test
