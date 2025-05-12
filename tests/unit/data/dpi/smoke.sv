
module smoke;

  import "DPI-C" function void dpi_func();

  initial begin
    $display("RES: ==> dpi_func");
    dpi_func();
    $display("RES: <== dpi_func");
    $finish;
  end

endmodule
