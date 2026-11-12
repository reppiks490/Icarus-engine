"""Collect Atlas's offline synthetic TestCases in the existing pytest CI."""
from research_allocation.test_cli import CLITests
from research_allocation.test_decision import ContractTests, JointTests, RobustTests, ValueTests
from research_allocation.test_journal import JournalTests
from research_allocation.test_planner import PlannerTests
from research_allocation.test_sequential import SequentialTests

__all__ = ["CLITests", "ContractTests", "JointTests", "RobustTests", "ValueTests",
           "JournalTests", "PlannerTests", "SequentialTests"]
