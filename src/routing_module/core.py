"""Reference model of a reconfigurable neuron-synapse routing module."""

import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from .error_codes import ErrorCode
from .metrics import RoutingMetrics
from .trace import TraceRecord, TraceWriter


# Network geometry constants
MAX_LAYERS = 3              # Hidden layers: 0, 1, 2
NEURONS_PER_LAYER = 8       # 8 neurons per hidden layer (0..7)
SHARED_PHYSICAL_POOL_SIZE = 8
MAX_TDM_SLOTS = 16

# Routing Modes
MODE_STATIC_CROSSBAR = 0
MODE_AER = 1
MODE_TDM = 2
MODE_BYPASS = 3
VALID_MODES = (MODE_STATIC_CROSSBAR, MODE_AER, MODE_TDM, MODE_BYPASS)


@dataclass
class SpikeEvent:
    """Spike stimulus entering the routing module.

    Attributes:
        src: Source address or neuron index.
        dst: Destination neuron index (or None to infer/crossbar-route).
        layer: Target hidden layer (0, 1, or 2).
        cycle: Injected simulation cycle (None = use router internal cycle).
        early_exit: Flag requesting early exit/bypass in Mode 3.
        slot: Optional explicit TDM slot (None = infer from cycle).
    """

    src: int
    dst: Optional[int] = None
    layer: int = 0
    cycle: Optional[int] = None
    early_exit: bool = False
    slot: Optional[int] = None


class RoutingModule:
    """Reconfigurable neuron-synapse routing module reference model.

    Features 4 routing modes:
        0: Static crossbar with neuron and layer enable masks.
        1: Address Event Representation (AER) with source lookup table and multicast.
        2: Time-Division Multiplexing (TDM) neuron reuse on a shared physical pool.
        3: Layer bypass / early exit.

    Configuration staging:
        Configuration changes are staged in shadow registers and only latched
        into the active hardware configuration on commit().
    """

    def __init__(self, trace_writer: Optional[TraceWriter] = None, metrics: Optional[RoutingMetrics] = None):
        self.trace_writer = trace_writer if trace_writer is not None else TraceWriter()
        self.metrics = metrics if metrics is not None else RoutingMetrics()
        self._current_cycle: int = 0

        # Active configuration (currently in effect)
        self._active_mode: int = MODE_STATIC_CROSSBAR
        self._active_layers: int = MAX_LAYERS
        self._active_layer_mask: int = (1 << MAX_LAYERS) - 1  # 0b111 (all 3 layers active)
        self._active_neuron_masks: Dict[int, int] = {
            lyr: (1 << NEURONS_PER_LAYER) - 1 for lyr in range(MAX_LAYERS)
        }  # 0xFF per layer
        self._active_route_table: Dict[int, int] = {}
        self._active_tdm_schedule: Dict[int, int] = {}
        self._active_bypass_layers: Dict[int, bool] = {lyr: False for lyr in range(MAX_LAYERS)}

        # Staged configuration (shadow registers; applied only on commit)
        self._staged_mode: int = self._active_mode
        self._staged_layers: int = self._active_layers
        self._staged_layer_mask: int = self._active_layer_mask
        self._staged_neuron_masks: Dict[int, int] = copy.deepcopy(self._active_neuron_masks)
        self._staged_route_table: Dict[int, int] = copy.deepcopy(self._active_route_table)
        self._staged_tdm_schedule: Dict[int, int] = copy.deepcopy(self._active_tdm_schedule)
        self._staged_bypass_layers: Dict[int, bool] = copy.deepcopy(self._active_bypass_layers)
        self._has_uncommitted_changes: bool = False

    # -------------------------------------------------------------------------
    # Configuration API (Staged until commit)
    # -------------------------------------------------------------------------

    def set_routing_mode(self, mode: int) -> int:
        """Stage routing mode configuration (0: Static, 1: AER, 2: TDM, 3: Bypass)."""
        if not isinstance(mode, int) or isinstance(mode, bool) or mode not in VALID_MODES:
            return ErrorCode.ERR_INVALID_MODE
        self._staged_mode = mode
        self._has_uncommitted_changes = True
        return ErrorCode.SUCCESS

    def set_active_layers(self, n: int, mask: Optional[int] = None) -> int:
        """Stage active layer count (1..3) or explicit layer bitmask."""
        if mask is not None:
            if not isinstance(mask, int) or isinstance(mask, bool) or mask < 0 or mask > ((1 << MAX_LAYERS) - 1):
                return ErrorCode.ERR_INVALID_LAYERS
            self._staged_layers = bin(mask).count("1")
            self._staged_layer_mask = mask
            self._has_uncommitted_changes = True
            return ErrorCode.SUCCESS

        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > MAX_LAYERS:
            return ErrorCode.ERR_INVALID_LAYERS

        self._staged_layers = n
        self._staged_layer_mask = (1 << n) - 1
        self._has_uncommitted_changes = True
        return ErrorCode.SUCCESS

    def set_active_neurons(self, layer: int, k: int, mask: Optional[int] = None) -> int:
        """Stage active neurons for a given layer.

        Args:
            layer: Layer index (0, 1, or 2).
            k: Neuron count (0..8) or raw 8-bit mask (0..255).
            mask: Optional explicit bitmask override (0..255).
        """
        if not isinstance(layer, int) or isinstance(layer, bool) or layer < 0 or layer >= MAX_LAYERS:
            return ErrorCode.ERR_INVALID_LAYER

        if mask is not None:
            if not isinstance(mask, int) or isinstance(mask, bool) or mask < 0 or mask > 0xFF:
                return ErrorCode.ERR_INVALID_NEURONS
            eff_mask = mask
        else:
            if not isinstance(k, int) or isinstance(k, bool) or k < 0 or k > 0xFF:
                return ErrorCode.ERR_INVALID_NEURONS
            if k <= NEURONS_PER_LAYER:
                eff_mask = (1 << k) - 1 if k > 0 else 0
            else:
                eff_mask = k

        self._staged_neuron_masks[layer] = eff_mask
        self._has_uncommitted_changes = True
        return ErrorCode.SUCCESS

    def load_route_table(self, src: int, dst_mask: int) -> int:
        """Stage an AER route table entry mapping src address to multicast dst_mask."""
        if not isinstance(src, int) or isinstance(src, bool) or src < 0 or src > 0xFFFF:
            return ErrorCode.ERR_INVALID_SRC
        if not isinstance(dst_mask, int) or isinstance(dst_mask, bool) or dst_mask < 0 or dst_mask > 0xFFFFFF:
            return ErrorCode.ERR_INVALID_DST_MASK

        self._staged_route_table[src] = dst_mask
        self._has_uncommitted_changes = True
        return ErrorCode.SUCCESS

    def set_tdm_schedule(self, slot: int, layer: int) -> int:
        """Stage a TDM slot allocation for a logical layer.

        Args:
            slot: Slot index (0..MAX_TDM_SLOTS-1).
            layer: Layer index (0..MAX_LAYERS-1), or -1 to deschedule/idle.
        """
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0 or slot >= MAX_TDM_SLOTS:
            return ErrorCode.ERR_INVALID_SLOT
        if not isinstance(layer, int) or isinstance(layer, bool) or (layer < -1 or layer >= MAX_LAYERS):
            return ErrorCode.ERR_INVALID_LAYER

        self._staged_tdm_schedule[slot] = layer
        self._has_uncommitted_changes = True
        return ErrorCode.SUCCESS

    def set_layer_bypass(self, layer: int, enable: bool) -> int:
        """Stage layer bypass enable/disable flag for Mode 3."""
        if not isinstance(layer, int) or isinstance(layer, bool) or layer < 0 or layer >= MAX_LAYERS:
            return ErrorCode.ERR_INVALID_LAYER
        self._staged_bypass_layers[layer] = bool(enable)
        self._has_uncommitted_changes = True
        return ErrorCode.SUCCESS

    def commit(self) -> int:
        """Apply staged configuration to active hardware registers."""
        self._active_mode = self._staged_mode
        self._active_layers = self._staged_layers
        self._active_layer_mask = self._staged_layer_mask
        self._active_neuron_masks = copy.deepcopy(self._staged_neuron_masks)
        self._active_route_table = copy.deepcopy(self._staged_route_table)
        self._active_tdm_schedule = copy.deepcopy(self._staged_tdm_schedule)
        self._active_bypass_layers = copy.deepcopy(self._staged_bypass_layers)
        self._has_uncommitted_changes = False
        return ErrorCode.SUCCESS

    # -------------------------------------------------------------------------
    # State Inspection Helpers
    # -------------------------------------------------------------------------

    @property
    def active_mode(self) -> int:
        return self._active_mode

    @property
    def staged_mode(self) -> int:
        return self._staged_mode

    @property
    def active_layers(self) -> int:
        return self._active_layers

    @property
    def active_layer_mask(self) -> int:
        return self._active_layer_mask

    def get_active_neuron_mask(self, layer: int) -> int:
        return self._active_neuron_masks.get(layer, 0)

    @property
    def active_route_table(self) -> Dict[int, int]:
        return dict(self._active_route_table)

    @property
    def active_tdm_schedule(self) -> Dict[int, int]:
        return dict(self._active_tdm_schedule)

    @property
    def has_uncommitted_changes(self) -> bool:
        return self._has_uncommitted_changes

    # -------------------------------------------------------------------------
    # Event Routing Engine
    # -------------------------------------------------------------------------

    def step(self, cycles: int = 1) -> int:
        """Advance simulation clock by given cycle count."""
        self._current_cycle += cycles
        self.metrics.step_cycle(cycles)
        return self._current_cycle

    def route(
        self,
        src: int,
        dst: Optional[int] = None,
        layer: int = 0,
        cycle: Optional[int] = None,
        early_exit: bool = False,
        slot: Optional[int] = None,
    ) -> List[TraceRecord]:
        """Route a single event through the active routing architecture."""
        event = SpikeEvent(
            src=src,
            dst=dst,
            layer=layer,
            cycle=cycle,
            early_exit=early_exit,
            slot=slot,
        )
        return self.route_event(event)

    def route_event(self, event: SpikeEvent) -> List[TraceRecord]:
        """Dispatch an event according to active routing mode."""
        cyc = event.cycle if event.cycle is not None else self._current_cycle
        mode = self._active_mode

        if mode == MODE_STATIC_CROSSBAR:
            return self._route_static_crossbar(event, cyc)
        elif mode == MODE_AER:
            return self._route_aer(event, cyc)
        elif mode == MODE_TDM:
            return self._route_tdm(event, cyc)
        elif mode == MODE_BYPASS:
            return self._route_bypass(event, cyc)
        else:
            rec = self.trace_writer.log(
                cycle=cyc,
                mode=mode,
                src=event.src,
                dst=-1,
                status="DROPPED",
                layer=event.layer,
                reason="UNKNOWN_MODE",
            )
            self.metrics.record_dropped(cyc, mode, event.layer, "UNKNOWN_MODE")
            return [rec]

    # --- Mode 0: Static Crossbar ---
    def _route_static_crossbar(self, event: SpikeEvent, cyc: int) -> List[TraceRecord]:
        layer = event.layer

        # 1. Check layer validity and enable mask
        if layer < 0 or layer >= MAX_LAYERS:
            rec = self.trace_writer.log(
                cycle=cyc, mode=0, src=event.src, dst=-1, status="DROPPED", layer=layer, reason="INVALID_LAYER"
            )
            self.metrics.record_dropped(cyc, 0, layer, "INVALID_LAYER")
            return [rec]

        if not (self._active_layer_mask & (1 << layer)):
            rec = self.trace_writer.log(
                cycle=cyc, mode=0, src=event.src, dst=-1, status="DROPPED", layer=layer, reason="LAYER_DISABLED"
            )
            self.metrics.record_dropped(cyc, 0, layer, "LAYER_DISABLED")
            return [rec]

        # 2. Determine target destination neuron
        target_dst = event.dst if event.dst is not None else (event.src % NEURONS_PER_LAYER)
        if target_dst < 0 or target_dst >= NEURONS_PER_LAYER:
            rec = self.trace_writer.log(
                cycle=cyc, mode=0, src=event.src, dst=target_dst, status="DROPPED", layer=layer, reason="INVALID_DST_NEURON"
            )
            self.metrics.record_dropped(cyc, 0, layer, "INVALID_DST_NEURON")
            return [rec]

        # 3. Check neuron enable mask
        neuron_mask = self._active_neuron_masks.get(layer, 0)
        if not (neuron_mask & (1 << target_dst)):
            rec = self.trace_writer.log(
                cycle=cyc, mode=0, src=event.src, dst=target_dst, status="DROPPED", layer=layer, reason="NEURON_MASKED"
            )
            self.metrics.record_dropped(cyc, 0, layer, "NEURON_MASKED")
            return [rec]

        # 4. Successfully routed
        rec = self.trace_writer.log(
            cycle=cyc, mode=0, src=event.src, dst=target_dst, status="ROUTED", layer=layer, reason="CROSSBAR_OK"
        )
        self.metrics.record_routed(cyc, 0, layer)
        return [rec]

    # --- Mode 1: AER ---
    def _route_aer(self, event: SpikeEvent, cyc: int) -> List[TraceRecord]:
        layer = event.layer
        src = event.src

        # 1. Lookup in route table; missing or 0 dst_mask means invalid address
        if src not in self._active_route_table or self._active_route_table[src] == 0:
            rec = self.trace_writer.log(
                cycle=cyc, mode=1, src=src, dst=-1, status="DROPPED", layer=layer, reason="INVALID_ADDR"
            )
            self.metrics.record_dropped(cyc, 1, layer, "INVALID_ADDR")
            return [rec]

        dst_mask = self._active_route_table[src]

        # 2. Check if target layer is enabled
        if layer < 0 or layer >= MAX_LAYERS or not (self._active_layer_mask & (1 << layer)):
            rec = self.trace_writer.log(
                cycle=cyc, mode=1, src=src, dst=dst_mask, status="DROPPED", layer=layer, reason="LAYER_DISABLED"
            )
            self.metrics.record_dropped(cyc, 1, layer, "LAYER_DISABLED")
            return [rec]

        # 3. Apply neuron enable mask to multicast mask
        layer_neuron_mask = self._active_neuron_masks.get(layer, 0xFF)
        active_multicast = dst_mask & layer_neuron_mask
        if active_multicast == 0:
            rec = self.trace_writer.log(
                cycle=cyc, mode=1, src=src, dst=dst_mask, status="DROPPED", layer=layer, reason="ALL_DST_MASKED"
            )
            self.metrics.record_dropped(cyc, 1, layer, "ALL_DST_MASKED")
            return [rec]

        # 4. Successfully routed multicast
        rec = self.trace_writer.log(
            cycle=cyc,
            mode=1,
            src=src,
            dst=active_multicast,
            status="ROUTED",
            layer=layer,
            reason=f"AER_MULTICAST_0x{active_multicast:02X}",
        )
        self.metrics.record_routed(cyc, 1, layer)
        return [rec]

    # --- Mode 2: TDM Neuron Reuse ---
    def _route_tdm(self, event: SpikeEvent, cyc: int) -> List[TraceRecord]:
        layer = event.layer

        # 1. Determine slot
        if event.slot is not None:
            slot = event.slot
        else:
            num_slots = max(len(self._active_tdm_schedule), 1)
            slot = cyc % num_slots

        # 2. Check if layer is scheduled in this slot
        scheduled_layer = self._active_tdm_schedule.get(slot, None)
        if scheduled_layer != layer:
            rec = self.trace_writer.log(
                cycle=cyc,
                mode=2,
                src=event.src,
                dst=-1,
                status="DROPPED",
                layer=layer,
                reason=f"SLOT_MISMATCH_SLOT{slot}_REQ{layer}_SCHED{scheduled_layer}",
            )
            self.metrics.record_dropped(cyc, 2, layer, "SLOT_MISMATCH")
            return [rec]

        # 3. Check if layer is active
        if not (self._active_layer_mask & (1 << layer)):
            rec = self.trace_writer.log(
                cycle=cyc, mode=2, src=event.src, dst=-1, status="DROPPED", layer=layer, reason="LAYER_DISABLED"
            )
            self.metrics.record_dropped(cyc, 2, layer, "LAYER_DISABLED")
            return [rec]

        # 4. Logical-to-physical neuron mapping
        logical_dst = event.dst if event.dst is not None else (event.src % NEURONS_PER_LAYER)
        physical_neuron = logical_dst % SHARED_PHYSICAL_POOL_SIZE

        # 5. Check if logical neuron is enabled
        layer_neuron_mask = self._active_neuron_masks.get(layer, 0xFF)
        if not (layer_neuron_mask & (1 << logical_dst)):
            rec = self.trace_writer.log(
                cycle=cyc, mode=2, src=event.src, dst=physical_neuron, status="DROPPED", layer=layer, reason="NEURON_MASKED"
            )
            self.metrics.record_dropped(cyc, 2, layer, "NEURON_MASKED")
            return [rec]

        # 6. Successfully routed via shared physical pool
        rec = self.trace_writer.log(
            cycle=cyc,
            mode=2,
            src=event.src,
            dst=physical_neuron,
            status="ROUTED",
            layer=layer,
            reason=f"TDM_PHYS_POOL_P{physical_neuron}",
        )
        self.metrics.record_routed(cyc, 2, layer)
        return [rec]

    # --- Mode 3: Layer Bypass / Early Exit ---
    def _route_bypass(self, event: SpikeEvent, cyc: int) -> List[TraceRecord]:
        layer = event.layer
        target_dst = event.dst if event.dst is not None else (event.src % NEURONS_PER_LAYER)

        # 1. Early exit requested directly from this layer
        if event.early_exit:
            rec = self.trace_writer.log(
                cycle=cyc,
                mode=3,
                src=event.src,
                dst=target_dst,
                status="ROUTED",
                layer=layer,
                reason="EARLY_EXIT",
            )
            self.metrics.record_routed(cyc, 3, layer)
            return [rec]

        # 2. Check if this layer is configured to bypass
        if self._active_bypass_layers.get(layer, False):
            next_layer = layer + 1
            rec = self.trace_writer.log(
                cycle=cyc,
                mode=3,
                src=event.src,
                dst=target_dst,
                status="ROUTED",
                layer=next_layer if next_layer < MAX_LAYERS else layer,
                reason=f"BYPASS_LAYER_{layer}",
            )
            self.metrics.record_routed(cyc, 3, layer)
            return [rec]

        # 3. Standard feedforward in Mode 3 (if no bypass/early exit)
        if layer >= MAX_LAYERS or not (self._active_layer_mask & (1 << layer)):
            rec = self.trace_writer.log(
                cycle=cyc, mode=3, src=event.src, dst=-1, status="DROPPED", layer=layer, reason="LAYER_DISABLED"
            )
            self.metrics.record_dropped(cyc, 3, layer, "LAYER_DISABLED")
            return [rec]

        neuron_mask = self._active_neuron_masks.get(layer, 0xFF)
        if not (neuron_mask & (1 << target_dst)):
            rec = self.trace_writer.log(
                cycle=cyc, mode=3, src=event.src, dst=target_dst, status="DROPPED", layer=layer, reason="NEURON_MASKED"
            )
            self.metrics.record_dropped(cyc, 3, layer, "NEURON_MASKED")
            return [rec]

        rec = self.trace_writer.log(
            cycle=cyc, mode=3, src=event.src, dst=target_dst, status="ROUTED", layer=layer, reason="STANDARD_ROUTED"
        )
        self.metrics.record_routed(cyc, 3, layer)
        return [rec]
