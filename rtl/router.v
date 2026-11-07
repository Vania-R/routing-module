// =============================================================================
// Module: router
// Description: Synthesizable Verilog-2001 reference model of a reconfigurable
//              neuron-synapse routing module supporting 4 operating modes:
//                0: Static crossbar with neuron/layer enable masks
//                1: AER lookup RAM with multicast dst mask & invalid-addr drop
//                2: TDM neuron reuse (shared physical pool, slot schedule, map)
//                3: Layer bypass / early exit
//
// Compliant with Icarus Verilog.
// Synchronous reset, valid/ready event interface, staged config with atomic commit.
// Contains NO delays, NO $display, NO initial blocks.
// =============================================================================

`timescale 1ns / 1ps

module router (
    input  wire        clk,
    input  wire        rst,            // Synchronous active-high reset

    // Configuration Interface (Staged in shadow registers until CFG_CMD_COMMIT)
    input  wire        cfg_valid,
    input  wire [3:0]  cfg_cmd,
    input  wire [9:0]  cfg_arg0,       // Mode / Layer / Src / Slot
    input  wire [15:0] cfg_arg1,       // Count / Mask / Layer / Enable

    // Input Spike Event Interface (Valid / Ready handshake)
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [31:0] in_cycle,
    input  wire [9:0]  in_src,
    input  wire [3:0]  in_dst,         // 4'h0..4'h7, or 4'hF if omitted/default
    input  wire [1:0]  in_layer,       // Target layer: 0, 1, or 2
    input  wire        in_early_exit,  // Flag requesting early exit in Mode 3
    input  wire [3:0]  in_slot,        // Explicit TDM slot, or 4'hF to derive from cycle

    // Output Event Interface (Valid / Ready handshake)
    output reg         out_valid,
    input  wire        out_ready,
    output reg  [31:0] out_cycle,
    output reg  [1:0]  out_mode,
    output reg  [9:0]  out_src,
    output reg  [7:0]  out_dst,        // Target neuron (0..7) or multicast mask
    output reg         out_dst_is_neg1,// 1 if dst is -1 (no destination)
    output reg         out_status,     // 1 = ROUTED, 0 = DROPPED
    output reg  [1:0]  out_layer,      // Processed layer
    output reg  [3:0]  out_reason_code,// Diagnostic code for reason string formatting
    output reg  [7:0]  out_reason_aux  // Auxiliary info for reason string formatting
);

    // -------------------------------------------------------------------------
    // Configuration Command Opcodes
    // -------------------------------------------------------------------------
    localparam CFG_CMD_SET_MODE    = 4'd1;
    localparam CFG_CMD_SET_LAYERS  = 4'd2;
    localparam CFG_CMD_SET_NEURONS = 4'd3;
    localparam CFG_CMD_LOAD_ROUTE  = 4'd4;
    localparam CFG_CMD_SET_TDM     = 4'd5;
    localparam CFG_CMD_SET_BYPASS  = 4'd6;
    localparam CFG_CMD_COMMIT      = 4'd7;

    // -------------------------------------------------------------------------
    // Diagnostic Reason Codes
    // -------------------------------------------------------------------------
    localparam REASON_CROSSBAR_OK      = 4'd1;
    localparam REASON_NEURON_MASKED    = 4'd2;
    localparam REASON_LAYER_DISABLED   = 4'd3;
    localparam REASON_INVALID_LAYER    = 4'd4;
    localparam REASON_INVALID_DST_NRN  = 4'd5;
    localparam REASON_INVALID_ADDR     = 4'd6;
    localparam REASON_ALL_DST_MASKED   = 4'd7;
    localparam REASON_AER_MULTICAST    = 4'd8;  // aux = active_multicast
    localparam REASON_SLOT_MISMATCH    = 4'd9;  // aux = {slot[3:0], sched_layer[3:0]}
    localparam REASON_TDM_PHYS_POOL    = 4'd10; // aux = physical_neuron
    localparam REASON_EARLY_EXIT       = 4'd11;
    localparam REASON_LAYER_BYPASS     = 4'd12; // aux = bypassed_layer
    localparam REASON_STANDARD_ROUTED  = 4'd13;

    // -------------------------------------------------------------------------
    // Staged Configuration Registers (Shadow registers)
    // -------------------------------------------------------------------------
    reg [1:0] staged_mode;
    reg [1:0] staged_layers;
    reg [2:0] staged_layer_mask;
    reg [7:0] staged_neuron_masks [0:2];
    reg [1:0] staged_tdm_schedule [0:15];
    reg [15:0] staged_tdm_valid;       // 1 bit per slot indicating scheduled layer
    reg [2:0] staged_bypass_layers;

    // Staged Route Table Buffer (up to 64 staged updates before commit)
    reg [9:0] staged_route_src  [0:63];
    reg [7:0] staged_route_mask [0:63];
    reg [6:0] staged_route_count;

    // -------------------------------------------------------------------------
    // Active Configuration Registers (Latched on CFG_CMD_COMMIT)
    // -------------------------------------------------------------------------
    reg [1:0] active_mode;
    reg [1:0] active_layers;
    reg [2:0] active_layer_mask;
    reg [7:0] active_neuron_masks [0:2];
    reg [1:0] active_tdm_schedule [0:15];
    reg [15:0] active_tdm_valid;
    reg [2:0] active_bypass_layers;

    // AER Lookup Table Memory (1024 depth x 8-bit destination mask)
    reg       active_lut_val  [0:1023];
    reg [7:0] active_lut_mask [0:1023];

    // Commit state machine for sequential RAM updates between inputs
    reg       committing;
    reg [6:0] commit_idx;

    // -------------------------------------------------------------------------
    // Flow Control: Ready Generation
    // -------------------------------------------------------------------------
    // Router can accept events when not currently committing RAM updates and
    // downstream is ready to accept output (or output buffer is empty).
    wire can_accept_event = (!committing) && (!out_valid || out_ready);
    assign in_ready = can_accept_event;

    // -------------------------------------------------------------------------
    // Helper: Compute Neuron Mask from Count 'k' (0..8) or Raw Bitmask
    // -------------------------------------------------------------------------
    function [7:0] compute_neuron_mask;
        input [15:0] k_val;
        begin
            if (k_val <= 16'd8) begin
                case (k_val[3:0])
                    4'd0: compute_neuron_mask = 8'h00;
                    4'd1: compute_neuron_mask = 8'h01;
                    4'd2: compute_neuron_mask = 8'h03;
                    4'd3: compute_neuron_mask = 8'h07;
                    4'd4: compute_neuron_mask = 8'h0F;
                    4'd5: compute_neuron_mask = 8'h1F;
                    4'd6: compute_neuron_mask = 8'h3F;
                    4'd7: compute_neuron_mask = 8'h7F;
                    4'd8: compute_neuron_mask = 8'hFF;
                    default: compute_neuron_mask = 8'hFF;
                endcase
            end else begin
                compute_neuron_mask = k_val[7:0];
            end
        end
    endfunction

    // -------------------------------------------------------------------------
    // Configuration Engine: Staging & Synchronous Reset
    // -------------------------------------------------------------------------
    integer i;
    always @(posedge clk) begin
        if (rst) begin
            // Default active state: Mode 0, 3 layers, all 8 neurons enabled
            active_mode           <= 2'd0;
            active_layers         <= 2'd3;
            active_layer_mask     <= 3'b111;
            active_neuron_masks[0] <= 8'hFF;
            active_neuron_masks[1] <= 8'hFF;
            active_neuron_masks[2] <= 8'hFF;
            active_tdm_valid      <= 16'h0000;
            active_bypass_layers  <= 3'b000;

            staged_mode           <= 2'd0;
            staged_layers         <= 2'd3;
            staged_layer_mask     <= 3'b111;
            staged_neuron_masks[0] <= 8'hFF;
            staged_neuron_masks[1] <= 8'hFF;
            staged_neuron_masks[2] <= 8'hFF;
            staged_tdm_valid      <= 16'h0000;
            staged_bypass_layers  <= 3'b000;

            for (i = 0; i < 16; i = i + 1) begin
                active_tdm_schedule[i] <= 2'd0;
                staged_tdm_schedule[i] <= 2'd0;
            end

            for (i = 0; i < 1024; i = i + 1) begin
                active_lut_val[i]  <= 1'b0;
                active_lut_mask[i] <= 8'h00;
            end

            staged_route_count <= 7'd0;
            committing         <= 1'b0;
            commit_idx         <= 7'd0;
        end else begin
            // 1. Commit state machine: writes staged route table entries to active LUT
            if (committing) begin
                if (commit_idx < staged_route_count) begin
                    active_lut_val[staged_route_src[commit_idx]]  <= (staged_route_mask[commit_idx] != 8'h00);
                    active_lut_mask[staged_route_src[commit_idx]] <= staged_route_mask[commit_idx];
                    commit_idx <= commit_idx + 7'd1;
                end else begin
                    committing         <= 1'b0;
                    staged_route_count <= 7'd0;
                    commit_idx         <= 7'd0;
                end
            end

            // 2. Staged Configuration Commands
            if (cfg_valid && !committing) begin
                case (cfg_cmd)
                    CFG_CMD_SET_MODE: begin
                        staged_mode <= cfg_arg0[1:0];
                    end

                    CFG_CMD_SET_LAYERS: begin
                        staged_layers <= cfg_arg0[1:0];
                        case (cfg_arg0[1:0])
                            2'd1: staged_layer_mask <= 3'b001;
                            2'd2: staged_layer_mask <= 3'b011;
                            2'd3: staged_layer_mask <= 3'b111;
                            default: staged_layer_mask <= 3'b111;
                        endcase
                    end

                    CFG_CMD_SET_NEURONS: begin
                        if (cfg_arg0[1:0] < 2'd3) begin
                            staged_neuron_masks[cfg_arg0[1:0]] <= compute_neuron_mask(cfg_arg1);
                        end
                    end

                    CFG_CMD_LOAD_ROUTE: begin
                        if (staged_route_count < 7'd64) begin
                            staged_route_src[staged_route_count]  <= cfg_arg0[9:0];
                            staged_route_mask[staged_route_count] <= cfg_arg1[7:0];
                            staged_route_count <= staged_route_count + 7'd1;
                        end
                    end

                    CFG_CMD_SET_TDM: begin
                        if (cfg_arg0[4:0] < 5'd16) begin
                            staged_tdm_schedule[cfg_arg0[3:0]] <= cfg_arg1[1:0];
                            staged_tdm_valid[cfg_arg0[3:0]]    <= 1'b1;
                        end
                    end

                    CFG_CMD_SET_BYPASS: begin
                        if (cfg_arg0[1:0] < 2'd3) begin
                            staged_bypass_layers[cfg_arg0[1:0]] <= cfg_arg1[0];
                        end
                    end

                    CFG_CMD_COMMIT: begin
                        // Latch all staged shadow registers atomically
                        active_mode           <= staged_mode;
                        active_layers         <= staged_layers;
                        active_layer_mask     <= staged_layer_mask;
                        active_neuron_masks[0] <= staged_neuron_masks[0];
                        active_neuron_masks[1] <= staged_neuron_masks[1];
                        active_neuron_masks[2] <= staged_neuron_masks[2];
                        active_bypass_layers  <= staged_bypass_layers;
                        active_tdm_valid      <= staged_tdm_valid;

                        for (i = 0; i < 16; i = i + 1) begin
                            active_tdm_schedule[i] <= staged_tdm_schedule[i];
                        end

                        // If route table updates were staged, enter commit state
                        if (staged_route_count > 7'd0) begin
                            committing <= 1'b1;
                            commit_idx <= 7'd0;
                        end
                    end

                    default: ;
                endcase
            end
        end
    end

    // -------------------------------------------------------------------------
    // Mode-Specific Combinational Decision Logic
    // -------------------------------------------------------------------------
    wire [2:0] def_dst_crossbar = in_src[2:0]; // src % 8
    wire [2:0] req_dst_neuron   = (in_dst == 4'hF) ? def_dst_crossbar : in_dst[2:0];
    wire       dst_is_invalid   = (in_dst > 4'd7) && (in_dst != 4'hF);

    // --- Mode 0: Static Crossbar ---
    reg        m0_status;
    reg [7:0]  m0_dst;
    reg        m0_dst_is_neg1;
    reg [1:0]  m0_layer;
    reg [3:0]  m0_reason;
    reg [7:0]  m0_aux;

    always @(*) begin
        m0_layer = in_layer;
        m0_aux   = 8'h00;
        if (in_layer >= 2'd3) begin
            m0_status      = 1'b0;
            m0_dst         = 8'hFF;
            m0_dst_is_neg1 = 1'b1;
            m0_reason      = REASON_INVALID_LAYER;
        end else if (!active_layer_mask[in_layer]) begin
            m0_status      = 1'b0;
            m0_dst         = 8'hFF;
            m0_dst_is_neg1 = 1'b1;
            m0_reason      = REASON_LAYER_DISABLED;
        end else if (dst_is_invalid) begin
            m0_status      = 1'b0;
            m0_dst         = {4'h0, in_dst};
            m0_dst_is_neg1 = 1'b0;
            m0_reason      = REASON_INVALID_DST_NRN;
        end else if (!active_neuron_masks[in_layer][req_dst_neuron]) begin
            m0_status      = 1'b0;
            m0_dst         = {5'd0, req_dst_neuron};
            m0_dst_is_neg1 = 1'b0;
            m0_reason      = REASON_NEURON_MASKED;
        end else begin
            m0_status      = 1'b1;
            m0_dst         = {5'd0, req_dst_neuron};
            m0_dst_is_neg1 = 1'b0;
            m0_reason      = REASON_CROSSBAR_OK;
        end
    end

    // --- Mode 1: AER ---
    reg        m1_status;
    reg [7:0]  m1_dst;
    reg        m1_dst_is_neg1;
    reg [1:0]  m1_layer;
    reg [3:0]  m1_reason;
    reg [7:0]  m1_aux;

    wire       lut_entry_valid = active_lut_val[in_src];
    wire [7:0] lut_entry_mask  = active_lut_mask[in_src];
    wire [7:0] eff_multicast   = lut_entry_mask & active_neuron_masks[in_layer];

    always @(*) begin
        m1_layer = in_layer;
        m1_aux   = 8'h00;
        if (!lut_entry_valid || lut_entry_mask == 8'h00) begin
            m1_status      = 1'b0;
            m1_dst         = 8'hFF;
            m1_dst_is_neg1 = 1'b1;
            m1_reason      = REASON_INVALID_ADDR;
        end else if (in_layer >= 2'd3 || !active_layer_mask[in_layer]) begin
            m1_status      = 1'b0;
            m1_dst         = lut_entry_mask;
            m1_dst_is_neg1 = 1'b0;
            m1_reason      = REASON_LAYER_DISABLED;
        end else if (eff_multicast == 8'h00) begin
            m1_status      = 1'b0;
            m1_dst         = lut_entry_mask;
            m1_dst_is_neg1 = 1'b0;
            m1_reason      = REASON_ALL_DST_MASKED;
        end else begin
            m1_status      = 1'b1;
            m1_dst         = eff_multicast;
            m1_dst_is_neg1 = 1'b0;
            m1_reason      = REASON_AER_MULTICAST;
            m1_aux         = eff_multicast;
        end
    end

    // --- Mode 2: TDM ---
    reg        m2_status;
    reg [7:0]  m2_dst;
    reg        m2_dst_is_neg1;
    reg [1:0]  m2_layer;
    reg [3:0]  m2_reason;
    reg [7:0]  m2_aux;

    wire [3:0] active_slot = (in_slot != 4'hF) ? in_slot : in_cycle[3:0];
    wire       slot_is_sched = active_tdm_valid[active_slot];
    wire [1:0] sched_layer   = active_tdm_schedule[active_slot];
    wire [2:0] phys_pool_nrn = req_dst_neuron; // pool size 8: neuron % 8

    always @(*) begin
        m2_layer = in_layer;
        m2_aux   = 8'h00;
        if (!slot_is_sched || sched_layer != in_layer) begin
            m2_status      = 1'b0;
            m2_dst         = 8'hFF;
            m2_dst_is_neg1 = 1'b1;
            m2_reason      = REASON_SLOT_MISMATCH;
            m2_aux         = {active_slot, 1'b0, slot_is_sched, sched_layer};
        end else if (!active_layer_mask[in_layer]) begin
            m2_status      = 1'b0;
            m2_dst         = 8'hFF;
            m2_dst_is_neg1 = 1'b1;
            m2_reason      = REASON_LAYER_DISABLED;
        end else if (!active_neuron_masks[in_layer][req_dst_neuron]) begin
            m2_status      = 1'b0;
            m2_dst         = {5'd0, phys_pool_nrn};
            m2_dst_is_neg1 = 1'b0;
            m2_reason      = REASON_NEURON_MASKED;
        end else begin
            m2_status      = 1'b1;
            m2_dst         = {5'd0, phys_pool_nrn};
            m2_dst_is_neg1 = 1'b0;
            m2_reason      = REASON_TDM_PHYS_POOL;
            m2_aux         = {5'd0, phys_pool_nrn};
        end
    end

    // --- Mode 3: Bypass / Early Exit ---
    reg        m3_status;
    reg [7:0]  m3_dst;
    reg        m3_dst_is_neg1;
    reg [1:0]  m3_layer;
    reg [3:0]  m3_reason;
    reg [7:0]  m3_aux;

    wire [1:0] next_bypassed_layer = (in_layer + 2'd1 < 2'd3) ? (in_layer + 2'd1) : in_layer;

    always @(*) begin
        m3_aux = 8'h00;
        if (in_early_exit) begin
            m3_status      = 1'b1;
            m3_dst         = {5'd0, req_dst_neuron};
            m3_dst_is_neg1 = 1'b0;
            m3_layer       = in_layer;
            m3_reason      = REASON_EARLY_EXIT;
        end else if (active_bypass_layers[in_layer]) begin
            m3_status      = 1'b1;
            m3_dst         = {5'd0, req_dst_neuron};
            m3_dst_is_neg1 = 1'b0;
            m3_layer       = next_bypassed_layer;
            m3_reason      = REASON_LAYER_BYPASS;
            m3_aux         = {6'd0, in_layer};
        end else if (in_layer >= 2'd3 || !active_layer_mask[in_layer]) begin
            m3_status      = 1'b0;
            m3_dst         = 8'hFF;
            m3_dst_is_neg1 = 1'b1;
            m3_layer       = in_layer;
            m3_reason      = REASON_LAYER_DISABLED;
        end else if (!active_neuron_masks[in_layer][req_dst_neuron]) begin
            m3_status      = 1'b0;
            m3_dst         = {5'd0, req_dst_neuron};
            m3_dst_is_neg1 = 1'b0;
            m3_layer       = in_layer;
            m3_reason      = REASON_NEURON_MASKED;
        end else begin
            m3_status      = 1'b1;
            m3_dst         = {5'd0, req_dst_neuron};
            m3_dst_is_neg1 = 1'b0;
            m3_layer       = in_layer;
            m3_reason      = REASON_STANDARD_ROUTED;
        end
    end

    // -------------------------------------------------------------------------
    // Mode Mux: Select Final Routing Decision
    // -------------------------------------------------------------------------
    reg        mux_status;
    reg [7:0]  mux_dst;
    reg        mux_dst_is_neg1;
    reg [1:0]  mux_layer;
    reg [3:0]  mux_reason;
    reg [7:0]  mux_aux;

    always @(*) begin
        case (active_mode)
            2'd0: begin
                mux_status      = m0_status;
                mux_dst         = m0_dst;
                mux_dst_is_neg1 = m0_dst_is_neg1;
                mux_layer       = m0_layer;
                mux_reason      = m0_reason;
                mux_aux         = m0_aux;
            end
            2'd1: begin
                mux_status      = m1_status;
                mux_dst         = m1_dst;
                mux_dst_is_neg1 = m1_dst_is_neg1;
                mux_layer       = m1_layer;
                mux_reason      = m1_reason;
                mux_aux         = m1_aux;
            end
            2'd2: begin
                mux_status      = m2_status;
                mux_dst         = m2_dst;
                mux_dst_is_neg1 = m2_dst_is_neg1;
                mux_layer       = m2_layer;
                mux_reason      = m2_reason;
                mux_aux         = m2_aux;
            end
            2'd3: begin
                mux_status      = m3_status;
                mux_dst         = m3_dst;
                mux_dst_is_neg1 = m3_dst_is_neg1;
                mux_layer       = m3_layer;
                mux_reason      = m3_reason;
                mux_aux         = m3_aux;
            end
        endcase
    end

    // -------------------------------------------------------------------------
    // Output Event Registers (Synchronous pipeline stage)
    // -------------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            out_valid       <= 1'b0;
            out_cycle       <= 32'd0;
            out_mode        <= 2'd0;
            out_src         <= 10'd0;
            out_dst         <= 8'd0;
            out_dst_is_neg1 <= 1'b0;
            out_status      <= 1'b0;
            out_layer       <= 2'd0;
            out_reason_code <= 4'd0;
            out_reason_aux  <= 8'd0;
        end else if (in_valid && in_ready) begin
            out_valid       <= 1'b1;
            out_cycle       <= in_cycle;
            out_mode        <= active_mode;
            out_src         <= in_src;
            out_dst         <= mux_dst;
            out_dst_is_neg1 <= mux_dst_is_neg1;
            out_status      <= mux_status;
            out_layer       <= mux_layer;
            out_reason_code <= mux_reason;
            out_reason_aux  <= mux_aux;
        end else if (out_valid && out_ready) begin
            out_valid       <= 1'b0;
        end
    end

endmodule
