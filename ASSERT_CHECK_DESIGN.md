# Simulator diagnostics in test verdicts — Design

Status (2026-10-28): implemented (`sim_diag.py`, `uvm_log_parser.py`,
`sim_check.py`, `sim_uvm_case.py`; `TestResult` fields in `flow.dv`).

## Problem

A simulation can fail and still be reported as a pass:

- **A clean UVM summary hides simulator diagnostics.** The UVM report server
  counts only `uvm_report_*` messages. A concurrent assertion failure, an HDL
  `$error`/`$fatal` or a simulator error is printed by the simulator itself,
  so a run can end with `UVM_ERROR : 0` after many assertion failures.
  `SimUVMCheck` returned pass as soon as it saw a clean summary.
- **The exit code is not enough.** VCS exits 0 after a default SVA failure.
  Verilator with `+verilator+error+limit+N` logs every `%Error: Assertion
  failed` and exits 0. Generic `SimCheck` used only the exit code.
- **A tail-only read cannot certify a run.** `parse_uvm_log` read the last
  64 KiB. A failure earlier in a long log was never seen.

## Behavior

Both Check tasks (and `SimUVMCase`) make one streaming pass over the complete
log and fail a case on any error/fatal-severity simulator diagnostic,
whatever the UVM summary or the exit code say. Warnings never fail a case.

| Evidence | Result |
| --- | --- |
| UVM: clean summary, exit 0, no simulator errors/fatals | pass |
| UVM: UVM error/fatal, `** TEST FAILED **`, or any simulator error/fatal | fail |
| UVM: everything clean but a nonzero exit | error |
| UVM, no summary: segfault / core dump / simulator tool error | error |
| UVM, no summary: a checker's `$fatal` (or fatal assertion) ended the run | fail |
| UVM, no summary: no `$finish` | timeout |
| UVM, no summary, finished: UVM or simulator errors | fail |
| UVM, no summary, finished, nothing else | error |
| Generic: exit 0 and no simulator errors/fatals | pass |
| Generic: nonzero exit or any simulator error/fatal | fail |
| Either: no simulation log | Check task fails (infrastructure) |

A failing case is data: the Check task returns status 0 with a non-passing
`TestResult` and logs the reason as info, not an Error marker (which would
drop a matrix cell from the suite's aggregation). `SimSuiteReport` keeps every
case and gates the suite.

`SimRunResult` is unchanged: `status` stays the raw process status and
`simLog` the log artifact. Diagnostics are recovered from the persisted log,
so an old run can be re-checked.

## Recognition (`sim_diag.py`)

One table of anchored header patterns, shared by the Check tasks
(`DiagScanner`) and the compile-log `LogParser` (which takes the Xcelium
envelope from it). Each recognized message becomes a `Diag`: severity
(error | fatal | warning), category (assertion | check | tool), code, file,
line, hierarchy, time (as printed, plus femtoseconds for comparison),
message and log line.

| Simulator | Header | Category |
| --- | --- | --- |
| VCS | `"f.sv", 31: top.u.A: started at T failed at T` (+ indented `Offending`) | assertion |
| VCS | `Error:` / `Fatal:` / `Warning: "f.sv", N: scope: at time T` + message lines | check (assertion when merged) |
| VCS | `Error-[CODE]` / `Warning-[CODE]` | tool |
| Xcelium | `<tool>: *E,<CODE>` / `*F,` / `*W,` with `(path,line)` or `(path,line\|col)` for xmsim, xmvlog, xmelab, xmvhdl, xrun (and nc*, irun) | ASRTST: assertion; ERRSEV/FATSEV/WARSEV: check; else tool |
| Verilator | `[time] %Error/%Fatal/%Warning[-CODE]: f.sv:N: ...` | `Assertion failed in`: assertion; else tool |
| Icarus | `ERROR:` / `FATAL:` / `WARNING: f.sv:N: msg` + `Time: … Scope: …` | check |
| Questa | `[# ]** Error/Fatal/Warning: msg` + `Time: … Scope: … File: … Line: …` | `Assertion error`: assertion; with `(code)`: tool; else check |

Rules:

- No bare `error`, `failed` or `fatal` substring matching; UVM report lines
  and zero-count summaries never match.
- Continuations are per format: VCS SVA takes indented lines; VCS severity
  reports and Xcelium take following message lines; Icarus and Questa only
  their `Time:` line; Verilator none. A blank line, another header, a UVM
  line, the UVM summary or the simulator's end-of-run lines end a record. At
  most 3 continuation lines; messages are clipped to 240 characters. A
  pending record is flushed at EOF.
- A VCS SVA failure and an immediately following `Error:`/`Fatal:` report
  with the same hierarchy and the same time (after unit normalization) are
  one event, keeping the assertion's location and the action's message.
  Different assertions at the same time, unrelated `$error`s at the same
  time, and repeated failures at different times are separate events.
- Verilator's `%Error: … Verilog $stop` after an error is that error's
  consequence and is not counted.
- Verilator and Icarus print an assertion's action and a plain `$error` the
  same way; the assertion/check split there is what the simulator says.
- Warning suppression (`SuppressWarnings`) applies only to warnings in the
  marker parser; the Check scan has no suppression.

## Results

`TestResult` keeps `errors`/`warnings`/`fatals` as the UVM tallies (from the
summary when there is one; individual `UVM_*` lines are counted only when
there is not) and adds, all defaulted so older results still load:

- `sim_errors`, `sim_fatals` — simulator diagnostics outside UVM.
- `assertion_failures` — how many of those are assertion failures (a subset).
- `diagnostics` — the first 10, as maps.

The counts are also in `stats` (summed by `SimSuiteReport` via
`sim_stats.STAT_KEYS`). The suite console line, `report.json`, `junit.xml`
and `ctrf.json` show a failing case's counts and its first diagnostic. The
counts are what the simulator printed; a simulator's own message limit can
hide more.

Memory is bounded: counts, at most 400 lines of the last UVM summary region
and 10 diagnostics, regardless of log size.

## Tests

- `tests/unit/test_sim_diag.py` — recognition, grouping and merging, against
  `tests/unit/data/diag/` (real Verilator 5.052 and Icarus logs;
  hand-written VCS, Xcelium and Questa logs in their documented formats).
- `tests/unit/test_uvm_log_parser.py` — verdict rules, including a failure
  before the last 64 KiB of a 5 MB log, clean summary + nonzero exit, and
  the Questa `# ` transcript prefix.
- `tests/unit/test_sim_check.py` — Check tasks and `SimSuiteReport`: a suite
  with one assertion-only failure and one pass keeps both, gates nonzero and
  explains the failure in every report; reports accept older TestResults.

## Not covered

- Expected-error tests: there is no way yet to declare an expected simulator
  error; such a test fails. A general expected-diagnostic API is a separate
  design. There is deliberately no blanket "ignore simulator errors" switch.
- OVL and other checker-library message formats: add with real fixtures.
- Live (during-run) diagnostic streaming.
- VCS, Xcelium and Questa fixtures are written from the documented formats,
  not captured from those simulators; confirm against real logs.
