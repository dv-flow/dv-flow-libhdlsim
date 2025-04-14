
module simrun_plusarg;
    string s;

    initial begin

        if (!$value$plusargs("myarg=%s", s)) begin
            $display("Error: no plusarg found");
        end else begin
            $display("Hello World: %0s", s);
        end
        $finish; 
    end
endmodule