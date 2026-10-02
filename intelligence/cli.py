from __future__ import annotations

import argparse

from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ops-signals batch operational signal engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full batch pipeline")
    run_parser.add_argument("--config", required=True, help="Path to config.yaml")

    init_parser = subparsers.add_parser("init-db", help="Initialize PostgreSQL tables")
    init_parser.add_argument("--config", required=True, help="Path to config.yaml")

    subparsers.add_parser("mcp", help="Run the Ops Signals MCP server over stdio in read-only mode")
    subparsers.add_parser("mcp-write", help="Run the Ops Signals MCP server over stdio with write tools enabled")

    from backend.app.case_import.cli import add_parser as add_import_cases_parser

    add_import_cases_parser(subparsers)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        config = load_config(args.config)
        pipeline = SignalPipeline(config)
        pipeline.init_db()
        print("Database initialized.")
        return

    if args.command == "run":
        config = load_config(args.config)
        pipeline = SignalPipeline(config)
        result = pipeline.run()
        report = result.report
        print("Operational Intelligence Report")
        print(f"Analysis window: {report.analysis_window_start} -> {report.analysis_window_end}")
        print(f"Overall health score: {report.overall_health_score}")
        print(f"Critical findings: {report.critical_findings}")
        print(f"Significant findings: {report.significant_findings}")
        print(f"Normal findings: {report.normal_findings}")
        print(f"Metrics analysed: {report.metrics_analysed}")
        print(f"What changed yesterday? {report.answers['what_changed_yesterday']}")
        print(f"What should I investigate first? {report.answers['what_should_i_investigate_first']}")
        print(f"Did anything unusual happen? {report.answers['did_anything_unusual_happen']}")
        print(f"Is this behaviour new or expected? {report.answers['is_this_behavior_new_or_expected']}")
        print(f"Has this happened before? {report.answers['has_this_happened_before']}")
        print("Top findings:")
        for finding in result.findings:
            print(f"- [{finding.importance_score}] {finding.title}")
        return

    if args.command == "mcp":
        from backend.app.mcp_server import main as run_mcp_server

        run_mcp_server(read_only_only=True)
        return

    if args.command == "mcp-write":
        from backend.app.mcp_server import main as run_mcp_server

        run_mcp_server(read_only_only=False)
        return

    if args.command == "import-cases":
        from backend.app.case_import.cli import run as run_import_cases

        raise SystemExit(run_import_cases(args))


if __name__ == "__main__":
    main()
