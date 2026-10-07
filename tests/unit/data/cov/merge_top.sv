// Merge test design: what a run covers depends on +mode, so two runs with
// different modes each miss a branch that the other hits, and only their
// merge covers both. No delays, so it builds with or without timing support.
module merge_top;
  int mode = 0;
  logic [3:0] v = 0;
  initial begin
    void'($value$plusargs("mode=%d", mode));
    for (int i = 0; i < 4; i++) begin
      if (mode == 1)
        v = v + 1;
      else
        v = v - 1;
    end
    $display("merge_top mode=%0d v=%0d", mode, v);
    $finish;
  end
endmodule
