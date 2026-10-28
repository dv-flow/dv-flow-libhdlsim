// Busy enough for a sampling profiler to see: constraint solving, class
// code, a covergroup, an assertion and 16 RTL instances.
module prof_cnt (input clk, output logic [31:0] q);
  initial q = 0;
  always @(posedge clk) q <= q + 1 + (q >> 3) ^ (q << 5);
endmodule

class prof_item;
  rand bit [15:0] a, b;
  constraint c { a < b; a + b < 1000; }
  int hist[$];
  function void work();
    for (int i = 0; i < 50; i++) hist.push_back(a ^ i);
    if (hist.size() > 500) hist.delete();
  endfunction
endclass

module prof_top;
  logic clk = 0;
  logic [31:0] q[16];
  bit [7:0] v;
  covergroup cg @(posedge clk);
    cp: coverpoint v;
    cl: coverpoint v[3:0];
    cx: cross cp, cl;
  endgroup
  cg cg_i = new;
  for (genvar i = 0; i < 16; i++) begin : g
    prof_cnt u (.clk(clk), .q(q[i]));
  end
  a_q: assert property (@(posedge clk) q[0] != 32'hdeadbeef);
  initial begin
    prof_item it = new;
    int s = 0;
    repeat (30000) begin
      #5 clk = 1; #5 clk = 0;
      void'(it.randomize()); it.work(); s += it.a; v = s[7:0];
    end
    $display("done s=%0d", s);
    $finish;
  end
endmodule
