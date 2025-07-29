
import os
import dataclasses as dc
import logging
import pytest
import shutil
import pytest_dfm

_log = logging.getLogger("libhdlsim.pytest")

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
                _log.debug("Simulator %s is not included" % sim)
                add = False
            if excl is not None and sim in excl:
                _log.debug("Simulator %s is excluded" % sim)
                add = False
            if add: 
                _log.debug("Adding simulator %s" % sim)
                sims.append(sim)
            else:
                _log.debug("Not adding simulator %s" % sim)
    _log.debug("Available sims: %s" % sims, flush=True)
    return sims

@dc.dataclass
class HdlSimDvFlow(pytest_dfm.DvFlow):
    sim: str = ""

    def __post_init__(self):
        super().__post_init__()
        self.sim = self.request.param


#@pytest.fixture(scope='function', params=_available_sims())
@pytest.fixture
def hdlsim_dvflow(request, tmpdir):
    dvflow = HdlSimDvFlow(
        request,
        os.path.dirname(request.fspath),
        tmpdir)
    return dvflow
