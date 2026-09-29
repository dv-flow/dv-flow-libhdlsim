import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


@cocotb.test()
async def inc(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.a.value = 41
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.y.value) == 42, f"y={dut.y.value}"
