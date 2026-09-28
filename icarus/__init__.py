"""Icarus Engine -- one adaptive intraday system, four asset classes.

Public surface:
    >>> from icarus import IcarusEngine, AssetClass, backtest, synthetic_series
    >>> report = backtest(synthetic_series(2000), AssetClass.CRYPTO)
"""

from icarus.config import AssetClass, Profile, PROFILES, profile_for
from icarus.data import Bar, load_csv, synthetic_series

__version__ = "1.0.0"

__all__ = [
    "AssetClass", "Profile", "PROFILES", "profile_for",
    "Bar", "load_csv", "synthetic_series",
    "__version__",
]
