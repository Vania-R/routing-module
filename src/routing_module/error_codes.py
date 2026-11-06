"""Error codes for the Reconfigurable Neuron-Synapse Routing Module."""

from enum import IntEnum


class ErrorCode(IntEnum):
    """Status and error codes returned by the routing module API."""

    SUCCESS = 0
    ERR_INVALID_MODE = 1
    ERR_INVALID_LAYERS = 2
    ERR_INVALID_LAYER = 3
    ERR_INVALID_NEURONS = 4
    ERR_INVALID_SRC = 5
    ERR_INVALID_DST_MASK = 6
    ERR_INVALID_SLOT = 7
    ERR_INVALID_CONFIG = 8
    ERR_UNCOMMITTED_CHANGES = 9

    def is_ok(self) -> bool:
        """Return True if this code represents SUCCESS."""
        return self == ErrorCode.SUCCESS
