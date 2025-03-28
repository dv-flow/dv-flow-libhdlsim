
module simrun_plusarg;
    initial begin
        automatic string s;

        if (!$value$plusargs("myarg=%s", s)) begin
            $display("Error: no plusarg found");
        end else begin
            $display("Hello World: %0s", s);
        end
        $finish; 
    end
endmodule