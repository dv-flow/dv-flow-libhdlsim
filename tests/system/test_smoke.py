import os
import logging
import pytest
import shutil
import subprocess
import sys


sims = None

def get_available_sims():
    global sims

    sims = []
    for sim_exe,sim in {
        "iverilog": "ivl",
        "verilator": "vlt",
        "vcs": "vcs",
        "vsim": "mti",
        "xsim": "xsm",
    }.items():
        if shutil.which(sim_exe) is not None:
            sims.append(sim)
    return sims

@pytest.mark.parametrize("sim", get_available_sims())
def test_top(tmpdir, sim):
    data_dir = os.path.join(os.path.dirname(__file__), "data/smoke")

    shutil.copy(
        os.path.join(data_dir, "top.sv"),
        os.path.join(tmpdir, "top.sv"))
    
    with open(os.path.join(tmpdir, "flow.dv"), "w") as fp:
        fp.write("""
package:
  name: foo
  imports:
""")
        fp.write("  - name: hdlsim.%s\n" % sim)
        fp.write("    as: hdlsim\n")
        fp.write("""
  tasks:
  - name: files
    uses: std.FileSet
    with:
      type: systemVerilogSource
      include: "*.sv"

  - name: build
    uses: hdlsim.SimImage
    with:
      top: [top]
    needs: [files]

  - name: run
    uses: hdlsim.SimRun
    needs: [build]
""")
        
    print("active log: %d" % logging.root.level)

    cmd = [
        sys.executable, '-m', 'dv_flow.mgr', "-d",
        "run", "run"
    ]
    output = subprocess.check_call(cmd, cwd=os.path.join(tmpdir))

    print("Output: %s" % str(output))
