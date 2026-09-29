// $error without $fatal: with --error-exit the run must fail.
module xzm_error;
    initial begin
        $error("deliberate error");
        #10;
        $display("xzm_error: after error");
        $finish;
    end
endmodule
