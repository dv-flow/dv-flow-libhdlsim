# Simulator profiling — Design

Status (2026-10-12): **phases 0-4 implemented** (coarse stats on
vcs/xcm/mti; `prof.py`, SimProfArgs, vcs + xcm `time`/`mem`; mti
`time`/`mem`, vlt `time`; `SimProfReport`; libproject `prof` knob,
`flags-prof`, `profile` root); phase 5 started: the deep-profiler
mechanism and Xcelium xProf (`hdlsim.XcmProfArgs`). See [Decisions](#decisions) and
[Implementation notes](#implementation-notes). Modeled on coverage
(`hdlsim.SimCovArgs`, `cov.json`, `simCovDb`, `SimCovMerge`, and libproject's
`cov` knob / `flags-cov` / `flags-img` / `coverage` root).

## What the simulators offer

Surveyed from the installed docs, with a small smoke test on each tool.
Versions: VCS Y-2026.03, Xcelium 26.03-s005, Questa 2026.1, Verilator 5.052.

| | VCS | Xcelium | Questa | Verilator |
|---|---|---|---|---|
| **CPU time** (module / instance / construct) | `vcs -simprofile` + `simv -simprofile time` | `xmsim -profile` (sampling, low overhead) | `vsim -fprofile+perf[=high]` | `--prof-cfuncs --prof-c` → gprof |
| **Memory** | `simv -simprofile mem` | `xmsim -memdetail` | `vsim -fprofile+mem` | — |
| **Needs a profiling build?** | **yes**, and a clean rebuild (no incremental compile) | no (`-profile` is runtime-only in 3-step) | no (`vopt -fprofile` optional, adds usage data) | **yes** |
| **Raw output** | `simprofile_dir/` | `xmprof.out` / `xmprofmem.{out,json}` | `fprofile/*.fdb` | `gmon.out` |
| **Report written at end of run** | `profileReport.{json,txt,html}` + `profileReport/` | `xmprof.out` *is* the report | none; needs `visualizer -fbatch …+report=x.csv+csv` | none; needs `gprof` + `verilator_profcfunc` |
| **Machine-parseable** | JSON | fixed-format text; JSON for mem | CSV (via visualizer) | text |
| **Solver / randomize** | `time_solver` view | "Time In Randomize Calls/Classes" | `+solver`, `profile report -solver` | n/a |
| **DPI / PLI** | `time_pli` (HTML only) | `-plidebug` splits user vs interface | regions in calltree | — |
| **Covergroup cost** | `Time.Coverage` in JSON | not broken out | capacity `COVERGROUP` | — |
| **Deep / vendor-only** | UVM profiler (`-simprofile=uvm`, `uvmprofrpt`); FGP `-fgp=diag:ruse` | xProf (`xmelab -xprof`, `xprof -batch`, `xprof_merge`) | classic profiler, `capstats` | `--prof-exec` + `verilator_gantt` (threads); `--prof-pgo` |
| **Coarse end-of-run stats** | `-reportstats` | `-perfstat` → `xmperfstat.out` | `vsim -stats=perf,time` | printed by default |
| **License** | unified profiler is "LCA" | none seen | doc: "requires an additional license" | — |

Things that shape the design:

- **Time and memory are not cumulative.** VCS and Questa both say to profile
  them in separate runs because together they skew each other. So this is a
  *mode*, not a cumulative level like coverage.
- **VCS and Verilator must rebuild the image**, so the request has to reach
  SimImage (as coverage does). Xcelium and Questa could profile any image.
- **Verilator has no memory profiler.** Its CPU profile is gprof-based,
  de-optimizes the model, and covers C++ functions mapped back to Verilog
  blocks, not instances.
- Doc vs reality: Questa's docs claim `vsim -fprofile+perf+report=…`; 2026.1
  rejects `+report` (`vsim-16076`). Reports come from `visualizer` only.
- VCS's `profileReport.json` `DatabaseInformation` block and Xcelium's
  `xmprof.out` header contain host and user names. Scrub them from test fixtures.

## Recommendation

### 1. Vocabulary: one mode, `none | time | mem`

```yaml
- name: SimProfArgs
  doc: Profiling request for SimImage (and, via the image, SimRun)
  with:
    mode: { type: str, value: "${{ hdlsim.prof }}" }   # none | time | mem
```

- Package variable `hdlsim.prof` (default `none`), so `-D hdlsim.prof=time`
  flips a flow with a bare `uses: hdlsim.SimProfArgs`, just like `hdlsim.cov`.
- SimImage gets a `prof` param. Unlike coverage there is no "highest wins":
  if the param and the consumed SimProfArgs disagree on two non-`none` modes,
  it is an error.
- `time` includes the solver, DPI and covergroup breakdowns wherever the tool
  puts them in its time profile. They are not separate modes.
- A backend that can't do a mode warns once and builds without it (Verilator
  `mem`; xzm, ivl, xsm everywhere), the same rule as coverage.

The deep profilers (xProf, the VCS UVM profiler, Verilator `--prof-exec`,
Questa classic/capacity) have no common shape. Following the "vendor-specific
first" rule, they are not part of `mode`. Each simulator gets **typed args of
its own** in `hdlsim` (`hdlsim.XcmProfArgs { xprof }`, later
`VcsProfArgs { uvm }`, `VltProfArgs { exec }`), which every SimImage
consumes and only that simulator's acts on, plus the same switch as a param
on its per-sim SimImage (`hdlsim.xcm.SimImage: xprof`). Params alone would
be out of reach of a flow built on the generic SimImage (all of libproject);
typed args travel the same path as `SimProfArgs`, and one flow can carry
every simulator's request. See [Phase 5](#phase-5-deep-profilers).

### 2. The image is the source of truth (same as coverage)

- `VlSimImageBuilder` gets `prof_supported(mode) -> bool` and
  `_resolve_prof()`, which mirror `cov_kinds` / `_resolve_cov`. It records
  `prof.json` (`{mode}`) in the image dir and removes a stale record on rebuild.
- `VLSimRunner` reads `prof.json` and adds the backend's run flags through a
  new `prof_args(data)` hook. Before the run it removes a stale profile, as
  `_remove_cov_db` does.
- Per backend:
  - **vcs**: `-simprofile` at build. `simv -simprofile time|mem
    -simprofile_dir_path <rundir>/simprofile_dir`. When the prof state
    changes, wipe `csrc`/`simv.daidir` (VCS has no incremental profiling compile).
  - **xcm**: no elab flag. `xmsim -profile` (time) or `-memdetail` (mem).
    Add `-profthread` when DPI libs are loaded.
  - **mti**: `vopt -fprofile`, `vsim -fprofile+perf=high` or `+mem`, then
    `visualizer -fbatch -fprofile+perf+report=prof.csv+csv` after the run.
  - **vlt**: `--prof-cfuncs --prof-c` at build. After the run, `gprof` +
    `verilator_profcfunc`. `mem` is unsupported.

### 3. Results

- **Artifacts** on SimRunResult, through `_artifact_spec`:
  - `simProfDb` (`role=prof`, `format=` one of `vcs-simprofile`,
    `xcelium-xmprof`, `xcelium-xmprofmem`, `questa-fdb`, `vlt-gmon`): the raw
    database, kept for re-reporting in the vendor GUI.
  - `simProfReport` (`role=prof-report`): the human report
    (`profileReport.html`, `xmprof.out`, the visualizer text report,
    `verilator_profcfunc` output).
- **`prof_summary.json`** in the rundir: a sim-neutral normalized summary,
  written by a new `parse_prof_summary` runner hook:
  ```json
  {"mode": "time", "sim": "vcs",
   "categories": {"hdl": 61.2, "solver": 22.0, "pli": 9.1, "kernel": 7.7},
   "top": [{"scope": "module", "name": "fifo", "pct": 18.4, "instances": 4}, ...]}
  ```
  Category vocabulary (like `cov.KINDS`): `hdl`, `tb` (SV class code),
  `solver`, `pli` (DPI/PLI/VPI), `assert`, `cov`, `kernel`. Each tool maps
  its own names onto these, and the map is only present where the tool
  reports it. This mapping must be validated against real output per tool.
- **Stats** (sparse, added to `sim_stats.STAT_KEYS`):
  - `prof_<cat>_pct` with agg `none`;
  - `prof_<cat>_s` with agg `sum` (pct × `cpu_total_s`). The suite roll-up
    then gives "seconds spent in the solver across the regression" for free,
    with no change to SimSuiteReport;
  - for `mem`: `prof_mem_peak_mb` (agg `max`) and `prof_mem_dynamic_mb`.
- **`runinfo.prof`** = `{mode}`.

### 4. `SimProfReport`: the suite-level verb (analog of SimCovMerge)

Profiles don't merge the way coverage does. The regression question is
"which tests and which modules eat the farm". So `SimProfReport` is
**sim-neutral**: it reads `prof_summary.json` from the SimRunResult /
TestResult / SuiteResult artifacts it `needs:` and writes:

- tests ranked by CPU time;
- top modules weighted by each test's CPU time;
- category totals.

Output is a `simProfReport` FileSet (text + JSON) plus a `SimProfReportResult`
item. Vendor merges (`xprof_merge`, `xmprofmerge.pl`) can follow later as
per-sim overrides, the same way SimCovMerge dispatches.

### 5. Separable quick win: coarse stats on vcs, xcm and mti

`parse_sim_stats` is implemented only for Verilator. Its docstring already
names vcs, mti and xcm as candidates. VCS `-reportstats`, Xcelium `-perfstat`
and Questa `-stats=perf,time` give simulator-reported CPU, memory and
elab/sim time split for almost no cost. This fills `sim_cpu_s`, `sim_mem_mb`
and `sim_walltime_s` without profiling, and is independent of the `prof` knob.

## libproject

Same shape as coverage (`packages/dv-flow-libproject/COVERAGE_DESIGN.md`):

1. **Knob** `prof` in `project.dv`: `none | time | mem`, `cli: true`, default
   `none`. The name matches `hdlsim.prof`, so `--prof time` also reaches bare
   `hdlsim.SimProfArgs`. It is a separate axis, not a `build` value. The
   `flags.rst` example of adding a `prof` *build variant* should change to
   point at the knob, since `opt`+`time` is the normal combination.
2. **Holder** `flags-prof`: `uses: hdlsim.SimProfArgs`,
   `with: {mode: "${{ prof }}"}`.
3. **Bundle**: add `flags-prof` to `flags-img`. This is the one-line change
   the bundle was created for; leaves using `flags-img` need no edit. Runs need
   nothing, because SimRun follows the image.
4. **Root** `profile`: `uses: hdlsim.SimProfReport`, `needs: [tests]`,
   `with: {sim: "${{ sim }}"}`. It has the same `-D tests=…` selection
   caveat as `coverage`.
5. **Tests**: copy the coverage tests in `tests/unit/test_archetypes.py`
   (knob from CLI, unknown value rejected, holder follows knob, bare hdlsim
   request, bundle forwards). Add an end-to-end test that `prof.json` is
   recorded, gated on a tool.

It depends on the same two unreleased dv-flow-mgr fixes that coverage does
(`flags-img` honoring knobs, unqualified `--cov` reaching `hdlsim.cov`).

## Phasing

| Phase | Scope | Verify with |
|---|---|---|
| 0 | `parse_sim_stats` for vcs / xcm / mti (coarse stats) | captured log fixtures + gated live runs |
| 1 | `prof.py` (vocab, `prof.json`, summary schema, parsers), `SimProfArgs`, `hdlsim.prof`, SimImage `prof`, builder/runner hooks, **vcs + xcm** `time`/`mem` | fixture parser tests; live tests gated on `vcs` / `xmsim` |
| 2 | **mti** (fprofile + visualizer report) and **vlt** (`time` via gprof) | gated; mti also gated on the profiler license |
| 3 | `SimProfReport` + `SimProfReportResult` | pure-Python tests on synthetic summaries |
| 4 | libproject knob / holder / bundle / `profile` root + docs | `test_archetypes.py` additions |
| 5 | Vendor deep profilers as per-sim typed args: xProf (done), VCS UVM profiler, vlt `--prof-exec` | gated live tests per profiler |

VCS and Xcelium go first because both write a parseable report with no
post-processing step.

## Costs and caveats

- Changing `prof` rebuilds every image that wires `flags-prof`. This happens
  even on xcm and mti, where the build flags barely change, because the
  consumed item changes the image's inputs. See open question 1.
- Profiling with coverage on, or a `dbg` build (`+acc`, `-debug_access`),
  attributes that cost to the design. Document this; don't forbid it.
- Questa: profiler licensing on other sites may fail. Detect it and report a
  clear error.
- Verilator on this host: the default g++ 9 can't build `--timing` models,
  and `gprof` must match the compiler. Use the packaged 5.052.

## Implementation notes

Changes from the design above, found while implementing phases 0-4:

- **`other` category.** Added to the vocabulary for names a tool reports that
  the mapping doesn't know, so the categories still sum to 100%.
- **`simProfSummary` artifact** (`role=prof-summary`) carries
  `prof_summary.json`, so SimProfReport (phase 3) finds it by filetype.
- **No `prof_mem_dynamic_mb`.** Neither tool reports it in a comparable way.
  `prof_mem_peak_mb` is the peak as each tool defines it: VCS's and
  Questa's (VSZ) cover the whole process image (libraries included),
  Xcelium's is physical memory.
- **No `-profthread`** on xcm (decision 2).
- **Category mapping, as validated:**
  - VCS: `CONSTRAINT`→solver. `VERILOG` is split by sub-component:
    `Module`→hdl, `Package`→tb, `Functional Coverage`/`Function Coverage
    Kernel`→cov, the remainder→hdl. `PLI/DPI/DirectC`→pli;
    `KERNEL`/`UCLI`→kernel.
  - Xcelium: the Technology-wise table gives Randomization→solver,
    TB/SV→tb, RTL/Design→hdl, Miscellaneous→kernel. The Stream Type table
    then moves `Outside engine` from kernel to pli and `Assertions` from
    hdl to assert. The hit counts reconcile exactly on the fixture.
    Xcelium doesn't break out covergroup time.
  - Questa `time` (Performance/Summary): Solver→solver, `C code`→pli,
    Assertions→assert, Coverage→cov, Kernel→kernel, SV/Verilog/VHDL→hdl.
    `SV` holds class code and RTL alike, so Questa has no `tb`.
  - Questa `mem` (Memory Overview, shares of the current VSZ):
    Kernel/Reserved→kernel, Non-Kernel→other; under HDL,
    Assertions/Solver/Covergroups→assert/solver/cov, classes, queues and
    strings→tb, the rest→hdl.
  - Verilator (`verilator_profcfunc` types): VBlock/VCommon→hdl,
    VLib/Prof→kernel; plain C++ by name: `VlRandom*`/`VlSolver*`→solver,
    `VlCover*`→cov, other `Vl*`/`Verilated*`→kernel, else→other.
- **VCS writes `profileReport.*` into the cwd** (the rundir) and the raw
  data into `<-simprofile_dir_path>/simprofile_dir`. The path must already
  exist, or VCS fails with `SIMPROFILE-DIR-NO-ACCESS`.
- **Questa reports from the text report, not CSV.** One `visualizer
  -fbatch -fprofile+perf|mem+dir=fprofile+report=prof_report.txt` run
  (about 2 s) gives both the human report and the parsed tables; the tables
  read have no free-text column, so splitting on `|` is safe. visualizer
  picks up vopt's FDB (in the image's `fprofile/`) through the vsim FDB.
- **visualizer can hang after reporting** when its stdin is an open socket:
  it writes the whole report, then never exits. With stdin closed it exits
  in ~2 s, so `_run_report` now closes stdin for every report tool.
- **Questa samples coarsely**: about 30 samples per CPU second even at
  `perf=high`.
- **Verilator's gprof view is partial.** gprof samples only the simv text
  (not shared libraries or children), and the constraint solver is a forked
  SMT process, so a `randomize()`-heavy run attributes little to `solver`.
  `top` is per source file (`__PROF__<file>__l<line>`), scope `file`.
  `--prof-cfuncs` changes compiler and link flags that make doesn't track,
  so a mode change wipes `obj_dir`. Building needs a g++ with coroutines
  for `--timing` designs; the host default g++ 9 can't.
- **Missing or failing report tools warn.** Unlike coverage (debug log
  only), mti/vlt add a Warning marker when visualizer, gprof or
  `verilator_profcfunc` is missing or fails: the user asked for a profile.
- **SimProfReport has a section per mode.** Time and memory don't add up
  the same way, so `prof_report.json` (and SimProfReportResult) has a `time`
  and a `mem` section. `time` sums each run's category and module shares of
  its CPU time (`cpu_total_s`, else `sim_cpu_s`); a run with neither is
  listed but left out, with a warning. `mem` gives mean category shares and
  each module's largest footprint in any run. Modules are keyed by
  (scope, name), so a Verilator file and a module of the same name stay
  apart. Module totals are lower bounds, since a summary keeps its top 20.
  It reads no bare `simProfSummary` FileSets: without the run's stats there
  is no CPU time to weight by.
- **libproject's `profile` root has no `sim`.** SimProfReport doesn't
  depend on the simulator, so there is nothing to select. Having no
  elaborator, it also doesn't need the dv-flow-mgr rebinding fix that
  `coverage` does (an inherited root keeping the leaf's `tests` override).
  `flags.rst`'s "adding a build variant" example now uses `xprop` instead
  of `prof`.
- **`xmprofmem.json` is not one JSON document.** It is a stream of objects,
  one per sample, with sizes in KB.
- **Phase-0 overhead measured** on a 400k-cycle randomizing design (user CPU
  with vs without): VCS `-reportstats` 6.94 vs 7.17 s; Xcelium `-perfstat`
  3.58 vs 3.44 s; Questa `-stats=perf,time` 8.51 vs 8.42 s. All within
  noise, so the switches are always on (skipped when the user's args already
  carry them). Xcelium prints no CPU or memory figures at all without
  `-perfstat`. VCS prints simulated time with a unit only when the design
  has a timescale, so `simtime` is absent otherwise.

## Phase 5: deep profilers

- **Mechanism.** A backend declares `prof_deep_type` (the args type it reads)
  and `prof_deep` (its bool switches). The image base ORs each switch across
  its SimImage params and consumed items of that type into
  `data.prof_deep`, calls `check_prof_deep()` to validate the combination
  with the mode, and records both in `prof.json`:
  `{"mode": "time", "deep": {"xprof": true}}`. A record with mode `none`
  and a deep profiler is valid; the runner writes `prof_summary.json` only
  for a mode.
- **Outputs.** The deep profiler's database is `simProfDb` with its own
  `format=` and its reports `simProfReport`, replacing the mode's (an xProf
  snapshot doesn't write the mode's files anyway). No summary, no stats.
- **libproject.** No knob. A project adds the simulator's holder to its
  image's `needs:` next to `flags-img`. A `--prof-deep` on/off knob can come
  later if a common case appears.
- **Xcelium xProf** (measured, 26.03): `xmelab -xprof` alone is enough; xmsim
  writes `<prof_work>/prof_cpu_<n>/{prof_db,raw_data}` plus a `prof_cpu`
  link, and builds `prof_db` itself at exit. On that snapshot
  `xmsim -profile` writes no `xmprof.out` and `-memdetail` writes nothing,
  so `time` reads `prof_cpu/.xmprof_summary.out` (the same tables) and `mem`
  is an error. `xprof -batch` waits on stdin without `-input`, tries the
  default `xprof_report_dir` before a script's `load` (an `*E,INVRND`, then
  carries on), and is clean with `-load <abs prof_db>`. `summary -type` /
  `-inst` write no file when no sample landed in design code.
  `xprof_merge <raw_data>...` writes `prof_db_merge/` but then crashes in
  `free()`, so merging waits.
- **Next:** VCS UVM profiler (`-simprofile=uvm`, `uvmprofrpt`), then
  Verilator `--prof-exec` (with `--threads`, so it is the deferred threads
  mode). Questa `capstats` last. `--prof-pgo` is a build optimization, not
  a profile, and stays out.

## Decisions

Resolved 2026-10-12:

1. **Image-level only.** SimRun does not consume SimProfArgs; it follows
   `prof.json`. The extra xcm/mti rebuild on a `prof` change is accepted.
2. **No `threads` mode for now.** Thread profiling (vlt `--prof-exec`, vcs
   FGP diag, xcm `-profthread`) stays deferred; revisit as deep-profiler
   switches in phase 5.
3. **Phase 0 coarse stats are always on** (`-reportstats` / `-perfstat` /
   `-stats=perf,time`), provided a measurement confirms the overhead is
   negligible. If one isn't, that backend gates it on `prof != none`.
4. **Questa uses fprofile + visualizer**, not the classic profiler.
