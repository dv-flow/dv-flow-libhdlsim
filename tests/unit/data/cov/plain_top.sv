// A design with no functional coverage, for backends that can't compile
// covergroups (the `none` and unsupported-backend tests).
module plain_top;
  logic [3:0] count = 0;
  initial begin
    repeat (4) #5 count = count + 1;
    $display("plain_top done count=%0d", count);
    $finish;
  end
endmodule
