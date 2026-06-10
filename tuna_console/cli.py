from __future__ import annotations

import argparse
import os

from .web.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tuna Operator Console web UI")
    parser.add_argument("--db", default=os.environ.get("TUNA_DB", "tuna.sqlite3"), help="SQLite Tuna database path (default: $TUNA_DB or tuna.sqlite3)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--verbose", action="store_true", help="show verbose Operator Console diagnostics")
    args = parser.parse_args(argv)
    app = create_app(args.db)
    app.config["TUNE_VERBOSE"] = args.verbose
    app.run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
