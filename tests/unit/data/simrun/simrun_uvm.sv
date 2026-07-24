
// Minimal UVM-report-summary emitter (no real UVM), so SimUVMCase's log parser
// can be exercised without a UVM build. Prints a PASS summary normally, or a
// FAILED summary (UVM_ERROR: 2) when +fail is given. Always $finish.
module simrun_uvm;
    initial begin
        if ($test$plusargs("fail")) begin
            $display("UVM_ERROR @ 10: uvm_test_top.env.sb [MISCOMPARE] boom");
            $display("UVM_INFO @ 20: uvm_test_top [RESULT] ** TEST FAILED **");
            $display("--- UVM Report Summary ---");
            $display("");
            $display("** Report counts by severity");
            $display("UVM_INFO :    3");
            $display("UVM_WARNING :    0");
            $display("UVM_ERROR :    2");
            $display("UVM_FATAL :    0");
        end else begin
            $display("UVM_INFO @ 20: uvm_test_top [RESULT] ** TEST PASSED **");
            $display("--- UVM Report Summary ---");
            $display("");
            $display("** Report counts by severity");
            $display("UVM_INFO :    5");
            $display("UVM_WARNING :    0");
            $display("UVM_ERROR :    0");
            $display("UVM_FATAL :    0");
        end
        $finish;
    end
endmodule
