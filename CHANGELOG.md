# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-29

### Added
- **HermesRunRecorder** — Records Hermes `delegate_task` subagent runs as content-addressed `.tine` artifacts. Captures lifecycle events: start → tool calls → done/error.
- **RoboticContractRecorder** — Emits 5-node lifecycle `.tine` artifacts from DDG robotics audit endpoints (authorization_grant → scope_check → execution_dispatch → sensor_evidence → completion_receipt).
- **ContractArtifact** — Response-ready wrapper for saved `.tine` artifacts with integrity digest and verify command.
- **MCP server bridge** — Wrapper script for opentine's MCP server with absolute `runs_dir` configuration.
- **Dynamic opentine path resolution** — `_get_opentine()` tries multiple candidate site-packages paths (dedicated venv, system python, explicit env override) for portability across environments.
- **Position-based diff** — Patched opentine's `Run.diff()` so `changed[]` populates correctly for steps at the same DAG position with different content (was always `[]` upstream).
- Comprehensive test suite (7 tests): lifecycle construction, tamper detection, counterfactual fork, subagent recording, error recording, disabled state, diff fix.
- GitHub Actions CI workflow (lint + test on Python 3.11/3.12/3.13).
