`include "uvm_macros.svh"

package tb_pkg;
    import uvm_pkg::*;

    // Reads the DUT register through the UVM DPI backdoor (uvm_hdl_read), so
    // the run only passes if the UVM DPI library is loaded.
    class backdoor_test extends uvm_test;
        `uvm_component_utils(backdoor_test)

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        task run_phase(uvm_phase phase);
            uvm_hdl_data_t v;
            phase.raise_objection(this);
            if (!uvm_hdl_read("uvm_tb.dut.count", v))
                `uvm_error("BACKDOOR", "uvm_hdl_read failed")
            else if (v[7:0] != 8'h5a)
                `uvm_error("BACKDOOR", $sformatf("count=%0h, expected 5a", v))
            else
                `uvm_info("BACKDOOR", "count=5a", UVM_LOW)
            phase.drop_objection(this);
        endtask
    endclass
endpackage

module uvm_tb;
    import uvm_pkg::*;
    import tb_pkg::*;

    counter dut();

    initial run_test();
endmodule
