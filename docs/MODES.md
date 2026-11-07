# Router modes and API

Status: simulated in Icarus Verilog only. Not synthesized, not on a board, not yet integrated with the policy engine or dashboard.

## Modes (Python model and Verilog behave identically)

| Mode | Name | What it does | Drop reasons |
|---|---|---|---|
| 0 | Static crossbar | Neuron and layer enable masks | NEURON_MASKED, LAYER_DISABLED |
| 1 | AER | Source address looks up a destination mask in a 1024-entry LUT. Multicast supported. | INVALID_ADDR |
| 2 | TDM neuron reuse | 8 shared physical neurons, 16-slot schedule, logical-to-physical mapping | SLOT_MISMATCH |
| 3 | Bypass / early exit | Skips layers or exits early | none in the demo |

## API the policy engine calls

set_routing_mode(mode)
set_active_layers(n)
set_active_neurons(layer, k)
load_route_table(src, dst_mask)
set_tdm_schedule(slot, layer)
commit()

Everything is staged and applied atomically on commit(), between inputs.

## Trace columns (out/rtl_trace.txt)

cycle,mode,src,dst,status,layer,reason

status is ROUTED or DROPPED. "cycle" is the event index, not latency.

## Limits

3 hidden layers x 8 neurons. 64 staged route entries per commit (extra loads are ignored).

## Not done

Integration with the policy engine (teammate A) and the dashboard (teammate B), synthesis, Zedboard.
