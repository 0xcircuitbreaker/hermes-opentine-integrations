"""
RoboticContractRecorder — emits opentine .tine lifecycle artifacts from
DDG's robotics audit endpoints.

Maps each audit result to a 5-node content-addressed run tree:
  authorization_grant → scope_check → execution_dispatch → sensor_evidence → completion_receipt

Opt-in: only activates when env DDG_OPENTINE_RECEIPTS is set.
Never throws into the audit path — all operations are try/except guarded.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_RUNS_DIR = os.getenv(
    "OPENTINE_ROBOTICS_RUNS_DIR",
    os.path.expanduser("~/.hermes/tine_runs"),
)

# Candidate site-packages paths for opentine, in priority order.
# The recorder tries each until it finds a working import. This makes the
# module portable across environments (dedicated venv, system python, uv-managed).
_OPENTINE_SITE_CANDIDATES = [
    # 1. Explicit override via env
    os.getenv("OPENTINE_SITE_PACKAGES", ""),
    # 2. Dedicated opentine venv (DDG/Hermes convention)
    os.path.expanduser("~/.hermes/venvs/opentine/lib/python3.11/site-packages"),
    # 3. Python version-agnostic search in the dedicated venv
    *[os.path.expanduser(f"~/.hermes/venvs/opentine/lib/{v}/site-packages")
      for v in ("python3.11", "python3.12", "python3.13")],
    # 4. System site-packages (opentine installed globally or via uv pip)
    "",  # empty = rely on existing sys.path
]


def _get_opentine():
    """Import opentine from the dedicated venv or system python.

    Tries multiple candidate paths so the module works across environments:
    dedicated venv, system python, or an explicit OPENTINE_SITE_PACKAGES override.
    """
    import sys

    # Fast path: already importable (system install, or already injected)
    try:
        from opentine import Run, StepKind
        return Run, StepKind
    except ImportError:
        pass

    # Try each candidate site-packages path
    for candidate in _OPENTINE_SITE_CANDIDATES:
        if not candidate or not os.path.isdir(candidate):
            continue
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        try:
            from opentine import Run, StepKind
            return Run, StepKind
        except ImportError:
            continue
    return None


class ContractArtifact:
    """Wraps a saved .tine artifact with response-ready metadata."""

    def __init__(self, run_id: str, path: str, digest: str, step_count: int):
        self.run_id = run_id
        self.path = path
        self.digest = digest
        self.step_count = step_count

    def to_response(self) -> dict:
        return {
            "format": "opentine.tine.v1",
            "run_id": self.run_id,
            "artifact_hash": self.digest,
            "steps": self.step_count,
            "verify_command": f"tine verify {self.run_id}.tine",
            "description": (
                "Portable, tamper-evident run tree binding authorization → "
                "scope check → execution → evidence → completion. "
                "Verify offline: Run.verify_integrity(artifact_path)."
            ),
        }


class RoboticContractRecorder:
    """
    Records a robotic contract audit as a .tine lifecycle artifact.
    """

    @classmethod
    def record(
        cls,
        path: str,
        spec: dict,
        report: dict,
        runs_dir: str = DEFAULT_RUNS_DIR,
    ) -> Optional[ContractArtifact]:
        """Build and save a .tine artifact from an audit result. Never raises."""
        try:
            result = _get_opentine()
            if result is None:
                logger.debug("opentine not available — robotics recorder skipped")
                return None
            Run, StepKind = result

            receipt = report.get("receipt", {})
            runs_path = Path(runs_dir)
            runs_path.mkdir(parents=True, exist_ok=True)

            run = Run(manifest={
                "kind": "ddg_robotic_contract",
                "route": path,
                "audit_overall": report.get("overall", "unknown"),
                "resume": True,
                "replay": ["cache", "rerun"],
            })

            # Node 1: Authorization Grant
            grant_inputs = cls._extract_grant_fields(spec, path)
            grant_inputs["event"] = "authorization_grant"
            grant = run.add_step(StepKind.think, grant_inputs)

            # Node 2: Scope Check (the DDG audit findings)
            findings = report.get("findings", [])
            scope_inputs = {
                "event": "scope_check",
                "overall": report.get("overall"),
                "counts": report.get("counts", {}),
                "rules_checked": [f.get("rule", "?") for f in findings],
                "failed_rules": [
                    {"rule": f.get("rule"), "message": f.get("message")}
                    for f in findings if f.get("severity") == "fail"
                ],
                "ddg_binding": receipt.get("binding", ""),
            }
            scope = run.add_step(StepKind.tool, scope_inputs, parent_id=grant.id)

            # Node 3: Execution Dispatch
            exec_inputs = {
                "event": "execution_dispatch",
                "route": path,
                "spec_sha256": receipt.get("spec_sha256", ""),
                "price_usd": receipt.get("price_usd", ""),
                "issued_at": receipt.get("issued_at"),
            }
            execution = run.add_step(StepKind.tool, exec_inputs, parent_id=scope.id)

            # Node 4: Sensor Evidence
            evidence_inputs = {
                "event": "sensor_evidence",
                "report_sha256": receipt.get("report_sha256", ""),
                "audit_ok": report.get("ok"),
                "evidence_type": "static_analysis_rules_engine",
                "finding_count": len(findings),
            }
            evidence = run.add_step(StepKind.tool, evidence_inputs, parent_id=execution.id)

            # Node 5: Completion Receipt
            receipt_inputs = {
                "event": "completion_receipt",
                "verdict": report.get("overall"),
                "binding": receipt.get("binding", ""),
                "protocol": receipt.get("protocol", "ddg_robotics_audit"),
                "portable_format": "opentine.tine.v1",
                "tamper_evident": True,
            }
            run.add_step(StepKind.done, receipt_inputs, parent_id=evidence.id)

            # Save
            artifact_path = runs_path / f"{run.id}.tine"
            run.save(str(artifact_path))

            # Extract digest
            with open(artifact_path) as f:
                data = json.load(f)
            digest = data.get("metadata", {}).get("integrity", {}).get("digest", "")

            logger.info(
                f"opentine robotics contract recorded: {artifact_path.name} "
                f"(5 nodes, overall={report.get('overall')})"
            )

            return ContractArtifact(
                run_id=run.id,
                path=str(artifact_path),
                digest=digest,
                step_count=5,
            )

        except Exception as e:
            logger.debug(f"RoboticContractRecorder.record failed: {e}")
            return None

    @staticmethod
    def _extract_grant_fields(spec: dict, path: str) -> dict:
        """Extract authorization-relevant fields from the spec."""
        return {
            "force_cap_newtons": spec.get("force_cap_newtons") or spec.get("force_cap_N"),
            "motion_scope": spec.get("motion_scope") or spec.get("workspace"),
            "allowed_objects": spec.get("allowed_objects"),
            "zone": spec.get("zone") or spec.get("allowed_zone"),
            "ttl_seconds": spec.get("ttl_seconds") or spec.get("expires_in_seconds"),
            "revocable": spec.get("revocable") or spec.get("revocation_path"),
            "task": (spec.get("task") or spec.get("objective") or "")[:500],
        }
