// Short run with activity, for waveform tests.
module xzm_trace;
    reg [3:0] cnt = 0;
    initial begin
        $dumpfile("xzm_trace.vcd");
        $dumpvars(0, xzm_trace);
        repeat (4) #5 cnt = cnt + 1;
        $finish;
    end
endmodule
