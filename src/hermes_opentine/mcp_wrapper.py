#!/usr/bin/env python3
"""
opentine MCP server wrapper for Hermes Agent.

Launches opentine's FastMCP server with an absolute runs_dir so .tine artifacts
are stored/read from a stable, profile-safe location regardless of cwd.

Exposes tools (via the opentine MCP server):
  - list_runs()           → list all saved run summaries
  - show_run(run_id)      → show full run detail for debugging
  - fork_run(run_id, from_step, reason) → branch from a step (replay/retry)
  - diff_runs(run_a, run_b) → compare two runs, find divergence point

Resource: run://{run_id}

Usage:
    python -m hermes_opentine.mcp_wrapper
    # or, after install:
    hermes-opentine-mcp

Configure via environment:
    OPENTINE_RUNS_DIR  → directory for .tine artifacts (default: ~/.hermes/tine_runs)
"""
import os

# Absolute path to the .tine artifact store
RUNS_DIR = os.path.expanduser(
    os.environ.get("OPENTINE_RUNS_DIR", "~/.hermes/tine_runs")
)


def main() -> None:
    """Launch the opentine MCP server. Called by the console-script entry point."""
    import opentine.mcp_server as oms

    # Ensure the directory exists
    os.makedirs(RUNS_DIR, exist_ok=True)

    server = oms.create_server(runs_dir=RUNS_DIR)
    server.run()


if __name__ == "__main__":
    main()
