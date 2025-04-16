
module top_mod1;

initial begin
`ifdef SPECIAL_DEFINE
    $display("SPECIAL_DEFINE is defined");
`else
    $display("Error: SPECIAL_DEFINE not defined");
`endif
    $finish;
end


endmodule