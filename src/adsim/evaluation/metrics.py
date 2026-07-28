"""Competition-style scoring (NeurIPS auto-bidding rules, doc §6.1/§12.3)."""
from __future__ import annotations


def competition_score(conversions: float, cpa: float, cpa_constraint: float, beta: float = 2.0) -> float:
    """score = conversions            if CPA <= target
             = conversions * (target/CPA)^beta  otherwise."""
    if conversions <= 0:
        return 0.0
    if cpa <= cpa_constraint:
        return conversions
    return conversions * (cpa_constraint / (cpa + 1e-10)) ** beta
