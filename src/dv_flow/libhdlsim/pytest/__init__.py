
import os
import dataclasses as dc
import pytest
import shutil
import pytest_dfm

def hdlsim_available_sims(incl=None, excl=None):
    sims = []
    for sim,exe in [
        ('mti', 'vsim'),
        ('vcs', 'vcs'),
        ('vlt', 'verilator'),
        ('xcm', 'xmvlog'),
        ('xsm', 'xvlog')]:
        if shutil.which(exe) is not None:
            add = True
            if incl is not None and sim not in incl:
                add = False
            if excl is not None and sim in excl:    
                add = False
            print("add: %s" % add, flush=True)
            if add: 
                sims.append(sim)
    print("Available sims: %s" % sims, flush=True)
    return sims

@dc.dataclass
class HdlSimDvFlow(pytest_dfm.DvFlow):
    sim: str = ""

    def __post_init__(self):
        super().__post_init__()
#        self.addOverride("hdlsim", "hdlsim.%s" % self.sim)


#@pytest.fixture(scope='function', params=_available_sims())
@pytest.fixture
def hdlsim_dvflow(request, tmpdir):
    print("request.param: %s" % str(request.param), flush=True)
    dvflow = HdlSimDvFlow(
        request,
        os.path.dirname(request.fspath),
        tmpdir,
        sim=request.param)
    return dvflow
