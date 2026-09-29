`include "uvm_macros.svh"
module xzm_uvm_tb;
    import uvm_pkg::*;

    class pass_test extends uvm_test;
        `uvm_component_utils(pass_test)
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        task run_phase(uvm_phase phase);
            phase.raise_objection(this);
            #10;
            `uvm_info("PASS", "pass_test running", UVM_LOW)
            phase.drop_objection(this);
        endtask
    endclass

    // Never drops its objection: the run ends only at --max-time.
    class hang_test extends uvm_test;
        `uvm_component_utils(hang_test)
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        task run_phase(uvm_phase phase);
            phase.raise_objection(this);
            forever #10;
        endtask
    endclass

    initial run_test();
endmodule
