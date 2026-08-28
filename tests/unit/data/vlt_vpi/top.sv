module top;
  logic [31:0] sig /*verilator public*/;

  import "DPI-C" context function int probe_sig(string path);

  initial begin
    sig = 32'hdeadbeef;
    if (probe_sig("top.sig") != 1) begin
      $display("%%Error: probe_sig failed");
      $finish;
    end
    $display("VLT VPI PASSED");
    $finish;
  end
endmodule
