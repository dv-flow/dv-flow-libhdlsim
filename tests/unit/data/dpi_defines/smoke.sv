module smoke;

  import "DPI-C" function void dpi_func();

  initial begin
`ifdef DPI_C_DEFINE
    // C-only defines must not reach the SV compile
    $display("RES: DPI_C_DEFINE leaked into SV");
`endif
    $display("RES: ==> dpi_func");
    dpi_func();
    $display("RES: <== dpi_func");
    $finish;
  end

endmodule
