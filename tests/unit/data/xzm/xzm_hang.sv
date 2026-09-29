// Never calls $finish: the run ends only at --max-time.
module xzm_hang;
    reg clk = 0;
    always #5 clk = ~clk;
endmodule
