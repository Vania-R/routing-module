# Reconfigurable Neuron-Synapse Routing Module

A standalone Python reference model of a reconfigurable neuron-synapse routing module for neuromorphic hardware architectures.

## Architecture Overview

The routing module interconnects a deep neuromorphic network consisting of **up to 3 hidden layers** (Layer 0, 1, 2) with **8 neurons each** (neurons 0..7). The routing architecture supports four runtime operating modes:

1. **Mode 0: Static Crossbar with Enable Masks**
   - Direct feedforward crossbar connectivity between layers.
   - Neuron and layer enable masks dynamically gate traffic. Disabled neurons or layers result in dropped spikes.
2. **Mode 1: Address-Event Representation (AER)**
   - Source-address lookup table (`route_table[src] -> dst_mask`).
   - Multicast destination mask routes spikes to multiple target neurons in parallel.
   - Unmapped/invalid source addresses are dropped (`INVALID_ADDR`).
3. **Mode 2: Time-Division Multiplexing (TDM) Neuron Reuse**
   - Reuses a compact **shared physical pool of 8 neurons** across the 3 logical layers.
   - Time-division slot schedule (`schedule[slot] -> layer`) assigns physical neurons to logical layers.
   - Logical-to-physical neuron mapping (`p = logical_neuron % 8`).
   - Slot mismatch drops spikes when incoming events do not align with the currently scheduled layer.
4. **Mode 3: Layer Bypass / Early Exit**
   - Enables low-latency early exit from intermediate layers directly to network output.
   - Per-layer bypass allows selective skipping of hidden layers for adaptive computation.

## Staged Configuration API

All configuration changes are staged into shadow registers and **only applied on `commit()`**, ensuring clean transitions between input spikes.

```python
from routing_module import RoutingModule, ErrorCode

router = RoutingModule()

# 1. Mode selection (0: Static, 1: AER, 2: TDM, 3: Bypass)
err = router.set_routing_mode(0)
assert err == ErrorCode.SUCCESS

# 2. Layer activation (1..3 layers)
err = router.set_active_layers(2)

# 3. Neuron activation per layer (k neurons active, or explicit 8-bit mask)
err = router.set_active_neurons(layer=0, k=8)
err = router.set_active_neurons(layer=1, k=4)  # First 4 neurons enabled

# 4. AER Route table loading
err = router.load_route_table(src=10, dst_mask=0x15)  # Multicast to neurons 0, 2, 4

# 5. TDM Slot scheduling
err = router.set_tdm_schedule(slot=0, layer=0)
err = router.set_tdm_schedule(slot=1, layer=1)
err = router.set_tdm_schedule(slot=2, layer=2)

# 6. Commit staged registers to active hardware registers
err = router.commit()
assert err == ErrorCode.SUCCESS
```

## Trace Writer & Metrics

Every routed or dropped event logs a structured trace tuple `(cycle, mode, src, dst, status, layer)`:
- `cycle`: Simulation cycle.
- `mode`: Active routing mode (0..3).
- `src`: Source neuron/address.
- `dst`: Destination neuron, multicast mask, or physical pool index.
- `status`: Outcome (`ROUTED` or `DROPPED`).
- `layer`: Target hidden layer.

Cumulative execution metrics track:
- `routed`: Number of spikes successfully routed.
- `dropped`: Number of spikes dropped (with diagnostic reason codes).
- `cycles`: Total simulation cycles elapsed.

## Quick Start & Commands

```bash
# Run pytest test suite
make test

# Run interactive 4-mode demo with mid-run reconfiguration, table output, and plot generation
make demo
```
