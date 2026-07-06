# ==================================================================================================
#  Book Cricket Multiplayer — Server Engine (Tier3 cricket model)
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

from __future__ import annotations
import random
from typing import Dict, Any, Optional, List
from common_schema import SHOTS, LENGTHS, INTENTS, EXTRA_TYPES, WICKET_TYPES, clamp_int

def pitch_mods(pitch: str) -> Dict[str, float]:
    pitch = (pitch or "FLAT").upper()
    if pitch == "GREEN":
        return {"wicket": 1.15, "boundary": 0.90}
    if pitch == "DUSTY":
        return {"wicket": 1.05, "boundary": 0.95}
    if pitch == "TWO_PACED":
        return {"wicket": 1.10, "boundary": 0.92}
    return {"wicket": 1.00, "boundary": 1.00}

def dew_mods(dew: str) -> Dict[str, float]:
    dew = (dew or "LOW").upper()
    if dew == "OFF":
        return {"wicket": 1.00, "boundary": 1.00}
    if dew == "HIGH":
        return {"wicket": 0.88, "boundary": 1.08}
    return {"wicket": 0.94, "boundary": 1.04}

def shot_profile(shot: str) -> Dict[str, float]:
    shot = (shot or "DEFEND").upper()
    if shot == "DEFEND":
        return {"wicket": 0.85, "bat_max": 2, "six_boost": 0.10}
    if shot == "DRIVE":
        return {"wicket": 1.00, "bat_max": 4, "six_boost": 0.25}
    if shot == "CUT":
        return {"wicket": 1.03, "bat_max": 4, "six_boost": 0.20}
    if shot == "PULL":
        return {"wicket": 1.08, "bat_max": 6, "six_boost": 0.40}
    return {"wicket": 1.20, "bat_max": 6, "six_boost": 0.60}  # SLOG

def length_profile(length: str) -> Dict[str, float]:
    length = (length or "GOOD").upper()
    if length == "YORKER":
        return {"wicket": 1.10, "boundary": 0.80, "extra": 0.10}
    if length == "GOOD":
        return {"wicket": 1.00, "boundary": 0.95, "extra": 0.09}
    if length == "FULL":
        return {"wicket": 0.95, "boundary": 1.10, "extra": 0.11}
    return {"wicket": 0.92, "boundary": 1.12, "extra": 0.13}  # SHORT

def intent_profile(intent: str) -> Dict[str, float]:
    intent = (intent or "BN").upper()
    if intent == "BD":
        return {"wicket": 0.92, "boundary": 0.85, "extra": 0.92}
    if intent == "BA":
        return {"wicket": 1.10, "boundary": 1.08, "extra": 1.18}
    return {"wicket": 1.00, "boundary": 1.00, "extra": 1.00}

def choose_extra(p_extra: float) -> Optional[str]:
    if random.random() > p_extra:
        return None
    r = random.random()
    if r < 0.46:
        return "WD"
    if r < 0.82:
        return "NB"
    if r < 0.91:
        return "B"
    return "LB"

def bat_runs_distribution(max_bat: int, boundary_factor: float, six_boost: float) -> int:
    # calibrated light-weight distribution
    p0 = 0.10
    p1 = 0.32
    p2 = 0.22
    p3 = 0.08
    p4 = 0.18 * boundary_factor
    p6 = 0.10 * boundary_factor * (1.0 + six_boost)

    probs = {0: p0, 1: p1, 2: p2, 3: p3, 4: p4, 6: p6}
    allowed = [r for r in probs.keys() if r <= max_bat]
    total = sum(probs[r] for r in allowed)
    if total <= 1e-9:
        return 0

    x = random.random() * total
    acc = 0.0
    for r in allowed:
        acc += probs[r]
        if x <= acc:
            return r
    return allowed[-1]

def wicket_probability(base: float, mults: List[float]) -> float:
    p = base
    for m in mults:
        p *= m
    return min(max(p, 0.01), 0.60)
