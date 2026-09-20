import pytest

from icarus_engine.emulator import Emulator
from icarus_engine.pine.timeframe import Bar


def test_open_equity_charges_entry_commission_through_partial_exit():
    em = Emulator(initial_capital=1000, commission=2, contract_size=1)
    em.entry("L", 1, 2)
    em.process_bar(Bar(60, 100, 100, 100, 100, 1), 0)
    assert em.equity(100) == 996
    em.exit("partial", "L", qty=1, limit=101)
    em.process_bar(Bar(120, 100, 101, 100, 101, 1), 1)
    assert em.netprofit == -3
    assert em.equity(101) == 996
    em.close("L")
    em.process_bar(Bar(180, 101, 101, 101, 101, 1), 2)
    assert em.equity(101) == 994


@pytest.mark.parametrize("direction,entry,stop,close", [(1, 98, 99, 96), (-1, 102, 101, 104)])
def test_newly_activated_breached_stop_does_not_revisit_passed_price(direction, entry, stop, close):
    em = Emulator(initial_capital=1000, commission=0, contract_size=1)
    em.entry("E", direction, 1, limit=entry)
    em.exit("S", "E", stop=stop)
    em.process_bar(Bar(60, 100, 105, 95, close, 1), 0)
    assert len(em.closed) == 1
    assert em.closed[0].exit_price == entry
    assert em.closed[0].profit == 0
