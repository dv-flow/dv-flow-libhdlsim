# Simulator diagnostic fixtures

Small logs for `sim_diag` / `uvm_log_parser` / the Check tasks.

- `vlt_*.log`, `ivl_*.log`: real output of Verilator 5.052 and Icarus
  Verilog, from small test programs (an SVA with and without an action
  block, `$error`, `$warning`, `$fatal`).
- `vcs_*.log`, `xcm_*.log`, `mti_*.log`: hand-written in each simulator's
  documented runtime format. Names (`tb_top.dut.u_chk.REQ_KNOWN`,
  `checker.sv`) are invented.

Whitespace (tabs before VCS `Offending`, Icarus' aligned `Time:` lines) is
significant; keep it when editing.
