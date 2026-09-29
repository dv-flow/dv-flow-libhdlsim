// $warning only: the run must pass.
module xzm_warning;
    initial begin
        $warning("deliberate warning");
        #10;
        $finish;
    end
endmodule
