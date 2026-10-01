
import os
import pytest
import shutil
import asyncio
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder


def has_vlt():
    return shutil.which("verilator") is not None


@pytest.mark.skipif(not has_vlt(), reason="Verilator not available")
def test_protect_lib(tmpdir):
    """hdlsim.vlt.ProtectLib `uses: hdlsim.SimImage` but is already bound to
    Verilator, so it must build without `-D hdlsim.sim=...`."""
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir)
    with open(os.path.join(src_dir, "adder.sv"), "w") as f:
        f.write("""
module adder(input clk, input [7:0] a, input [7:0] b, output logic [8:0] sum);
  always_ff @(posedge clk) sum <= a + b;
endmodule
""")

    rundir = os.path.join(tmpdir, "rundir")
    runner = TaskSetRunner(rundir)
    builder = TaskGraphBuilder(
        PackageLoader().load_rgy(['std', 'hdlsim.vlt']),
        rundir)
    runner.builder = builder

    rtl = builder.mkTaskNode(
        "std.FileSet",
        name="rtl",
        type="systemVerilogSource",
        base=src_dir,
        include="*.sv")
    plib = builder.mkTaskNode(
        "hdlsim.vlt.ProtectLib",
        name="plib",
        top=["adder"],
        needs=[rtl])

    runner.add_listener(TaskListenerLog().event)
    out = asyncio.run(runner.run(plib))

    assert runner.status == 0

    filetypes = {fs.filetype: fs for fs in out.output
                 if fs.type == 'std.FileSet'}
    assert "systemVerilogSource" in filetypes
    assert "systemVerilogDPI" in filetypes
    so = filetypes["systemVerilogDPI"]
    assert os.path.isfile(os.path.join(so.basedir, so.files[0]))
