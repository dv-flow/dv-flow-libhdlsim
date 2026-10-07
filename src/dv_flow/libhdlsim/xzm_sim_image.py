#****************************************************************************
#* xzm_sim_image.py
#*
#* Copyright 2023-2025 Matthew Ballance and Contributors
#*
#* Licensed under the Apache License, Version 2.0 (the "License"); you may
#* not use this file except in compliance with the License.
#* You may obtain a copy of the License at:
#*
#*   http://www.apache.org/licenses/LICENSE-2.0
#*
#* Unless required by applicable law or agreed to in writing, software
#* distributed under the License is distributed on an "AS IS" BASIS,
#* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#* See the License for the specific language governing permissions and
#* limitations under the License.
#*
#****************************************************************************
import json
import logging
import os
from dv_flow.mgr import FileSet, TaskMarker
from dv_flow.mgr.task_data import SeverityE
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder, VlTaskSimImageMemento, check_sim_image_uptodate
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData, c_flags
from dv_flow.libhdlsim.xzm_log_parser import XzmLogParser
from dv_flow.libhdlsim import xzm_tool
from svdep import TaskBuildFileCollection

_log = logging.getLogger("xzm.SimImage")

ARTIFACT = "simv.xzb"
MANIFEST = "xezim_image.json"
DPI_LIB = "libxzm_dpi.so"

_CPP_EXTS = (".cc", ".cpp", ".cxx", ".c++", ".C")


def read_manifest(imgdir):
    """The image manifest SimImage wrote into `imgdir`, or {} if absent."""
    try:
        with open(os.path.join(imgdir, MANIFEST), "r") as fp:
            return json.load(fp)
    except Exception:
        return {}


# Coverage level -> kinds. xezim collects coverage at run time, so the image is
# the same at every level; cov.json (written by the base builder) is what
# tells SimRun what to collect. xezim's `statement` is reported as `line`.
_COV_KINDS = {
    "none": [],
    "func": ["covergroup", "user"],
    "code": ["covergroup", "user", "line", "branch"],
    "full": ["covergroup", "user", "line", "branch", "toggle"],
}


class SimImageBuilder(VlSimImageBuilder):

    # xezim loads VPI at run time (--vpi-lib), so forward VPI libs to SimRun.
    forward_vpi = True

    def cov_kinds(self, level):
        return list(_COV_KINDS[level])

    def getRefTime(self, rundir):
        path = os.path.join(rundir, ARTIFACT)
        if os.path.isfile(path):
            return os.path.getmtime(path)
        else:
            raise Exception("artifact (%s) does not exist" % path)

    async def build(self, input, data : VlSimImageData):
        status = 0
        dpi = list(data.dpi)

        self.memento = VlTaskSimImageMemento()

        # Build svdep collection for future uptodate checks
        try:
            info = TaskBuildFileCollection(data.files, data.incdirs).build()
            self.memento.svdeps = info.to_dict()
        except Exception as e:
            self._log.error("Failed to build file collection: %s" % str(e))
            self.markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="Dependency-checking failed: %s" % str(e)))
            status = 1

        prefix = xzm_tool.xezim_prefix(self.ctxt.env)

        # xezim takes DPI code only as a shared library (--dpi-lib, at run
        # time), so C/C++ sources given to the image are built into one here.
        if status == 0 and len(data.csource):
            status |= await self._build_dpi_lib(input, data, prefix)
            dpi.append(os.path.join(input.rundir, DPI_LIB))

        if status == 0:
            cmd = ['xezim', '--compile', '-o', ARTIFACT]

            for incdir in data.incdirs:
                if len(incdir.strip()) > 0:
                    cmd.extend(['-I', incdir])

            for define in data.defines:
                cmd.extend(['-D', define])

            cmd.extend(data.args)
            cmd.extend(data.compargs)
            cmd.extend(data.elabargs)

            # simLib dirs from a SimLib passthrough arrive as sources in
            # data.files; xezim has no precompiled libraries.
            cmd.extend(data.files)

            for top in data.top:
                cmd.extend(['-s', top])

            # data.timing, data.vpi_enable and data.public_flat_rw have no
            # xezim counterpart: timing is always modeled, and VPI and every
            # signal are always available.

            status |= await self.ctxt.exec(
                cmd,
                logfile="xezim_compile.log",
                logfilter=XzmLogParser(
                    notify=lambda m: self.ctxt.add_marker(m),
                    suppress=self.suppress).line)

        if status == 0:
            # Waveform options are run-time flags for xezim, so the format
            # the image was asked for travels to SimRun in the manifest.
            trace_fmt = data.trace_fmt if data.trace_fmt else "none"
            if trace_fmt == "none" and data.trace:
                trace_fmt = "fst"
            with open(os.path.join(input.rundir, MANIFEST), "w") as fp:
                json.dump(dict(
                    artifact=ARTIFACT,
                    version=xzm_tool.xezim_version(self.ctxt.env) or "",
                    trace_fmt=trace_fmt,
                    dpi=dpi), fp, indent=2)

        # Forward DPI libraries to SimRun, which passes them as --dpi-lib.
        for lib in dpi:
            self.output.append(FileSet(
                src=input.name,
                basedir=os.path.dirname(lib),
                files=[os.path.basename(lib)],
                filetype="systemVerilogDPI"))

        return (status, True)

    async def _build_dpi_lib(self, input, data : VlSimImageData, prefix):
        use_cpp = any(src.endswith(_CPP_EXTS) for src in data.csource)
        cmd = ['c++' if use_cpp else 'cc', '-shared', '-fPIC']
        if prefix is not None:
            cmd.extend(['-I', os.path.join(prefix, 'include')])
        for define in data.defines:
            cmd.append('-D%s' % define)
        for incdir in data.incdirs:
            if len(incdir.strip()) > 0:
                cmd.extend(['-I', incdir])
        cmd.extend(c_flags(data))
        cmd.extend(data.csource)
        cmd.extend(['-o', DPI_LIB])

        return await self.ctxt.exec(
            cmd,
            logfile="cc_dpi.log",
            logfilter=XzmLogParser(
                notify=lambda m: self.ctxt.add_marker(m)).line)


async def check_uptodate(ctxt) -> bool:
    ref_path = os.path.join(ctxt.rundir, ARTIFACT)
    if not await check_sim_image_uptodate(ctxt, ref_path):
        return False
    # An artifact is a serialized elaboration. A different xezim build may
    # reject it (format change) or, worse, load it with the old elaboration,
    # so rebuild whenever the xezim on PATH isn't the one that built it.
    built = read_manifest(ctxt.rundir).get("version")
    current = xzm_tool.xezim_version()
    if built is None or current is None or built != current:
        _log.debug("check_uptodate: xezim version changed (%s -> %s)", built, current)
        return False
    return True


async def SimImage(ctxt, input):
    return await SimImageBuilder(ctxt).run(ctxt, input)
