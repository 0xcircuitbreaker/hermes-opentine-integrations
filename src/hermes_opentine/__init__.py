"""
hermes_opentine — opentine provenance recorders for Hermes agent runs.

Re-exports the public API from the submodules so users can write:

    from hermes_opentine import HermesRunRecorder, maybe_create_recorder
    from hermes_opentine import RoboticContractRecorder, ContractArtifact
"""
from .run_recorder import (
    HermesRunRecorder,
    maybe_create_recorder,
    is_recorder_enabled,
)
from .robotics_recorder import (
    RoboticContractRecorder,
    ContractArtifact,
)

__version__ = "0.1.0"

__all__ = [
    "HermesRunRecorder",
    "maybe_create_recorder",
    "is_recorder_enabled",
    "RoboticContractRecorder",
    "ContractArtifact",
]
