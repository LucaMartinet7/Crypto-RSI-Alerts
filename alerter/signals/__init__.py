"""
Signal detectors. Each detector watches one indicator and decides what counts
as an alert. See base.py for the shared contract, and rsi.py / macd.py for the
concrete ones.
"""

from .base import Alert, Detector, DigestSection
from .macd import MacdCrossDetector
from .rsi import RsiZoneDetector

__all__ = [
    "Alert", "Detector", "DigestSection",
    "RsiZoneDetector", "MacdCrossDetector",
]
