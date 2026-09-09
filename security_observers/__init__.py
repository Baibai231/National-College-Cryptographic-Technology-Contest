"""Passive security-capability observers used by the measurement engine."""

from security_observers.base import collect_security_observations
from security_observers.maturity import build_cpam_maturity
from security_observers.recovery import analyze_recovery_signals
from security_observers.scoring import attach_security_assessment, build_security_assessment

__all__ = [
    "attach_security_assessment",
    "analyze_recovery_signals",
    "build_cpam_maturity",
    "build_security_assessment",
    "collect_security_observations",
]
