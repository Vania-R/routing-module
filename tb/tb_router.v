// =============================================================================
// Testbench: tb_router
// Description: Testbench for the reconfigurable neuron-synapse router.
//              - Reads a 64-bit stimulus hex file via $readmemh
//              - Drives commands and spike events via valid/ready handshake
//              - Generates VCD waveform dump (sim.vcd)
//              - Writes out/rtl_trace.txt in the exact format of Python trace
// =============================================================================

`timescale 1ns / 1ps

module tb_router;

    reg clk;
    reg rst;

    // Config interface
    reg        cfg_valid;
    reg [3:0]  cfg_cmd;
    reg [9:0]  cfg_arg0;
    reg [15:0] cfg_arg1;

    // Input event interface
    reg        in_valid;
    wire       in_ready;
    reg [31:0] in_cycle;
    reg [9:0]  in_src;
    reg [3:0]  in_dst;
    reg [1:0]  in_layer;
    reg        in_early_exit;
    reg [3:0]  in_slot;

    // Output event interface
    wire       out_valid;
    reg        out_ready;
    wire [31:0] out_cycle;
    wire [1:0]  out_mode;
    wire [9:0]  out_src;
    wire [7:0]  out_dst;
    wire        out_dst_is_neg1;
    wire        out_status;
    wire [1:0]  out_layer;
    wire [3:0]  out_reason_code;
    wire [7:0]  out_reason_aux;

    // Instantiate Device Under Test
    router dut (
        .clk(clk),
        .rst(rst),
        .cfg_valid(cfg_valid),
        .cfg_cmd(cfg_cmd),
        .cfg_arg0(cfg_arg0),
        .cfg_arg1(cfg_arg1),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .in_cycle(in_cycle),
        .in_src(in_src),
        .in_dst(in_dst),
        .in_layer(in_layer),
        .in_early_exit(in_early_exit),
        .in_slot(in_slot),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .out_cycle(out_cycle),
        .out_mode(out_mode),
        .out_src(out_src),
        .out_dst(out_dst),
        .out_dst_is_neg1(out_dst_is_neg1),
        .out_status(out_status),
        .out_layer(out_layer),
        .out_reason_code(out_reason_code),
        .out_reason_aux(out_reason_aux)
    );

    // Clock generation: 100MHz (10ns period)
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // Configuration Command Opcodes matching RTL
    localparam CFG_CMD_SET_MODE    = 4'd1;
    localparam CFG_CMD_SET_LAYERS  = 4'd2;
    localparam CFG_CMD_SET_NEURONS = 4'd3;
    localparam CFG_CMD_LOAD_ROUTE  = 4'd4;
    localparam CFG_CMD_SET_TDM     = 4'd5;
    localparam CFG_CMD_SET_BYPASS  = 4'd6;
    localparam CFG_CMD_COMMIT      = 4'd7;

    // Reason codes matching RTL
    localparam REASON_CROSSBAR_OK      = 4'd1;
    localparam REASON_NEURON_MASKED    = 4'd2;
    localparam REASON_LAYER_DISABLED   = 4'd3;
    localparam REASON_INVALID_LAYER    = 4'd4;
    localparam REASON_INVALID_DST_NRN  = 4'd5;
    localparam REASON_INVALID_ADDR     = 4'd6;
    localparam REASON_ALL_DST_MASKED   = 4'd7;
    localparam REASON_AER_MULTICAST    = 4'd8;
    localparam REASON_SLOT_MISMATCH    = 4'd9;
    localparam REASON_TDM_PHYS_POOL    = 4'd10;
    localparam REASON_EARLY_EXIT       = 4'd11;
    localparam REASON_LAYER_BYPASS     = 4'd12;
    localparam REASON_STANDARD_ROUTED  = 4'd13;

    // Stimulus memory
    reg [63:0] stim_mem [0:2047];
    integer stim_idx;
    integer trace_fd;
    integer cfg_log_fd;
    reg [31:0] clk_cycle;
    reg [63:0] cur_entry;

    // Clock cycle counter (active after reset deassertion)
    always @(posedge clk) begin
        if (rst) begin
            clk_cycle <= 32'd0;
        end else begin
            clk_cycle <= clk_cycle + 32'd1;
        end
    end

    reg [8*32-1:0] dst_str;
    reg [8*64-1:0] reason_str;

    // Helper function to format 2-digit uppercase hex
    function [15:0] hex_byte_upper;
        input [7:0] val;
        reg [7:0] hi, lo;
        begin
            hi = (val[7:4] < 4'd10) ? (8'd48 + {4'd0, val[7:4]}) : (8'd65 + {4'd0, (val[7:4] - 4'd10)});
            lo = (val[3:0] < 4'd10) ? (8'd48 + {4'd0, val[3:0]}) : (8'd65 + {4'd0, (val[3:0] - 4'd10)});
            hex_byte_upper = {hi, lo};
        end
    endfunction

    // Helper task to format output trace entry
    task format_and_log_trace;
        begin
            // 1. Format destination string
            if (out_dst_is_neg1) begin
                dst_str = "-1";
            end else if (out_dst > 8'd9) begin
                $sformat(dst_str, "0x%0x", out_dst);
            end else begin
                $sformat(dst_str, "%0d", out_dst);
            end

            // 2. Format reason string
            case (out_reason_code)
                REASON_CROSSBAR_OK:     reason_str = "CROSSBAR_OK";
                REASON_NEURON_MASKED:   reason_str = "NEURON_MASKED";
                REASON_LAYER_DISABLED:  reason_str = "LAYER_DISABLED";
                REASON_INVALID_LAYER:   reason_str = "INVALID_LAYER";
                REASON_INVALID_DST_NRN: reason_str = "INVALID_DST_NEURON";
                REASON_INVALID_ADDR:    reason_str = "INVALID_ADDR";
                REASON_ALL_DST_MASKED:  reason_str = "ALL_DST_MASKED";
                REASON_AER_MULTICAST:   $sformat(reason_str, "AER_MULTICAST_0x%s", hex_byte_upper(out_reason_aux));
                REASON_SLOT_MISMATCH: begin
                    if (out_reason_aux[2]) begin
                        $sformat(reason_str, "SLOT_MISMATCH_SLOT%0d_REQ%0d_SCHED%0d", out_reason_aux[7:4], out_layer, out_reason_aux[1:0]);
                    end else begin
                        $sformat(reason_str, "SLOT_MISMATCH_SLOT%0d_REQ%0d_SCHEDNone", out_reason_aux[7:4], out_layer);
                    end
                end
                REASON_TDM_PHYS_POOL:   $sformat(reason_str, "TDM_PHYS_POOL_P%0d", out_reason_aux[2:0]);
                REASON_EARLY_EXIT:      reason_str = "EARLY_EXIT";
                REASON_LAYER_BYPASS:    $sformat(reason_str, "BYPASS_LAYER_%0d", out_reason_aux[1:0]);
                REASON_STANDARD_ROUTED: reason_str = "STANDARD_ROUTED";
                default:                reason_str = "UNKNOWN";
            endcase

            // 3. Write line in exact CSV format
            $fdisplay(trace_fd, "%0d,%0d,%0d,%0s,%0s,%0d,%0s",
                out_cycle,
                out_mode,
                out_src,
                dst_str,
                out_status ? "ROUTED" : "DROPPED",
                out_layer,
                reason_str
            );
        end
    endtask

    // Main Test Sequence
    initial begin
        // VCD Dump
        $dumpfile("sim.vcd");
        $dumpvars(0, tb_router);

        // Open trace file and write CSV header
        trace_fd = $fopen("out/rtl_trace.txt", "w");
        if (trace_fd == 0) begin
            $display("ERROR: Failed to open out/rtl_trace.txt for writing");
            $finish;
        end
        $fdisplay(trace_fd, "cycle,mode,src,dst,status,layer,reason");

        // Open config log file and write CSV header
        cfg_log_fd = $fopen("out/config_log.txt", "w");
        if (cfg_log_fd == 0) begin
            $display("ERROR: Failed to open out/config_log.txt for writing");
            $finish;
        end
        $fdisplay(cfg_log_fd, "cycle,command,args");

        // Load stimulus hex file
        $readmemh("tb/stimulus.hex", stim_mem);

        // Initialize signals
        clk_cycle     = 32'd0;
        rst           = 1'b1;
        cfg_valid     = 1'b0;
        cfg_cmd       = 4'd0;
        cfg_arg0      = 10'd0;
        cfg_arg1      = 16'd0;
        in_valid      = 1'b0;
        in_cycle      = 32'd0;
        in_src        = 10'd0;
        in_dst        = 4'd0;
        in_layer      = 2'd0;
        in_early_exit = 1'b0;
        in_slot       = 4'd0;
        out_ready     = 1'b1;

        // Apply synchronous reset for 3 clock cycles
        @(posedge clk);
        @(posedge clk);
        rst <= 1'b0;
        @(posedge clk);

        // Process stimulus entries
        stim_idx = 0;
        while (stim_idx < 2048) begin
            cur_entry = stim_mem[stim_idx];

            if (cur_entry[63] == 1'b0) begin
                // --- Command Entry ---
                if (cur_entry[62:56] == 7'h7F) begin
                    // EOF sentinel reached
                    stim_idx = 2048;
                end else begin
                    // Wait until DUT is ready to accept commands
                    while (!in_ready) @(posedge clk);

                    cfg_valid <= 1'b1;
                    cfg_cmd   <= cur_entry[59:56];
                    cfg_arg0  <= cur_entry[49:40];
                    cfg_arg1  <= cur_entry[31:16];

                    // Write command entry to out/config_log.txt
                    case (cur_entry[59:56])
                        CFG_CMD_SET_MODE:
                            $fdisplay(cfg_log_fd, "%0d,set_routing_mode,%0d", clk_cycle, cur_entry[49:40]);
                        CFG_CMD_SET_LAYERS:
                            $fdisplay(cfg_log_fd, "%0d,set_active_layers,%0d", clk_cycle, cur_entry[49:40]);
                        CFG_CMD_SET_NEURONS:
                            $fdisplay(cfg_log_fd, "%0d,set_active_neurons,%0d %0d", clk_cycle, cur_entry[49:40], cur_entry[31:16]);
                        CFG_CMD_LOAD_ROUTE:
                            $fdisplay(cfg_log_fd, "%0d,load_route_table,%0d 0x%0x", clk_cycle, cur_entry[49:40], cur_entry[31:16]);
                        CFG_CMD_SET_TDM:
                            $fdisplay(cfg_log_fd, "%0d,set_tdm_schedule,%0d %0d", clk_cycle, cur_entry[49:40], cur_entry[31:16]);
                        CFG_CMD_SET_BYPASS:
                            $fdisplay(cfg_log_fd, "%0d,set_layer_bypass,%0d %0d", clk_cycle, cur_entry[49:40], cur_entry[31:16]);
                        CFG_CMD_COMMIT:
                            $fdisplay(cfg_log_fd, "%0d,commit,", clk_cycle);
                        default: ;
                    endcase

                    @(posedge clk);
                    cfg_valid <= 1'b0;
                    cfg_cmd   <= 4'd0;
                    cfg_arg0  <= 10'd0;
                    cfg_arg1  <= 16'd0;

                    // If command was COMMIT, wait until any internal RAM commit completes
                    if (cur_entry[59:56] == 4'd7) begin
                        @(posedge clk);
                        while (!in_ready) @(posedge clk);
                    end
                    stim_idx = stim_idx + 1;
                end
            end else begin
                // --- Spike Event Entry ---
                // Wait for DUT ready
                while (!in_ready) @(posedge clk);

                in_valid      <= 1'b1;
                in_cycle      <= cur_entry[62:32];
                in_src        <= cur_entry[31:20];
                in_dst        <= (cur_entry[19:12] == 8'hFF) ? 4'hF : cur_entry[15:12];
                in_layer      <= cur_entry[9:8];
                in_early_exit <= cur_entry[7];
                in_slot       <= (cur_entry[6:0] == 7'h7F) ? 4'hF : cur_entry[3:0];

                @(posedge clk);
                in_valid <= 1'b0;

                // Wait for router pipeline output valid
                while (!out_valid) @(posedge clk);

                format_and_log_trace();

                @(posedge clk);
                stim_idx = stim_idx + 1;
            end
        end

        // Drain pipeline and finish
        repeat (10) @(posedge clk);
        $fclose(trace_fd);
        $fclose(cfg_log_fd);
        $display("Simulation complete. Trace written to out/rtl_trace.txt");
        $finish;
    end

endmodule
