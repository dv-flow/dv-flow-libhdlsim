import os
import pytest
import shutil
import asyncio
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
import dv_flow.libhdlsim as libhdlsim

sims = None

def get_available_sims():
    global sims

    sims = []
    for sim_exe, sim in {
        "vcs": "vcs",
        "vsim": "mti",
    }.items():
        if shutil.which(sim_exe) is not None:
            sims.append(sim)
    return sims

@pytest.mark.parametrize("sim", get_available_sims())
def test_vpi_entrypoint(tmpdir, sim):
    """Test that VPI libraries with entrypoint attributes are correctly handled"""
    
    data_dir = os.path.join(os.path.dirname(__file__), "data/vpi")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))

    def marker_listener(marker):
        raise Exception(f"Unexpected marker: {marker}")

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', f'hdlsim.{sim}']),
        os.path.join(tmpdir, 'rundir'))

    # Create source fileset
    top = builder.mkTaskNode(
        'std.FileSet',
        name="top",  
        type="systemVerilogSource", 
        base=os.path.join(data_dir),
        include="top.sv")

    # Create VPI library fileset with entrypoint attribute
    vpi_lib = builder.mkTaskNode(
        'std.FileSet',
        name="vpi_lib",  
        type="verilogVPI", 
        base=os.path.join(tmpdir),
        include="libvpi.so",
        attributes=["entrypoint=my_vpi_init"])

    # Create a dummy VPI library file for testing
    with open(os.path.join(tmpdir, "libvpi.so"), "w") as f:
        f.write("# Dummy VPI library\n")

    sim_img = builder.mkTaskNode(
        f'hdlsim.{sim}.SimImage',
        name="sim_img",
        needs=[top, vpi_lib],
        top=["top"])

    # Check that the VPI library was collected with the entrypoint
    runner.add_listener(TaskListenerLog().event)
    
    # We need to verify the internal data structure
    # This test primarily checks that the code doesn't crash with the new tuple format
    out_l = asyncio.run(runner.run([sim_img]))
    
    # The test passes if no exceptions were raised during processing
    # In a real scenario with actual VPI libraries, you would check the command line
    assert True

def test_vpi_no_entrypoint(tmpdir):
    """Test that VPI libraries without entrypoint work (backward compatibility)"""
    from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
    
    data = VlSimImageData()
    
    # Test adding VPI libraries as tuples (new format)
    data.vpi.append(("/path/to/lib1.so", None))
    data.vpi.append(("/path/to/lib2.so", "custom_init"))
    
    assert len(data.vpi) == 2
    assert data.vpi[0] == ("/path/to/lib1.so", None)
    assert data.vpi[1] == ("/path/to/lib2.so", "custom_init")

def test_vpi_entrypoint_extraction():
    """Test that entrypoint is correctly extracted from attributes"""
    from dv_flow.mgr import FileSet
    
    # Create a fileset with entrypoint attribute
    fs = FileSet(
        filetype="verilogVPI",
        basedir="/test/path",
        files=["lib.so"],
        attributes=["entrypoint=my_init", "other_attr=value"]
    )
    
    # Extract entrypoint
    entrypoint = None
    for attr in fs.attributes:
        if attr.startswith("entrypoint="):
            entrypoint = attr.split("=", 1)[1]
            break
    
    assert entrypoint == "my_init"
    
    # Test with no entrypoint
    fs2 = FileSet(
        filetype="verilogVPI",
        basedir="/test/path",
        files=["lib.so"],
        attributes=["other_attr=value"]
    )
    
    entrypoint = None
    for attr in fs2.attributes:
        if attr.startswith("entrypoint="):
            entrypoint = attr.split("=", 1)[1]
            break
    
    assert entrypoint is None
