# Warning Suppression Implementation Plan

## Problem Statement

Several tools in this project parse log files for errors and warnings, then raise them as
task markers. Users need the ability to suppress specific warnings by code (e.g., VCS
`TFIPC`) so those warnings are still produced by the tool but are **not** raised as markers.
Suppression should be expressible both directly on the task (`with:` params) and via a
connected dataflow dataset.

---

## Background: How Warnings Flow Today

1. **Log parsers** (`log_parser.py`, `vcs_log_parser.py`, `mti_log_parser.py`, etc.)
   - `LogParser` in `log_parser.py` is the base. It handles four warning formats and
     emits `TaskMarker` objects via a `notify` callback.
   - Subclasses (`VcsLogParser`, `MtiLogParser`, `XsmLogParser`, `VltLogParser`) intercept
     build-progress signals and delegate the rest to `super().line()`.

2. **Builder/runner classes** create parser instances and wire up `notify`:
   - `VlSimImageBuilder` / `VlSimLibBuilder` — used for compile/elaborate phases
   - `VLSimRunner` — used for simulation runs (currently no log filtering done)

3. **Warning formats parsed and their codes:**

   | Format | Example | Code location |
   |--------|---------|--------------|
   | VCS/XSim multi-line | `Warning-[TFIPC] Too few port connections` | Between `[` and `]` in the header line |
   | Verilator single-line | `%Warning-PINCONNECTS: path:line: msg` | Between `-` and `:` at start |
   | Questa style-1 | `** Warning: (vlog-2623) path(line): msg` | Between `(` and `)` after first `:` |
   | Questa style-2 | `** Warning (suppressible): path(line): (vlog-2623) msg` | Between `(` and `)` after second `:` |
   | Xilinx/XSim single-line | `WARNING: msg [code]` | Between `[` and `]` at end of line |

4. **Current marker message text** for VCS-style warnings strips the `[CODE]` header and
   only keeps the text after `]`. The code is **not** currently included in the marker msg,
   making it hard to identify which code to suppress.

---

## Proposed Changes

### 1. `log_parser.py` — Core warning code extraction & suppression

**New fields on `LogParser`:**
```python
_code  : str       = dc.field(default="")           # extracted warning/error code
suppress : List[str] = dc.field(default_factory=list) # codes to suppress
```

**Code extraction in `_line()`:**

For each warning format, extract the code into `self._code` in addition to the existing
path/message parsing:

- **VCS multi-line** (`Warning-[TFIPC] …`):
  ```python
  ob = l.find("[")
  cb = l.find("]", ob)
  if ob != -1 and cb != -1:
      self._code = l[ob+1:cb]
  ```
  (done at the start of the `Warning-` branch, before storing `self._tmp`)

- **Verilator** (`%Warning-CODE: …`):
  ```python
  dash_idx = l.find("-")
  c1_idx   = l.find(":")
  if 0 < dash_idx < c1_idx:
      self._code = l[dash_idx+1:c1_idx]
  ```

- **Questa style-1** (`** Warning: (vlog-XXXX) path(line): msg`):
  ```python
  if l[c1_idx+2] == '(':
      p2_idx = l.find(")", c1_idx+2)
      self._code = l[c1_idx+3:p2_idx]   # e.g. "vlog-2623"
  ```

- **Questa style-2** (`** Warning (suppressible): path(line): (vlog-XXXX) msg`):
  ```python
  c3_idx = l.find(')', c2_idx+1)
  code_open  = l.find('(', c2_idx+1)
  code_close = l.find(')', code_open+1) if code_open != -1 else -1
  if code_open != -1 and code_close != -1:
      self._code = l[code_open+1:code_close]
  self._message = l[c3_idx+1:].strip()
  ```

- **XSim/Xilinx** (`WARNING: msg [code]`):
  ```python
  last_open = l.rfind('[')
  if last_open != -1:
      self._code = l[last_open+1:].rstrip().rstrip(']')
  ```

**`emit_marker()` changes:**

1. **Prepend code to message** so it is always visible in the marker:
   ```python
   msg = ("[%s] %s" % (self._code, self._message)).strip() if self._code else self._message
   ```

2. **Suppress check before calling notify:**
   ```python
   if self._code and self._code in self.suppress:
       self._code = ""
       self._kind = None
       self._message = ""
       self._path = ""
       return   # do not emit marker
   ```

3. Reset `self._code = ""` after emit (like `_kind`, `_message`, `_path`).

---

### 2. `flow.dv` (hdlsim base package) — New parameter & dataset type

**New parameter on `SimImage` and `SimLib` tasks:**
```yaml
suppress_warnings:
  doc: List of warning codes to suppress from becoming markers (e.g., [TFIPC, vlog-2623])
  type: list
```

Also add it to the `consumes:` list of `SimImage` and `SimLib`:
```yaml
- type: hdlsim.SuppressWarnings
```

**New dataset type `SuppressWarnings`:**
```yaml
- name: SuppressWarnings
  doc: |
    A dataset that carries a list of warning codes to suppress.
    Connect to SimImage or SimLib via needs/dataflow to suppress
    specific simulator warnings project-wide.
  with:
    codes:
      doc: Warning codes to suppress (e.g., TFIPC, vlog-2623, PINCONNECTS)
      type: list
```

---

### 3. `vl_sim_image_builder.py` — Thread suppression into parsers

In `VlSimImageBuilder.run()`, after collecting `data` from params, assemble the suppress list:

```python
suppress = list(merge_tokenize(input.params.suppress_warnings))
for fs in input.inputs:
    if fs.type == "hdlsim.SuppressWarnings":
        suppress.extend(fs.codes)
```

Store it on `self`:
```python
self.suppress = suppress
```

Change `parseLog()` to accept (or use) `self.suppress`:
```python
def parseLog(self, log):
    parser = LogParser(
        notify=lambda m: self.markers.append(m),
        suppress=self.suppress)
    with open(log, "r") as fp:
        for line in fp.readlines():
            parser.line(line)
```

The `build()` method in each simulator-specific subclass creates inline log parser
instances (e.g., `VcsLogParser(notify=..., notify_parsing=...)`). These need `suppress`
passed in. **Two options:**

- **(Preferred)** Add `suppress` as a constructor param to `LogParser` (already done in
  step 1) and each subclass parser. Then each subclass `build()` receives `suppress` via
  `self.suppress` set in `run()`.

- Alternatively, pass suppress as a `build()` argument — but that would require changing
  signatures more broadly.

---

### 4. `vl_sim_lib_builder.py` — Thread suppression into parsers

Same pattern as `VlSimImageBuilder`:
- Assemble suppress from `input.params.suppress_warnings` and `hdlsim.SuppressWarnings`
  datasets in `run()`
- Pass to `LogParser` in `parseLog()`
- Pass to `VcsLogParser` / etc. in `build()` via `self.suppress`

---

### 5. Simulator-specific `build()` methods — Pass suppress to inline parsers

For each simulator that creates a log parser inline (passing it as `logfilter`):

- **`vcs_sim_image.py`** (two places — `vlogan` and the `vcs` parseLog call):
  ```python
  VcsLogParser(
      notify=lambda m: self.ctxt.add_marker(m),
      notify_parsing=file_parsed,
      suppress=self.suppress).line
  ```
  And `self.parseLog(os.path.join(input.rundir, 'vlogan.log'))` uses the updated
  `parseLog()` that pulls from `self.suppress`.

- **`vcs_sim_lib.py`**:
  ```python
  VcsLogParser(
      notify=lambda m: self.ctxt.add_marker(m),
      notify_parsing=notify_parsing,
      suppress=self.suppress).line
  ```

- **`mti_sim_image.py`**:
  ```python
  MtiLogParser(
      notify=lambda m: self.ctxt.add_marker(m),
      notify_comp=notify_comp,
      suppress=self.suppress).line
  ```

- **`xsm_sim_image.py`**:
  ```python
  XsmLogParser(
      notify=lambda m: self.ctxt.add_marker(m),
      notify_analyze=file_analyzed,
      suppress=self.suppress).line
  ```

- **`vlt_sim_image.py`** (if it uses VltLogParser inline — check during implementation):
  Similar pattern.

---

### 6. `sim_args.py` — No changes needed

`SimArgs` is a generic args dataset, not related to warning suppression.

---

### 7. Simulator-specific `flow.dv` files — No changes needed

Because `hdlsim.vcs.SimImage` uses `uses: hdlsim.SimImage`, it inherits all params
including the new `suppress_warnings`. Same for other simulators. No changes needed to
`vcs_flow.dv`, `mti_flow.dv`, etc.

---

## Files to Modify

| File | Change |
|------|--------|
| `src/dv_flow/libhdlsim/log_parser.py` | Add `_code`, `suppress` fields; extract code in all 5 format branches; modify `emit_marker()` |
| `src/dv_flow/libhdlsim/flow.dv` | Add `suppress_warnings` param to `SimImage`/`SimLib`; add `SuppressWarnings` type; update `consumes:` |
| `src/dv_flow/libhdlsim/vl_sim_image_builder.py` | Assemble suppress list in `run()`; update `parseLog()` to pass it |
| `src/dv_flow/libhdlsim/vl_sim_lib_builder.py` | Same as above |
| `src/dv_flow/libhdlsim/vcs_sim_image.py` | Pass `suppress=self.suppress` to `VcsLogParser` |
| `src/dv_flow/libhdlsim/vcs_sim_lib.py` | Pass `suppress=self.suppress` to `VcsLogParser` |
| `src/dv_flow/libhdlsim/mti_sim_image.py` | Pass `suppress=self.suppress` to `MtiLogParser` |
| `src/dv_flow/libhdlsim/xsm_sim_image.py` | Pass `suppress=self.suppress` to `XsmLogParser` |
| `src/dv_flow/libhdlsim/vlt_sim_image.py` | Pass `suppress=self.suppress` to `VltLogParser` (if applicable) |

---

## Usage Example (after implementation)

### Direct on task (suppress TFIPC for VCS):
```yaml
- name: build
  uses: hdlsim.vcs.SimImage
  needs: [rtl, tb]
  with:
    top: [tb_top]
    suppress_warnings: [TFIPC, MAXX]
```

### Via shared suppression dataset (reusable across tasks):
```yaml
- name: common_suppressions
  uses: hdlsim.SuppressWarnings
  with:
    codes: [TFIPC, MAXX, vlog-2623]

- name: build
  uses: hdlsim.vcs.SimImage
  needs: [rtl, tb, common_suppressions]
  with:
    top: [tb_top]
```

### Resulting marker text (when NOT suppressed):
Marker message will be: `[TFIPC] Too few instance port connections`
(so users can easily identify the code to add to the suppress list)

---

## Notes / Considerations

- **Errors are never suppressed** — the suppress list only applies to warnings. Even if an
  error code appears in `suppress`, errors should still be emitted. Enforce this in
  `emit_marker()` by only applying the suppress check when `sev == SeverityE.Warning`.

- **Code comparison is case-sensitive** by default, matching the simulator's own convention.

- **`_code` reset** must happen in `emit_marker()` after use, just like `_kind`,
  `_message`, and `_path` are currently reset.

- **Backward compatibility** — `suppress` defaults to `[]`, so existing callers are
  unaffected. The code prefix in messages (`[CODE] msg`) is a visible change to marker
  text; existing tests may need updating if they match exact message strings.

- **SimRun warning suppression** is out of scope for this plan. Simulation runtime messages
  are usually handled differently (UVM severity, plusargs). Can be added later by extending
  `VLSimRunner` similarly.
