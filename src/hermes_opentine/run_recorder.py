"""
opentine run recorder for Hermes delegate_task/subagent runs.

Records each subagent run as a content-addressed .tine artifact for:
  - Replay-from-failure (fork from the step before an error)
  - Divergence diff (two subagents given the same task → compare runs)
  - Bug-share (export the .tine, another session loads and inspects it)

Opt-in: only activates when config agent.run_recorder == "opentine".
All recorder operations are wrapped in try/except — recorder failures NEVER
crash delegation or affect subagent behavior.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = os.path.expanduser("~/.hermes/tine_runs")

# Candidate site-packages paths for opentine (same logic as robotics recorder).
_OPENTINE_SITE_CANDIDATES = [
    os.getenv("OPENTINE_SITE_PACKAGES", ""),
    os.path.expanduser("~/.hermes/venvs/opentine/lib/python3.11/site-packages"),
    *[os.path.expanduser(f"~/.hermes/venvs/opentine/lib/{v}/site-packages")
      for v in ("python3.11", "python3.12", "python3.13")],
    "",
]


def _get_opentine():
    """Import opentine from the dedicated venv or system python.

    Tries multiple candidate paths for portability across environments.
    """
    import sys

    # Fast path: already importable
    try:
        from opentine import Run, StepKind
        from opentine.core import RunStatus
        return Run, StepKind, RunStatus
    except ImportError:
        pass

    for candidate in _OPENTINE_SITE_CANDIDATES:
        if not candidate or not os.path.isdir(candidate):
            continue
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        try:
            from opentine import Run, StepKind
            from opentine.graph import RunStatus
            return Run, StepKind, RunStatus
        except ImportError:
            continue
    return None


def is_recorder_enabled(config: dict | None = None) -> bool:
    """Check if the run recorder is enabled via config."""
    if config is None:
        config = _load_config_safe()
    val = (config or {}).get("agent", {}).get("run_recorder", "")
    return str(val).lower() in ("opentine", "true", "1", "yes")


def _load_config_safe() -> dict:
    try:
        import yaml
        path = os.path.expanduser("~/.hermes/config.yaml")
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def _safe_json(value: Any, max_len: int = 4000) -> Any:
    """Truncate large values for safe storage in .tine artifacts."""
    try:
        if isinstance(value, str):
            return value[:max_len]
        if isinstance(value, dict):
            return {k: _safe_json(v, max_len) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_safe_json(v, max_len) for v in value][:100]
        return value
    except Exception:
        return repr(value)[:max_len]


class HermesRunRecorder:
    """
    Records a single delegate_task subagent run as a .tine artifact.
    """

    def __init__(self, goal: str, context: str = "", runs_dir: str = DEFAULT_RUNS_DIR):
        self.goal = goal
        self.context = context
        self.runs_dir = Path(runs_dir)
        self._run = None
        self._last_step_id: Optional[str] = None
        self._step_count = 0
        self._started_at = time.time()
        self._init_run()

    def _init_run(self):
        try:
            result = _get_opentine()
            if result is None:
                logger.debug("opentine not available — recorder disabled")
                return
            Run, StepKind, RunStatus = result
            self._Run = Run
            self._StepKind = StepKind
            self._RunStatus = RunStatus

            self._run = Run(
                manifest={
                    "kind": "hermes-subagent",
                    "goal": self.goal[:500],
                    "resume": True,
                    "replay": ["cache", "rerun"],
                },
                user_prompt=self.goal,
            )
            self.runs_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug(f"HermesRunRecorder init failed: {e}")
            self._run = None

    @property
    def is_active(self) -> bool:
        return self._run is not None

    def on_start(self, subagent_id: str = "", model: str = ""):
        if not self.is_active:
            return
        try:
            step = self._run.add_step(
                self._StepKind.think,
                {
                    "event": "subagent.start",
                    "goal": self.goal[:500],
                    "context": self.context[:2000] if self.context else "",
                    "subagent_id": subagent_id,
                    "model": model,
                },
            )
            self._last_step_id = step.id
            self._step_count += 1
        except Exception as e:
            logger.debug(f"recorder.on_start failed: {e}")

    def on_tool(self, tool_name: str, args: dict | None = None,
                result: Any = None, duration: float = 0.0):
        if not self.is_active:
            return
        try:
            step = self._run.add_step(
                self._StepKind.tool,
                {"event": "tool_call", "tool": tool_name, "args": _safe_json(args)},
                outputs={"result": _safe_json(result)},
                parent_id=self._last_step_id,
                duration=duration,
            )
            self._last_step_id = step.id
            self._step_count += 1
        except Exception as e:
            logger.debug(f"recorder.on_tool failed: {e}")

    def on_error(self, error: str, error_type: str = ""):
        if not self.is_active:
            return
        try:
            self._run.add_step(
                self._StepKind.error,
                {"event": "subagent.error", "error": str(error)[:2000]},
                error={"type": error_type or "Exception"},
                parent_id=self._last_step_id,
            )
            self._step_count += 1
        except Exception as e:
            logger.debug(f"recorder.on_error failed: {e}")

    def on_done(self, result: str):
        if not self.is_active:
            return
        try:
            self._run.add_step(
                self._StepKind.done,
                {
                    "event": "subagent.complete",
                    "result": str(result)[:5000],
                    "duration_seconds": round(time.time() - self._started_at, 2),
                },
                parent_id=self._last_step_id,
            )
            self._step_count += 1
            self.save()
        except Exception as e:
            logger.debug(f"recorder.on_done failed: {e}")

    def save(self) -> Optional[str]:
        if not self.is_active:
            return None
        try:
            path = self.runs_dir / f"{self._run.id}.tine"
            self._run.save(str(path))
            logger.info(f"opentine run recorded: {path} ({self._step_count} steps)")
            return str(path)
        except Exception as e:
            logger.debug(f"recorder.save failed: {e}")
            return None


def maybe_create_recorder(
    goal: str, context: str, config: dict | None = None,
) -> Optional[HermesRunRecorder]:
    """Create a recorder if enabled, or None. Never raises."""
    try:
        if not is_recorder_enabled(config):
            return None
        recorder = HermesRunRecorder(goal=goal, context=context or "")
        return recorder if recorder.is_active else None
    except Exception:
        return None
