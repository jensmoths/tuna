from __future__ import annotations

from tuna_core.cli import analysis_commands
from tuna_core.cli.analysis_commands import handle_analysis_command
from tuna_core.cli.operator_commands import handle_operator_command
from tuna_core.cli.output import emit
from tuna_core.cli.parser import build_parser
from tuna_core.cli.state_commands import handle_state_command
from tuna_core.cli.workflow_commands import handle_workflow_command
from tuna_core.services.analysis import analyze_imported_log, decode_imported_log
from tuna_core.storage import connect, init_db


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = connect(args.db)
    try:
        if args.area == "db" and args.action == "init":
            init_db(conn)
            emit({"db": args.db}, args.json)
            return 0

        init_db(conn)
        analysis_commands.analyze_imported_log = analyze_imported_log
        analysis_commands.decode_imported_log = decode_imported_log
        for handler in (handle_state_command, handle_analysis_command, handle_workflow_command, handle_operator_command):
            handled = handler(conn, args)
            if handled is not None:
                return handled
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
