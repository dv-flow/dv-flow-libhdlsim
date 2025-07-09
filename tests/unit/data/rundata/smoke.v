
module smoke;

    int fp;
//    reg[7:0] data[0:255];
    string data;
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
