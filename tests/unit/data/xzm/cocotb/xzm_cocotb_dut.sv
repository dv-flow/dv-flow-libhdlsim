module xzm_cocotb_dut(input logic clk, input logic [7:0] a, output logic [7:0] y);
  always_ff @(posedge clk) y <= a + 8'd1;
endmodule
