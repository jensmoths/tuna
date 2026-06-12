# Tuna

Tuna is a drone-tuning system split into focused Python packages:

- `tuna_core/`: durable Tuna state, domain rules, SQLite persistence, and CLI helpers for the **Tuning Agent**.
- `tuna_blackbox/`: standalone Blackbox Log parsing, decode helpers, and analysis summaries.
- `tuna_fcs/`: flight-controller operations through FCS/Bridge or direct USB.
- `tuna_console/`: local Flask Operator Console for Operator Tasks, notifications, and Loop workbench views.
- `bridge-firmware/`: FC Bridge firmware experiments and tests.

Canonical domain terms and workflow rules live in `docs/domain-model.md` and `docs/tune-workflow-decisions.md`.

## Local checks

```bash
make install-dev  # install Tuna plus test dependencies into the active environment
make smoke      # dependency-light syntax/import compilation
make structure  # stdlib architecture boundary/godfile regression checks
make quick      # smoke + structure + focused workflow/FCS regression tests
make test       # pytest suite, requires project test dependencies
make check      # smoke + structure + full test suite
```

Run `make install-dev` before the full test suite in a new environment.
Override `PIP_INSTALL` if you prefer a virtualenv-managed install, for example
`make install-dev PIP_INSTALL=".venv/bin/python -m pip install"`.
