"""Reconfigurable Neuron-Synapse Routing Module reference model."""

from .core import (
    RoutingModule,
    SpikeEvent,
    MAX_LAYERS,
    NEURONS_PER_LAYER,
    SHARED_PHYSICAL_POOL_SIZE,
    MAX_TDM_SLOTS,
    MODE_STATIC_CROSSBAR,
    MODE_AER,
    MODE_TDM,
    MODE_BYPASS,
    VALID_MODES,
)
from .error_codes import ErrorCode
from .metrics import RoutingMetrics
from .stimulus import StimulusGenerator, StimCommand, StimEvent
from .trace import TraceRecord, TraceWriter

__all__ = [
    "RoutingModule",
    "SpikeEvent",
    "ErrorCode",
    "RoutingMetrics",
    "TraceRecord",
    "TraceWriter",
    "StimulusGenerator",
    "StimCommand",
    "StimEvent",
    "MAX_LAYERS",
    "NEURONS_PER_LAYER",
    "SHARED_PHYSICAL_POOL_SIZE",
    "MAX_TDM_SLOTS",
    "MODE_STATIC_CROSSBAR",
    "MODE_AER",
    "MODE_TDM",
    "MODE_BYPASS",
    "VALID_MODES",
]
