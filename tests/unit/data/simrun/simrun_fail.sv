
// Testbench that exits with a nonzero simulator status ($fatal -> exit code 1).
// Used to exercise SimRun `mode: test` (nonzero exit must NOT fail the task;
// the code rides in SimRunResult) vs `mode: run` (nonzero exit fails the task).
module simrun_fail;
    initial begin
        $display("simrun_fail: about to fatal");
        $fatal(1, "deliberate failure");
    end
endmodule
