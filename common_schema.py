# ==================================================================================================
#  Book Cricket Multiplayer — Common Schema & Helpers
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5050

SHOTS = ("DEFEND", "DRIVE", "CUT", "PULL", "SLOG")
LENGTHS = ("YORKER", "GOOD", "SHORT", "FULL")
INTENTS = ("BD", "BN", "BA")

EXTRA_TYPES = ("WD", "NB", "B", "LB")
WICKET_TYPES = ("CAUGHT", "BOWLED", "LBW", "RUNOUT", "STUMPED")

PHASES = ("LOBBY", "TOSS", "CHOOSE_BATBOWL", "PLAYING", "FINISHED")
TURNS = (None, "SELECT_BOWLER", "BAT", "BOWL")

def safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def overs_str(balls: int) -> str:
    return f"{balls//6}.{balls%6}"

def balls_to_overs_float(balls: int) -> float:
    return (balls // 6) + (balls % 6) / 6.0

def rr_required(target: int, score: int, balls_left: int) -> float:
    if balls_left <= 0:
        return 99.0
    need = target - score
    if need <= 0:
        return 0.0
    return (need / balls_left) * 6.0
