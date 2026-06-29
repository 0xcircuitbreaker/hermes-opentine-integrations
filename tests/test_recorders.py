#!/usr/bin/env python3
"""
Tests for both opentine integration recorders.

Run with:
    pytest tests/test_recorders.py -v

Requires opentine >= 0.1.1 installed in the active environment.

Tests:
  1. HermesRunRecorder — 5-step lifecycle, integrity verify, error recording
  2. RoboticContractRecorder — 5 lifecycle nodes, parent chain, tamper detection
  3. Disabled state — no crash when the recorder is off
"""
import json
import os
import shutil

import pytest
from opentine import Run

from hermes_opentine import (
    HermesRunRecorder,
    RoboticContractRecorder,
    ContractArtifact,
    maybe_create_recorder,
    is_recorder_enabled,
)

TEST_DIR = "/tmp/opentine_module_tests"


@pytest.fixture(autouse=True)
def _clean_test_dir():
    """Wipe and recreate the test directory before each test."""
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    os.makedirs(TEST_DIR, exist_ok=True)
    yield
    # leave artifacts in place for debugging; wiped on next run


# ---------------------------------------------------------------------------
# TEST 1: HermesRunRecorder
# ---------------------------------------------------------------------------

def test_hermes_run_recorder_lifecycle():
    """Full 5-step lifecycle records, saves, and passes integrity check."""
    recorder = HermesRunRecorder(
        "Build a FastAPI auth service",
        "JWT, PostgreSQL",
        runs_dir=f"{TEST_DIR}/hermes_runs",
    )
    assert recorder.is_active, "recorder should be active when opentine is available"

    recorder.on_start(subagent_id="sub-001", model="glm-5.2")
    recorder.on_tool("terminal", {"command": "mkdir src/"}, {"output": "created"}, duration=0.5)
    recorder.on_tool("write_file", {"path": "src/auth.py"}, {"status": "ok"})
    recorder.on_tool("terminal", {"command": "pytest"}, {"output": "5 passed"}, duration=2.1)
    recorder.on_done("Auth service built. 5 tests passing.")

    path = f"{TEST_DIR}/hermes_runs/{recorder._run.id}.tine"
    assert os.path.exists(path), "artifact should be saved"
    assert Run.verify_integrity(path).ok, "artifact should pass integrity check"

    loaded = Run.load(path)
    assert len(loaded.graph.steps) == 5, "should have 5 steps (start + 3 tools + done)"


def test_hermes_run_recorder_error_recording():
    """Error events are recorded without crashing."""
    recorder = HermesRunRecorder("failing task", runs_dir=f"{TEST_DIR}/hermes_runs")
    recorder.on_start(subagent_id="sub-err")
    recorder.on_tool("terminal", {"command": "bad-cmd"}, {"error": "not found"})
    recorder.on_error("TimeoutError", error_type="TimeoutError")

    err_path = recorder.save()
    assert err_path is not None
    loaded = Run.load(err_path)
    assert loaded.graph.steps, "should have steps including the error"


# ---------------------------------------------------------------------------
# TEST 2: RoboticContractRecorder
# ---------------------------------------------------------------------------

_SAMPLE_SPEC = {
    "force_cap_newtons": 5.0,
    "motion_scope": {"type": "joint"},
    "allowed_objects": ["bin_a"],
    "zone": "workcell-A",
    "ttl_seconds": 300,
    "revocable": True,
    "task": "move_arm_to(x=0.2)",
}

_SAMPLE_REPORT = {
    "ok": True,
    "overall": "pass",
    "counts": {"fail": 0, "warn": 1, "pass": 6, "total": 7},
    "findings": [
        {"severity": "pass", "rule": "force_bounded"},
        {"severity": "warn", "rule": "object_class"},
    ],
    "receipt": {
        "protocol": "ddg_robotics_audit",
        "price_usd": "35.00",
        "spec_sha256": "a1b2" + "0" * 60,
        "report_sha256": "c3d4" + "0" * 60,
        "binding": "/v1/robot-task/auth-contract-audit:a1b2:c3d4",
    },
}


def test_robotic_contract_recorder_lifecycle():
    """5-node lifecycle artifact saves with correct event chain."""
    artifact = RoboticContractRecorder.record(
        path="/v1/robot-task/authorization-contract-audit",
        spec=_SAMPLE_SPEC,
        report=_SAMPLE_REPORT,
        runs_dir=f"{TEST_DIR}/robotics_runs",
    )
    assert artifact is not None
    assert isinstance(artifact, ContractArtifact)
    assert artifact.step_count == 5

    assert Run.verify_integrity(artifact.path).ok

    loaded = Run.load(artifact.path)
    events = [s.inputs.get("event") for s in loaded.graph.steps.values()]
    assert events == [
        "authorization_grant",
        "scope_check",
        "execution_dispatch",
        "sensor_evidence",
        "completion_receipt",
    ], f"event chain mismatch: {events}"


def test_robotic_contract_recorder_tamper_detection():
    """A modified artifact must fail integrity verification."""
    artifact = RoboticContractRecorder.record(
        path="/v1/robot-task/authorization-contract-audit",
        spec=_SAMPLE_SPEC,
        report=_SAMPLE_REPORT,
        runs_dir=f"{TEST_DIR}/robotics_runs",
    )
    assert artifact is not None

    with open(artifact.path) as f:
        data = json.load(f)
    for sid, step in data["graph"]["steps"].items():
        if step.get("inputs", {}).get("event") == "authorization_grant":
            step["inputs"]["force_cap_newtons"] = 50.0

    tampered = artifact.path.replace(".tine", "_tampered.tine")
    with open(tampered, "w") as f:
        json.dump(data, f)

    assert not Run.verify_integrity(tampered).ok, "tampered artifact should fail verification"


def test_contract_artifact_to_response():
    """ContractArtifact.to_response() produces a well-formed payload."""
    artifact = RoboticContractRecorder.record(
        path="/v1/robot-task/authorization-contract-audit",
        spec=_SAMPLE_SPEC,
        report=_SAMPLE_REPORT,
        runs_dir=f"{TEST_DIR}/robotics_runs",
    )
    assert artifact is not None

    response = artifact.to_response()
    assert response["format"] == "opentine.tine.v1"
    assert response["run_id"] == artifact.run_id
    assert response["steps"] == 5
    assert "tine verify" in response["verify_command"]


# ---------------------------------------------------------------------------
# TEST 3: Disabled state / config gating
# ---------------------------------------------------------------------------

def test_disabled_state_returns_none():
    """maybe_create_recorder returns None when the recorder is off."""
    result = maybe_create_recorder("t", "t", config={"agent": {"run_recorder": ""}})
    assert result is None


def test_enabled_state_returns_recorder():
    """maybe_create_recorder returns a recorder when config enables it."""
    result = maybe_create_recorder(
        "t", "t", config={"agent": {"run_recorder": "opentine"}}
    )
    assert result is not None
    assert result.is_active


def test_is_recorder_enabled():
    """is_recorder_enabled reads the config flag correctly."""
    assert is_recorder_enabled(config={"agent": {"run_recorder": "opentine"}}) is True
    assert is_recorder_enabled(config={"agent": {"run_recorder": "yes"}}) is True
    assert is_recorder_enabled(config={"agent": {"run_recorder": ""}}) is False
    assert is_recorder_enabled(config={"agent": {}}) is False
    assert is_recorder_enabled(config=None) is not None  # returns a bool, doesn't crash


# ---------------------------------------------------------------------------
# TEST 4: Counterfactual fork
# ---------------------------------------------------------------------------

def test_robotic_contract_recorder_fork():
    """Fork from scope_check node carries ancestors into a new branch."""
    artifact = RoboticContractRecorder.record(
        path="/v1/robot-task/authorization-contract-audit",
        spec=_SAMPLE_SPEC,
        report=_SAMPLE_REPORT,
        runs_dir=f"{TEST_DIR}/fork_runs",
    )
    assert artifact is not None

    loaded = Run.load(artifact.path)
    steps_list = list(loaded.graph.steps.values())
    scope_check_id = steps_list[1].id

    forked = loaded.fork(
        from_step_id=scope_check_id,
        new_run_id="counterfactual_10N",
        branch="what_if_10N",
    )
    assert forked is not None
    assert len(forked.graph.steps) == 2
    assert forked.metadata.get("forked_from") == loaded.id
    assert forked.metadata.get("fork_point") == scope_check_id


# ---------------------------------------------------------------------------
# TEST 5: Diff fix — changed[] populates
# ---------------------------------------------------------------------------

def test_diff_changed_populates():
    """Position-matched steps with different content appear in changed[]."""
    from opentine import Run as OpentineRun, StepKind

    def _build(allow_value, suffix):
        run = OpentineRun(manifest={"kind": "test_contract"})
        s1 = run.add_step(StepKind.think, {"event": "auth_grant", "force_cap": 5.0})
        s2 = run.add_step(StepKind.tool, {"event": "scope_check", "overall": "pass"}, parent_id=s1.id)
        s3 = run.add_step(StepKind.tool, {"event": "execution", "allowed": allow_value}, parent_id=s2.id)
        run.add_step(StepKind.done, {"event": "receipt", "verdict": "pass"}, parent_id=s3.id)
        path = f"{TEST_DIR}/diff_{suffix}.tine"
        run.save(path)
        return OpentineRun.load(path)

    run_a = _build(True, "a")
    run_b = _build(False, "b")
    diff = run_a.diff(run_b)

    assert len(diff.changed) >= 1, f"Expected >=1 changed, got {len(diff.changed)}"
    changed_events = [(sa.inputs.get("event"), sb.inputs.get("event")) for sa, sb in diff.changed]
    assert ("execution", "execution") in changed_events

    run_c = _build(True, "c")
    diff_identical = run_a.diff(run_c)
    assert len(diff_identical.changed) == 0
