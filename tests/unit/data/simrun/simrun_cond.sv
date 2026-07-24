
// Passes normally; exits with a nonzero status ($fatal) when +fail is given.
// Lets one built image drive both a passing and a failing suite case.
module simrun_cond;
    initial begin
        if ($test$plusargs("fail")) begin
            $display("simrun_cond: failing");
            $fatal(1, "requested failure");
        end else begin
            $display("simrun_cond: passing");
            $finish;
        end
    end
endmodule
