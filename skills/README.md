# Tuna skills

Reusable agent skills are exposed as top-level skill directories so portable skill installers can discover them.

## Available skills

- `tuna-fcs`: flight-controller operations through `tuna-fcs` over the FC Bridge or direct USB.
- `tuna-blackbox`: standalone Blackbox Log metadata, decode, analysis, and segment row inspection through `tuna-blackbox`.
- `tuna-agent`: full Tuna Tuning Agent operating procedure.

## Install skills

From a local checkout:

```bash
npx skills add . --skill tuna-fcs
npx skills add . --skill tuna-blackbox
npx skills add . --skill tuna-agent
```

From a published Git repository, use the repository source instead of `.`:

```bash
npx skills add <owner>/<repo> --skill tuna-fcs
```

List available skills without installing:

```bash
npx skills add . --list
```

## Install CLI tools

The skills assume the matching Tuna Python CLIs are available. From a local checkout:

```bash
python3 -m pip install -e .
```

This installs:

- `tuna-fcs`
- `tuna-blackbox`
- `tuna-core`
- `tuna-console`

Without installing console scripts, commands can be run from the repository with Python modules, for example:

```bash
python3 -m tuna_fcs.cli --help
python3 -m tuna_blackbox.cli --help
```
