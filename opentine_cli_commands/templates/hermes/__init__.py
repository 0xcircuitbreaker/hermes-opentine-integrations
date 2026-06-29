"""
opentine Slash Command Plugin for Hermes
=========================================

Provides /tine commands for agent run provenance management:

  /tine                    - List recent runs
  /tine <run_id>           - Show a run's steps in a tree
  /tine fork <id> [step]   - Fork a run from a specific step
  /tine diff <a> <b>       - Diff two runs and show divergence
  /tine replay <id>        - Cache-replay a run (zero model cost)
  /tine budget             - Show total token/cost spend
  /tine verify <id>        - Verify integrity of a .tine artifact
  /tine help               - Show usage

All commands operate on .tine artifacts in the configured runs directory
(OPENTINE_RUNS_DIR env var, ~/.hermes/tine_runs/ by default).
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# opentine resolution — find the installed package or venv
# ---------------------------------------------------------------------------

_OPENTINE_SITE_CANDIDATES: list[str] = [
    os.environ.get("OPENTINE_PYTHON", ""),
    str(Path.home() / ".hermes/venvs/opentine/lib/python3.11/site-packages"),
    str(Path.home() / ".hermes/venvs/opentine/lib/python3.12/site-packages"),
    str(Path.home() / ".hermes/venvs/opentine/lib/python3.13/site-packages"),
]

for _candidate in _OPENTINE_SITE_CANDIDATES:
    if _candidate and Path(_candidate).is_dir():
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break

def _runs_dir() -> Path:
    """Resolve the .tine runs directory."""
    d = os.environ.get(
        "OPENTINE_RUNS_DIR",
        str(Path.home() / ".hermes/tine_runs"),
    )
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_opentine():
    """Import opentine, raising a helpful error if not installed."""
    try:
        from opentine.graph import Run, Step, StepKind, RunStatus
        from opentine import short_id
        return Run, Step, StepKind, RunStatus, short_id
    except ImportError as e:
        return None


def _format_cost(cost: float) -> str:
    """Format cost in USD."""
    if cost == 0:
        return "$0"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _format_duration(seconds: float) -> str:
    """Format duration human-readable."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def _kind_emoji(kind: str) -> str:
    """Emoji for step kinds."""
    return {
        "start": "🟢",
        "tool": "🔧",
        "think": "💭",
        "end": "🏁",
        "error": "❌",
        "done": "✅",
    }.get(kind, "❓")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_list(args: str) -> str:
    """List all .tine runs in the runs directory."""
    runs_dir = _runs_dir()
    tine_files = sorted(runs_dir.glob("*.tine"), key=lambda f: f.stat().st_mtime, reverse=True)

    if not tine_files:
        return f"No .tine runs found in {runs_dir}\nRecord runs by enabling the recorder, then use /tine to inspect them."

    opentine = _get_opentine()
    if opentine is None:
        # Fallback: just list files with basic info
        lines = [f"**{len(tine_files)} runs** in `{runs_dir}`\n"]
        for f in tine_files[:20]:
            size = f.stat().st_size
            lines.append(f"- `{f.stem}` ({size:,} bytes)")
        if len(tine_files) > 20:
            lines.append(f"- ... and {len(tine_files) - 20} more")
        return "\n".join(lines)

    Run = opentine[0]
    lines = [f"**{len(tine_files)} runs** in `{runs_dir}`\n"]
    lines.append("| Run ID | Steps | Status | Cost | Duration |")
    lines.append("|--------|-------|--------|------|----------|")

    for f in tine_files[:20]:
        try:
            run = Run.load(f)
            step_count = len(run.steps)
            status = run.status.value if hasattr(run.status, 'value') else str(run.status)
            cost = run.total_cost
            duration = run.total_duration
            lines.append(
                f"| `{f.stem}` | {step_count} | {status} | "
                f"{_format_cost(cost)} | {_format_duration(duration)} |"
            )
        except Exception:
            lines.append(f"| `{f.stem}` | ? | error | - | - |")

    if len(tine_files) > 20:
        lines.append(f"\n_...and {len(tine_files) - 20} more_")

    return "\n".join(lines)


def _cmd_show(run_id: str) -> str:
    """Show full details of a specific run."""
    if not run_id.strip():
        return "Usage: `/tine show <run_id>` — provide a run ID from `/tine list`"

    runs_dir = _runs_dir()

    # Try exact filename, then stem match
    candidates = list(runs_dir.glob(f"{run_id}*.tine"))
    if not candidates:
        candidates = list(runs_dir.glob(f"*{run_id}*.tine"))
    if not candidates:
        return f"No run matching `{run_id}` in {runs_dir}"

    opentine = _get_opentine()
    if opentine is None:
        return "opentine is not installed. Install with `pip install opentine`"

    Run = opentine[0]
    try:
        run = Run.load(candidates[0])
    except Exception as e:
        return f"Failed to load run: {e}"

    lines = [f"**Run:** `{candidates[0].stem}`"]
    lines.append(f"**Status:** {run.status.value if hasattr(run.status, 'value') else str(run.status)}")
    lines.append(f"**Cost:** {_format_cost(run.total_cost)} | **Duration:** {_format_duration(run.total_duration)}")
    lines.append(f"**Steps:** {len(run.steps)}\n")

    # Build step tree
    for step in run.steps:
        emoji = _kind_emoji(step.kind.value if hasattr(step.kind, 'value') else str(step.kind))
        parent_str = ""
        if step.parent_ids:
            parent_str = f" _← {_kind_emoji('')} {', '.join(p[:8] for p in step.parent_ids)}_"

        # Truncate inputs for display
        inputs_str = ""
        if step.inputs:
            inputs_preview = str(step.inputs)
            if len(inputs_preview) > 80:
                inputs_preview = inputs_preview[:77] + "..."
            inputs_str = f"\n  📥 `{inputs_preview}`"

        outputs_str = ""
        if step.outputs:
            outputs_preview = str(step.outputs)
            if len(outputs_preview) > 80:
                outputs_preview = outputs_preview[:77] + "..."
            outputs_str = f"\n  📤 `{outputs_preview}`"

        error_str = ""
        if step.error:
            error_str = f"\n  ❌ `{str(step.error)[:100]}`"

        tool_str = ""
        if step.tool_info:
            tool_name = step.tool_info.get("name", "")
            if tool_name:
                tool_str = f" `[{tool_name}]`"

        cost_str = f" ({_format_cost(step.cost)})" if step.cost else ""

        lines.append(
            f"{emoji} **{step.kind.value if hasattr(step.kind, 'value') else str(step.kind)}**"
            f"`{step.id[:12]}`{tool_str}{parent_str}{cost_str}{inputs_str}{outputs_str}{error_str}"
        )

    return "\n".join(lines)


def _cmd_fork(args: str) -> str:
    """Fork a run from a specific step."""
    parts = args.strip().split()
    if len(parts) < 2:
        return "Usage: `/tine fork <run_id> <step_id>` — fork from a specific step\nUse `/tine show <run_id>` to find step IDs"

    run_id = parts[0]
    step_id = parts[1]

    runs_dir = _runs_dir()
    candidates = list(runs_dir.glob(f"{run_id}*.tine"))
    if not candidates:
        candidates = list(runs_dir.glob(f"*{run_id}*.tine"))
    if not candidates:
        return f"No run matching `{run_id}`"

    opentine = _get_opentine()
    if opentine is None:
        return "opentine is not installed."

    Run = opentine[0]
    short_id = opentine[4]
    try:
        run = Run.load(candidates[0])

        # Match step by partial ID
        matching_steps = [s for s in run.steps if s.id.startswith(step_id) or step_id in s.id]
        if not matching_steps:
            return f"No step matching `{step_id}`. Available: {', '.join(s.id[:12] for s in run.steps)}"
        if len(matching_steps) > 1:
            return f"Ambiguous step ID. Matches: {', '.join(s.id[:12] for s in matching_steps)}"

        forked = run.fork(from_step_id=matching_steps[0].id)
        new_id = f"fork_{candidates[0].stem}_{short_id(step_id)}"
        out_path = runs_dir / f"{new_id}.tine"
        forked.save(out_path)

        return (
            f"**Forked** `{candidates[0].stem}` from step `{matching_steps[0].id[:12]}`\n"
            f"New run: `{new_id}` → `{out_path}`\n"
            f"The forked run shares all ancestor steps. Modify it and re-run from the branch point."
        )
    except Exception as e:
        return f"Fork failed: {e}\n```\n{traceback.format_exc()}\n```"


def _cmd_diff(args: str) -> str:
    """Diff two runs and show divergence."""
    parts = args.strip().split()
    if len(parts) < 2:
        return "Usage: `/tine diff <run_a> <run_b>` — compare two runs"

    runs_dir = _runs_dir()
    opentine = _get_opentine()
    if opentine is None:
        return "opentine is not installed."

    Run = opentine[0]

    # Find both runs
    paths = []
    for rid in parts[:2]:
        candidates = list(runs_dir.glob(f"{rid}*.tine")) or list(runs_dir.glob(f"*{rid}*.tine"))
        if not candidates:
            return f"No run matching `{rid}`"
        paths.append(candidates[0])

    try:
        run_a = Run.load(paths[0])
        run_b = Run.load(paths[1])
        diff = run_a.diff(run_b)

        lines = [f"**Diff:** `{paths[0].stem}` vs `{paths[1].stem}`\n"]

        if hasattr(diff, 'changed') and diff.changed:
            lines.append(f"**Changed steps ({len(diff.changed)}):**")
            for s in diff.changed:
                lines.append(f"  🔄 `{s.id[:12]}` — content differs at same DAG position")
        else:
            lines.append("**No changed steps** (position-matched content is identical)")

        if hasattr(diff, 'only_a') and diff.only_a:
            lines.append(f"\n**Only in A ({len(diff.only_a)}):**")
            for s in diff.only_a:
                lines.append(f"  ➡️ `{s.id[:12]}` ({s.kind})")

        if hasattr(diff, 'only_b') and diff.only_b:
            lines.append(f"\n**Only in B ({len(diff.only_b)}):**")
            for s in diff.only_b:
                lines.append(f"  ⬅️ `{s.id[:12]}` ({s.kind})")

        # Check common ancestor
        try:
            ancestor = run_a.common_ancestor(run_b)
            if ancestor:
                lines.append(f"\n**Common ancestor:** `{ancestor.id[:12]}`")
        except Exception:
            pass

        total_changes = len(getattr(diff, 'changed', []) or [])
        only_a_count = len(getattr(diff, 'only_a', []) or [])
        only_b_count = len(getattr(diff, 'only_b', []) or [])
        if total_changes == 0 and only_a_count == 0 and only_b_count == 0:
            lines.append("\n✅ **Runs are identical.**")

        return "\n".join(lines)
    except Exception as e:
        return f"Diff failed: {e}"


def _cmd_replay(run_id: str) -> str:
    """Cache-replay a run — show recorded outputs with zero model cost."""
    if not run_id.strip():
        return "Usage: `/tine replay <run_id>` — replay a run's recorded outputs (zero model cost)"

    runs_dir = _runs_dir()
    candidates = list(runs_dir.glob(f"{run_id}*.tine")) or list(runs_dir.glob(f"*{run_id}*.tine"))
    if not candidates:
        return f"No run matching `{run_id}`"

    opentine = _get_opentine()
    if opentine is None:
        return "opentine is not installed."

    Run = opentine[0]
    try:
        run = Run.load(candidates[0])

        lines = [
            f"**Cache Replay:** `{candidates[0].stem}`",
            f"**Cost:** {_format_cost(run.total_cost)} (already spent)",
            f"**Replay cost:** $0.00 — using recorded outputs only\n",
        ]

        for step in run.steps:
            kind = step.kind.value if hasattr(step.kind, 'value') else str(step.kind)
            emoji = _kind_emoji(kind)
            lines.append(f"{emoji} **{kind}** `{step.id[:12]}`")

            if step.outputs:
                for key, val in step.outputs.items():
                    val_str = str(val)
                    if len(val_str) > 200:
                        val_str = val_str[:197] + "..."
                    lines.append(f"  `{key}`: {val_str}")

            if step.error:
                lines.append(f"  ❌ {step.error}")

        lines.append(f"\n💡 **Token saving:** This replay cost $0 in model calls. "
                     f"The original run cost {_format_cost(run.total_cost)}.")
        return "\n".join(lines)
    except Exception as e:
        return f"Replay failed: {e}"


def _cmd_budget(args: str) -> str:
    """Show total cost across all recorded runs."""
    runs_dir = _runs_dir()
    tine_files = sorted(runs_dir.glob("*.tine"), key=lambda f: f.stat().st_mtime, reverse=True)

    if not tine_files:
        return f"No .tine runs found in {runs_dir}"

    opentine = _get_opentine()
    if opentine is None:
        return "opentine is not installed."

    Run = opentine[0]
    total_cost = 0.0
    total_duration = 0.0
    total_steps = 0
    by_kind: dict[str, float] = {}

    for f in tine_files:
        try:
            run = Run.load(f)
            total_cost += run.total_cost
            total_duration += run.total_duration
            total_steps += len(run.steps)
            for step in run.steps:
                kind = step.kind.value if hasattr(step.kind, 'value') else str(step.kind)
                by_kind[kind] = by_kind.get(kind, 0) + step.cost
        except Exception:
            pass

    lines = [
        f"**opentine Budget Report**\n",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total runs | {len(tine_files)} |",
        f"| Total steps | {total_steps} |",
        f"| Total cost | {_format_cost(total_cost)} |",
        f"| Total compute time | {_format_duration(total_duration)} |",
    ]

    if by_kind:
        lines.append(f"\n**Cost by step kind:**")
        for kind, cost in sorted(by_kind.items(), key=lambda x: -x[1]):
            lines.append(f"- {kind}: {_format_cost(cost)}")

    return "\n".join(lines)


def _cmd_verify(run_id: str) -> str:
    """Verify the integrity of a .tine artifact."""
    if not run_id.strip():
        return "Usage: `/tine verify <run_id>` — verify integrity of a .tine artifact"

    runs_dir = _runs_dir()
    candidates = list(runs_dir.glob(f"{run_id}*.tine")) or list(runs_dir.glob(f"*{run_id}*.tine"))
    if not candidates:
        return f"No run matching `{run_id}`"

    opentine = _get_opentine()
    if opentine is None:
        return "opentine is not installed."

    Run = opentine[0]
    try:
        result = Run.verify_integrity(str(candidates[0]))
        lines = [f"**Integrity Check:** `{candidates[0].stem}`\n"]

        if hasattr(result, 'valid'):
            if result.valid:
                lines.append("✅ **PASS** — artifact is valid and unmodified")
            else:
                lines.append("❌ **FAIL** — artifact has been modified or corrupted")

            if hasattr(result, 'reason'):
                lines.append(f"**Reason:** {result.reason}")
            if hasattr(result, 'expected'):
                lines.append(f"**Expected:** `{result.expected}`")
            if hasattr(result, 'actual'):
                lines.append(f"**Actual:** `{result.actual}`")
        else:
            lines.append(f"Result: {result}")

        return "\n".join(lines)
    except Exception as e:
        return f"Verification failed: {e}"


def _cmd_help() -> str:
    return """**opentine Slash Commands**

| Command | What it does |
|---------|-------------|
| `/tine` | List recent runs |
| `/tine <run_id>` | Show a run's steps in detail |
| `/tine fork <run_id> <step_id>` | Fork from a specific step |
| `/tine diff <run_a> <run_b>` | Compare two runs |
| `/tine replay <run_id>` | Cache-replay (zero model cost) |
| `/tine budget` | Total cost across all runs |
| `/tine verify <run_id>` | Verify .tine integrity |
| `/tine help` | This message |

**Token-saving workflows:**
- **Replay** — recalls a run's outputs without re-calling any model ($0)
- **Fork** — retry from a known-good step instead of re-running everything
- **Diff** — find where two approaches diverged
"""


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _handle_slash(raw_args: str) -> str | None:
    """Main slash command handler. Dispatches to subcommands."""
    raw = raw_args.strip()

    if not raw or raw.lower() in ("help", "-h", "--help"):
        return _cmd_help()

    parts = raw.split()
    subcommand = parts[0].lower()

    if subcommand == "list":
        return _cmd_list(" ".join(parts[1:]))
    elif subcommand == "show":
        return _cmd_show(" ".join(parts[1:]))
    elif subcommand == "fork":
        return _cmd_fork(" ".join(parts[1:]))
    elif subcommand == "diff":
        return _cmd_diff(" ".join(parts[1:]))
    elif subcommand == "replay":
        return _cmd_replay(" ".join(parts[1:]))
    elif subcommand == "budget":
        return _cmd_budget(" ".join(parts[1:]))
    elif subcommand == "verify":
        return _cmd_verify(" ".join(parts[1:]))
    elif subcommand == "help":
        return _cmd_help()
    else:
        # No subcommand prefix — treat the whole thing as a run ID for /tine <run_id>
        # But first check if it looks like a known subcommand typo
        close = [c for c in ["list", "show", "fork", "diff", "replay", "budget", "verify", "help"]
                 if c.startswith(subcommand)]
        if close:
            return f"Unknown subcommand `{subcommand}`. Did you mean `{close[0]}`?\n\n{_cmd_help()}"
        # Treat as run ID → show
        return _cmd_show(raw)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    ctx.register_command(
        "tine",
        handler=_handle_slash,
        description="Manage opentine agent runs: list, show, fork, diff, replay, budget, verify",
        args_hint="[list|show|fork|diff|replay|budget|verify] [run_id]",
    )
