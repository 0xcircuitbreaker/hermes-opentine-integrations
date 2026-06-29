# Hermes opentine Integrations — Provenance for Agent Runs

**Content-addressed, tamper-evident, forkable `.tine` artifacts for Hermes subagent runs and robotics audit services.**

[![CI](https://github.com/0xcircuitbreaker/hermes-opentine-integrations/actions/workflows/ci.yml/badge.svg)](https://github.com/0xcircuitbreaker/hermes-opentine-integrations/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What is this?

[opentine](https://github.com/0xcircuitbreaker/opentine) is **git for agent runs** — a pure-Python library that records agent executions as content-addressed DAGs and serializes them to portable `.tine` artifacts. This package provides integrations that wire opentine into:

1. **Hermes Agent subagent runs** — every `delegate_task` call becomes a replayable, forkable, diffable `.tine`
2. **Robotics audit services** — every paid audit produces a 5-node lifecycle artifact binding authorization → evidence → completion

Each artifact is:
- **Tamper-evident** — SHA-256 content addressing. Editing any node breaks every downstream hash.
- **Portable** — one self-describing JSON file. Email it, store it in S3, hand it to a regulator.
- **Forkable** — branch from any lifecycle node for counterfactual analysis or retry.
- **Self-verifying** — `Run.verify_integrity(path)` checks the digest offline, no server needed.

## Installation

```bash
pip install hermes-opentine-integrations

# With MCP server support:
pip install hermes-opentine-integrations[mcp]

# For development:
pip install -e ".[dev]"
```

**Prerequisite:** [opentine](https://pypi.org/project/opentine/) >=0.1.1 must be installed.

```bash
pip install opentine
# Or in a dedicated venv (recommended):
uv venv ~/.venvs/opentine --python 3.11
uv pip install --python ~/.venvs/opentine/bin/python opentine
```

## Quick Start

### HermesRunRecorder — Subagent Provenance

```python
from hermes_opentine import HermesRunRecorder, maybe_create_recorder

# Option A: Explicit creation
recorder = HermesRunRecorder(
    goal="Build a FastAPI auth service",
    context="JWT, PostgreSQL",
    runs_dir="~/.hermes/tine_runs",
)
recorder.on_start(subagent_id="sub-001", model="glm-5.2")
recorder.on_tool("terminal", {"command": "pytest"}, {"output": "5 passed"}, duration=2.1)
recorder.on_done("Auth service built. 5 tests passing.")
# → ~/.hermes/tine_runs/<run_id>.tine

# Option B: Config-gated (only activates if agent.run_recorder == "opentine")
recorder = maybe_create_recorder("task", "context", config=my_config)
```

### RoboticContractRecorder — Audit Lifecycle Artifacts

```python
from hermes_opentine import RoboticContractRecorder

# After running a robotics audit (or any structured audit):
artifact = RoboticContractRecorder.record(
    path="/v1/robot-task/authorization-contract-audit",
    spec={
        "force_cap_newtons": 5.0,
        "motion_scope": {"type": "joint", "joints": ["j1", "j2"]},
        "ttl_seconds": 300,
        "revocable": True,
        "task": "move_arm_to(x=0.2, y=0.1)",
    },
    report=audit_result,  # dict with ok, overall, findings, receipt
)

if artifact:
    print(f"Artifact: {artifact.run_id}")
    print(f"Digest:   {artifact.digest}")
    # Embed in API response:
    response["opentine_artifact"] = artifact.to_response()
```

### MCP Server — Browse Runs from Hermes

Register the MCP server in your Hermes `config.yaml`:

```yaml
mcp_servers:
  opentine:
    command: "python"
    args: ["-m", "hermes_opentine.mcp_wrapper"]
    env:
      OPENTINE_RUNS_DIR: "/home/user/.hermes/tine_runs"
    timeout: 60
```

After `/reset`, your agent gains 4 tools: `mcp_opentine_list_runs`, `mcp_opentine_show_run`, `mcp_opentine_fork_run`, `mcp_opentine_diff_runs`.

## Architecture

```
┌─────────────┐  lifecycle   ┌──────────────────────┐  .tine   ┌─────────────────┐
│ Agent /     │  events      │ Recorder             │ ───────▶ │ Artifact Store  │
│ Audit Engine│ ───────────▶ │ (add_step per event) │          │ (.tine files)   │
└─────────────┘              └──────────────────────┘          └───────┬─────────┘
                                                                   │
                                    ┌──────────────────────────────┘
                                    │
                          ┌─────────▼──────────┐  verify   ┌─────────────────┐
                          │ MCP Server         │ ────────▶ │ Verifier        │
                          │ (list/show/fork/   │           │ (tine verify /  │
                          │  diff)             │           │  Run.verify)    │
                          └────────────────────┘           └─────────────────┘
```

## Advanced Features

### Cache Replay — Save Tokens by Reusing Recorded Runs

When an agent retries a task that already succeeded, the recorded `.tine` can be replayed in cache mode — **zero model calls, zero tokens spent**.

```python
from opentine import Agent
agent = Agent(model=my_model)
# Reuse a previously recorded run instead of re-executing
result = agent.replay(saved_run, mode="cache")  # $0.00 vs full re-execution
```

**Savings:** A 10-step subagent retry costs $0.00 with cache replay vs $1.00+ for full re-execution.

### Fork for Counterfactual Analysis

Branch from any lifecycle node to explore "what if" scenarios without losing the original:

```python
# "What if we authorized 10N instead of 5N?"
forked = original_run.fork(
    from_step_id=grant_step.id,
    new_run_id="counterfactual_10N",
    branch="what_if_10N",
)
# Re-run audit from scope_check forward with the new authority
```

### Divergence Diff — Find Where Two Runs Branched

Compare two agent runs that were given the same task to find the exact divergence point:

```python
diff = run_a.diff(run_b)
print(f"Diverged at: {diff.common_ancestor}")
print(f"Only in A:   {len(diff.only_a)} steps")
print(f"Only in B:   {len(diff.only_b)} steps")
print(f"Changed:     {len(diff.changed)} steps")  # NOW WORKS (was always [])
```

An orchestrator can detect divergence, examine the changed steps, and re-dispatch the failing path with a corrected approach.

### Resume from Failure — Retry Only the Failed Tail

When a 10-step run fails at step 7, fork from step 6 and re-execute only steps 7-10:

```
Full retry:     Steps 1-10 re-executed = $1.00
Resume from 7:  Steps 1-6 cached, 7-10 re-executed = $0.40 (60% savings)
```

### Subagent Cost Tracking

Each step in a `.tine` carries a `cost` field. After a run:

```python
total_cost = sum(s.cost for s in run.graph.steps.values())
```

Compare two approaches to the same task by cost: `run_a.total_cost` vs `run_b.total_cost`.

### Policy Embedding

`.tine` artifacts carry the security policy that governed the run (filesystem bounds, network restrictions, shell/python disabled). A verifier can confirm the audit was conducted under the claimed constraints.

## Cross-CLI Slash Commands

The `opentine_cli_commands` package installs opentine provenance commands into multiple AI agent CLIs:

```bash
# Install for all detected CLIs
python -m opentine_cli_commands install --target all

# Install for a specific CLI
python -m opentine_cli_commands install --target hermes
python -m opentine_cli_commands install --target claude
python -m opentine_cli_commands install --target codex

# Check what's installed
python -m opentine_cli_commands status
```

| CLI | Integration | Commands |
|-----|-------------|----------|
| **Hermes** | Plugin (`/tine`) | `/tine list`, `/tine show`, `/tine fork`, `/tine diff`, `/tine replay`, `/tine budget`, `/tine verify` |
| **Claude Code** | Markdown prompts | `/tine-list`, `/tine-show`, `/tine-fork`, `/tine-diff`, `/tine-replay` |
| **Codex CLI** | MCP server | `list_runs`, `show_run`, `fork_run`, `diff_runs` (auto-discovered) |
| **OpenCode** | MCP server | Same as Codex |
| **Kimi Code** | MCP server | Same as Codex |

The Hermes plugin provides the richest experience — 8 slash commands with formatted output, budget tracking, and integrity verification. The MCP-based integrations (Codex, OpenCode, Kimi) expose the same 4 core tools that any MCP-compatible client can call.

## Verification

Every `.tine` can be verified offline:

```bash
# CLI
tine verify <run_id>.tine

# Python
from opentine import Run
result = Run.verify_integrity("path/to/artifact.tine")
print(result.ok)  # True if digest matches
```

## Limitations (Honest)

- **Integrity ≠ signing.** `verify_integrity` is a checksum — it catches accidental/unsophisticated tampering. A sophisticated party who rewrites the file *and* recomputes the digest can forge a valid artifact. For regulator-facing audit, add an HMAC/signature layer on top.
- **0.1.x beta.** opentine's `format_version` is pinned to 1 with no migration code. Pin your opentine version and budget for a migration tool before bumping.
- **No streaming auto-persistence.** Use explicit `save()` checkpoints for long-running tasks.
- **Secret redaction is key-name-based.** Keys matching `key|secret|token|password|credential|auth` are redacted to `[REDACTED]` on save. Don't store secrets under other key names.

## Full Design Document

For the complete architecture, integration points, sample artifacts, and the robotics audit lifecycle mapping, see the [design document](../opentine-robotics-recorder-design.md).

## License

MIT — see [LICENSE](LICENSE).

opentine itself is Apache-2.0.
