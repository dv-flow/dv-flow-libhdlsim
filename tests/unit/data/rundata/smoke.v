
module smoke;

    int fp;
`ifdef __ICARUS__
    reg[128*8-1:0] data;
`else
    string data;
`endif
    initial begin

        fp = $fopen("smoke.dat", "r");
        if (fp == 0) begin
            $display("Failed to open smoke.dat");
            $finish;
        end
        $fgets(data, fp);
        $display("Data: %0s", data);
        $finish;
    end

endmodule
