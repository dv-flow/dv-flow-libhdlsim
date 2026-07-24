#****************************************************************************
#* test_backend_select.py
#*
#* End-to-end proof of Feature C: an abstract `uses: hdlsim.SimImage` /
#* `hdlsim.SimRun` flow, with the simulator chosen by a `sim` variable, actually
#* builds and runs on the selected backend. See
#* docs/proposals/task_elaboration_impl_plan.md §C.4.
#****************************************************************************
import os
import shutil
import subprocess
import sys
import pytest


def _have(sim_exe):
    return shutil.which(sim_exe) is not None


@pytest.mark.skipif(not _have("verilator"), reason="verilator not installed")
def test_abstract_form_selects_vlt(tmpdir):
    """`uses: hdlsim.SimImage/SimRun` (generic) + `-D hdlsim.sim=vlt` runs on
    Verilator. Post-`set:` migration the abstract tasks read `${{ hdlsim.sim }}`;
    selection is via `-D hdlsim.sim` (or a subtree `set:`)."""
    data_dir = os.path.join(os.path.dirname(__file__), "data/smoke")
    shutil.copy(os.path.join(data_dir, "top.sv"), os.path.join(tmpdir, "top.sv"))

    with open(os.path.join(tmpdir, "flow.dv"), "w") as fp:
        fp.write('''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: files
    uses: std.FileSet
    with:
      type: systemVerilogSource
      include: "*.sv"
  - name: build
    uses: hdlsim.SimImage
    needs: [files]
    with:
      top: [top]
  - name: run
    uses: hdlsim.SimRun
    needs: [build]
''')

    cmd = [sys.executable, '-m', 'dv_flow.mgr', "run", "-D", "hdlsim.sim=vlt", "run"]
    subprocess.check_call(cmd, cwd=str(tmpdir))
    # A Verilator run log somewhere under the rundir should carry the design's
    # output -- proving the abstract SimRun dispatched to the vlt backend.
    import glob
    logs = glob.glob(os.path.join(str(tmpdir), "rundir", "**", "sim.log"),
                     recursive=True)
    assert logs, "expected a Verilator sim.log under the rundir"
    assert any("Hello World!" in open(p).read() for p in logs)


@pytest.mark.skipif(not _have("verilator"), reason="verilator not installed")
def test_abstract_form_set_selects_vlt(tmpdir):
    """A subtree `set: [{ hdlsim.sim: vlt }]` selects Verilator for the whole
    compound and actually builds+runs."""
    data_dir = os.path.join(os.path.dirname(__file__), "data/smoke")
    shutil.copy(os.path.join(data_dir, "top.sv"), os.path.join(tmpdir, "top.sv"))

    with open(os.path.join(tmpdir, "flow.dv"), "w") as fp:
        fp.write('''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: region
    set:
    - hdlsim.sim: vlt
    body:
    - name: files
      uses: std.FileSet
      with:
        type: systemVerilogSource
        include: "*.sv"
    - name: build
      uses: hdlsim.SimImage
      needs: [files]
      with:
        top: [top]
    - name: run
      uses: hdlsim.SimRun
      needs: [build]
''')

    cmd = [sys.executable, '-m', 'dv_flow.mgr', "run", "region"]
    subprocess.check_call(cmd, cwd=str(tmpdir))
    import glob
    logs = glob.glob(os.path.join(str(tmpdir), "rundir", "**", "sim.log"),
                     recursive=True)
    assert logs, "expected a Verilator sim.log under the rundir"
    assert any("Hello World!" in open(p).read() for p in logs)


@pytest.mark.skipif(not _have("verilator"), reason="verilator not installed")
def test_abstract_form_missing_sim_errors(tmpdir):
    """No `sim` selected anywhere -> build fails with the C.3 diagnostic."""
    data_dir = os.path.join(os.path.dirname(__file__), "data/smoke")
    shutil.copy(os.path.join(data_dir, "top.sv"), os.path.join(tmpdir, "top.sv"))

    with open(os.path.join(tmpdir, "flow.dv"), "w") as fp:
        fp.write('''
package:
  name: foo
  tasks:
  - name: files
    uses: std.FileSet
    with:
      type: systemVerilogSource
      include: "*.sv"
  - name: build
    uses: hdlsim.SimImage
    needs: [files]
    with:
      top: [top]
''')

    cmd = [sys.executable, '-m', 'dv_flow.mgr', "run", "build"]
    proc = subprocess.run(cmd, cwd=str(tmpdir), capture_output=True, text=True)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "No simulator selected" in combined
