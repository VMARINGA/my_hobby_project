# ==================================================================================================
#  Book Cricket Multiplayer — Server State Machine (authoritative)
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

from __future__ import annotations
import random
from typing import Dict, Any, Optional, List
from common_schema import (
    SHOTS, LENGTHS, INTENTS, WICKET_TYPES,
    overs_str, clamp_int, safe_int
)
from server_engine import (
    pitch_mods, dew_mods, shot_profile, length_profile, intent_profile,
    choose_extra, bat_runs_distribution, wicket_probability
)


# ---------------- Tier3++ realism helpers ----------------

BOWLER_TYPES = ("PACE", "SWING", "SEAM", "SPIN", "MYSTERY")

BOWLER_TYPE_MULTS = {
    "PACE":    {"wicket": 1.05, "boundary": 1.02, "extra": 1.05, "fatigue_inc": 0.030},
    "SWING":   {"wicket": 1.08, "boundary": 0.98, "extra": 1.08, "fatigue_inc": 0.032},
    "SEAM":    {"wicket": 1.06, "boundary": 0.97, "extra": 1.04, "fatigue_inc": 0.031},
    "SPIN":    {"wicket": 1.03, "boundary": 0.95, "extra": 0.95, "fatigue_inc": 0.022},
    "MYSTERY": {"wicket": 1.07, "boundary": 0.96, "extra": 0.98, "fatigue_inc": 0.024},
}

def match_phase(overs_total: int, balls_bowled: int) -> str:
    """Return phase label: PP / MID / DEATH."""
    o = clamp_int(int(overs_total), 1, 20)
    # Scale PP/death for short games so it still makes sense
    pp_overs = max(1, min(6, int((o * 0.30) + 0.999)))          # ceil(0.30*overs) capped at 6
    death_overs = max(1, int((o * 0.20) + 0.999))               # ceil(0.20*overs)
    over_no = (int(balls_bowled) // 6) + 1  # 1-based current over
    if over_no <= pp_overs:
        return "PP"
    if over_no > (o - death_overs):
        return "DEATH"
    return "MID"

def phase_mults(phase: str) -> Dict[str, float]:
    # Higher boundary rate in PP and death; wicket slightly up in death
    if phase == "PP":
        return {"boundary": 1.08, "wicket": 0.98, "extra": 1.02}
    if phase == "DEATH":
        return {"boundary": 1.18, "wicket": 1.06, "extra": 1.08}
    return {"boundary": 1.00, "wicket": 1.00, "extra": 1.00}

def pitch_deterioration(pitch: str, progress: float) -> Dict[str, float]:
    """progress: 0.0 start of innings -> 1.0 end of innings."""
    p = (pitch or "FLAT").upper()
    t = max(0.0, min(1.0, float(progress)))
    if p == "GREEN":
        # green top early, flattens later
        return {"wicket": 1.00 - 0.12 * t, "boundary": 1.00 + 0.02 * t}
    if p == "DUSTY":
        # gets slower & turns more
        return {"wicket": 1.00 + 0.15 * t, "boundary": 1.00 - 0.08 * t}
    if p == "TWO_PACED":
        # becomes more unpredictable
        return {"wicket": 1.00 + 0.10 * t, "boundary": 1.00 - 0.05 * t}
    # FLAT
    return {"wicket": 1.00 + 0.05 * t, "boundary": 1.00 - 0.03 * t}

def batter_skill_factors(skill: int, shot: str) -> Dict[str, float]:
    """skill: 1..100"""
    s = clamp_int(int(skill), 1, 100)
    # better batters: fewer wickets, more boundaries
    wicket = 1.0 - (s - 50) / 250.0    # 90 -> ~0.84
    boundary = 1.0 + (s - 50) / 220.0  # 90 -> ~1.18
    extra_run = 1.0 + (s - 50) / 500.0
    # low-skill slog is very risky
    if (shot or "").upper() == "SLOG" and s < 55:
        wicket *= 1.25
        boundary *= 0.90
    return {"wicket": max(0.70, min(1.35, wicket)),
            "boundary": max(0.80, min(1.35, boundary)),
            "extra_run": max(0.90, min(1.15, extra_run))}

def make_batter_skills() -> Dict[int, int]:
    """Create 11 batter skills (1..100). Openers stronger, tail weaker."""
    skills = {}
    for no in range(1, 12):
        if no <= 2:
            base = random.randint(70, 88)
        elif no <= 5:
            base = random.randint(62, 82)
        elif no <= 8:
            base = random.randint(50, 72)
        else:
            base = random.randint(35, 60)
        skills[no] = base
    return skills

def make_bowler_profiles(num_bowlers: int) -> Dict[str, Dict[str, Any]]:
    """Return profile per bowler tag: type, skill, stamina."""
    nb = clamp_int(int(num_bowlers), 1, 5)
    # choose a balanced mix
    if nb == 1:
        types = ["PACE"]
    elif nb == 2:
        types = ["PACE", "SPIN"]
    else:
        types = ["PACE", "SWING", "SEAM", "SPIN", "MYSTERY"][:nb]
    profiles = {}
    for i, t in enumerate(types, start=1):
        tag = f"B{i}"
        profiles[tag] = {
            "type": t,
            "skill": random.randint(55, 85),       # affects wicket/boundary/extras
            "stamina": random.randint(65, 95) / 100.0,  # affects fatigue growth
        }
    return profiles


class BookCricketState:
    """
    Authoritative match state. No socket code here.
    """
    def __init__(self):
        self.names = ["Player 1", "Player 2"]
        self.ready = [False, False]
        self.connected = [False, False]
        self.reset_match(hard=True)

    def reset_match(self, hard: bool):
        self.phase = "LOBBY"  # LOBBY / TOSS / CHOOSE_BATBOWL / PLAYING / FINISHED
        self.pitch = "FLAT"
        self.dew = "LOW"

        # Match config (auto-derived realism rules)
        # Overs: 1–20
        #  - 1 over  => 1 bowler, 2 wickets
        #  - 2–4 overs => 2 bowlers, 4 wickets
        #  - >=5 overs => 5 bowlers, 10 wickets
        self.overs = 1
        self.num_bowlers = 1
        self.wickets_total = 2
        self.balls_total = self.overs * 6

        # Re-generate Tier3++ profiles now that overs->bowler slots are derived
        self.bowler_profiles = {0: make_bowler_profiles(self.num_bowlers), 1: make_bowler_profiles(self.num_bowlers)}
        self.batter_skill = {0: make_batter_skills(), 1: make_batter_skills()}
        self.partnership_runs = {0: 0, 1: 0}
        self.partnership_balls = {0: 0, 1: 0}

        self.innings = 1
        self.batting_idx = 0
        self.bowling_idx = 1
        self.turn = None  # SELECT_BOWLER / BAT / BOWL

        # Toss control: server flips, designated caller calls
        self.toss_caller = 1  # default: Player 2 calls (can be changed later)
        self.toss_call = None
        self.toss_result = None
        self.toss_winner = None

        self.target: Optional[int] = None  # innings2: runs to win

        self.scores = [0, 0]
        self.wkts = [0, 0]
        self.balls = [0, 0]  # legal balls for each team (their innings)

        # batters
        self.current_batter_no = {0: 1, 1: 1}
        self.non_striker_no = {0: 2, 1: 2}
        self.next_batter_no = {0: 3, 1: 3}
        self.batter_balls_faced = {0: {}, 1: {}}
        self.batter_runs = {0: {}, 1: {}}

        # Tier3++ skills
        self.batter_skill = {0: make_batter_skills(), 1: make_batter_skills()}

        # partnership (runs/balls on current stand) for each batting team
        self.partnership_runs = {0: 0, 1: 0}
        self.partnership_balls = {0: 0, 1: 0}


        # free hit next legal ball only
        self.free_hit = {0: False, 1: False}

        # over/bowler
        self.current_bowler_tag = {0: "B1", 1: "B1"}  # per team when bowling
        self.last_over_bowler_tag = {0: None, 1: None}
        self.suggested_bowler_tag = {0: "B1", 1: "B1"}
        self.legal_in_over = {0: 0, 1: 0}

        # bowler fatigue (0.0 fresh .. 1.0 exhausted) tracked per bowling side
        self.bowler_fatigue = {0: {f"B{i}": 0.0 for i in range(1, 6)}, 1: {f"B{i}": 0.0 for i in range(1, 6)}}
        self.bowler_legal_balls = {0: {f"B{i}": 0 for i in range(1, 6)}, 1: {f"B{i}": 0 for i in range(1, 6)}}

        # Tier3++ bowler profiles (type/skill/stamina) - set again in start_match() after overs derived
        self.bowler_profiles = {0: make_bowler_profiles(self.num_bowlers), 1: make_bowler_profiles(self.num_bowlers)}


        self.pending_bat = None
        self.pending_bowl = None

        self.history: List[Dict[str, Any]] = []
        self.last_event = ""
        self.result: Optional[Dict[str, Any]] = None

        if hard:
            self.ready = [False, False]

    # ---------------- config rules ----------------

    @staticmethod
    def derive_config_from_overs(overs: int) -> Dict[str, int]:
        """Derive wickets + bowler slots from overs per your realism rules."""
        o = clamp_int(overs, 1, 20)
        if o <= 1:
            return {"overs": o, "wickets_total": 2, "num_bowlers": 1}
        if o <= 4:
            return {"overs": o, "wickets_total": 4, "num_bowlers": 2}
        return {"overs": o, "wickets_total": 10, "num_bowlers": 5}

    def allowed_bowler_tags(self) -> List[str]:
        return [f"B{i}" for i in range(1, self.num_bowlers + 1)]

    # ---------------- result helpers ----------------

    
    def compute_suggested_bowler(self) -> str:
        """Deterministic rotation suggestion: over1->B1, over2->B2, over3->B3 ... cycling."""
        try:
            over_no = (self.balls[self.batting_idx] // 6) + 1  # next over to be bowled
            return f"B{((over_no - 1) % max(1, self.num_bowlers)) + 1}"
        except Exception:
            return "B1"

    def _match_summary(self) -> str:
        p0, p1 = self.names
        return f"{p0}: {self.scores[0]}/{self.wkts[0]} ({overs_str(self.balls[0])}) | {p1}: {self.scores[1]}/{self.wkts[1]} ({overs_str(self.balls[1])})"

    def _compute_result(self) -> Dict[str, Any]:
        p0, p1 = self.names
        s0, s1 = self.scores

        if self.target is None:
            if s0 > s1:
                return {"winner_idx": 0, "message": f"{p0} won ✅", "summary": self._match_summary()}
            if s1 > s0:
                return {"winner_idx": 1, "message": f"{p1} won ✅", "summary": self._match_summary()}
            return {"winner_idx": None, "message": "Match tied 🤝", "summary": self._match_summary()}

        target = int(self.target)

        # Infer setter/chaser robustly
        setter = 0 if s0 == (target - 1) else (1 if s1 == (target - 1) else None)
        if setter is None:
            setter = 0 if s0 >= s1 else 1
        chaser = 1 - setter

        chaser_score = self.scores[chaser]
        chaser_wk = self.wkts[chaser]

        if chaser_score >= target:
            wk_left = self.wickets_total - chaser_wk
            return {
                "winner_idx": chaser,
                "message": f"{self.names[chaser]} won by {wk_left} wicket(s). ✅",
                "target": target,
                "summary": self._match_summary(),
                "setter_idx": setter,
                "chaser_idx": chaser,
            }

        if chaser_score == (target - 1):
            return {"winner_idx": None, "message": "Match tied 🤝", "target": target, "summary": self._match_summary()}

        runs_margin = (target - 1) - chaser_score
        return {
            "winner_idx": setter,
            "message": f"{self.names[setter]} won by {runs_margin} run(s). ✅",
            "target": target,
            "summary": self._match_summary(),
            "setter_idx": setter,
            "chaser_idx": chaser,
        }

    def finish_match(self, reason: str):
        self.phase = "FINISHED"
        self.turn = None
        self.result = self._compute_result()
        self.last_event = f"{reason} | RESULT: {self.result.get('message','')} | {self.result.get('summary','')}".strip()

    # ---------------- state snapshot ----------------

    def get_state(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "pitch": self.pitch,
            "dew": self.dew,
            "overs": self.overs,
            "num_bowlers": self.num_bowlers,
            "wickets_total": self.wickets_total,
            "balls_total": self.balls_total,
            "allowed_bowlers": self.allowed_bowler_tags(),
            "bowler_fatigue": self.bowler_fatigue,
"bowler_profiles": self.bowler_profiles,
            "batter_skill": self.batter_skill,
            "partnership": {
                "runs": self.partnership_runs.get(self.batting_idx, 0),
                "balls": self.partnership_balls.get(self.batting_idx, 0),
            },
            "batters": {
                "striker_no": self.current_batter_no.get(self.batting_idx, 1),
                "non_striker_no": self.non_striker_no.get(self.batting_idx, 2),
                "striker_runs": self.batter_runs.get(self.batting_idx, {}).get(self.current_batter_no.get(self.batting_idx, 1), 0),
                "striker_balls": self.batter_balls_faced.get(self.batting_idx, {}).get(self.current_batter_no.get(self.batting_idx, 1), 0),
                "non_striker_runs": self.batter_runs.get(self.batting_idx, {}).get(self.non_striker_no.get(self.batting_idx, 2), 0),
                "non_striker_balls": self.batter_balls_faced.get(self.batting_idx, {}).get(self.non_striker_no.get(self.batting_idx, 2), 0),
            },
            "phase_tag": match_phase(self.overs, self.balls[self.batting_idx]),
            "suggested_bowler_tag": self.suggested_bowler_tag,

            "players": self.names,
            "ready": self.ready,
            "connected": self.connected,

            "innings": self.innings,
            "batting_idx": self.batting_idx,
            "bowling_idx": self.bowling_idx,
            "turn": self.turn,

            "toss_caller": self.toss_caller,
            "toss_call": self.toss_call,
            "toss_result": self.toss_result,
            "toss_winner": self.toss_winner,

            "scores": self.scores,
            "wkts": self.wkts,
            "balls": self.balls,
            "overs_str": [overs_str(self.balls[0]), overs_str(self.balls[1])],

            "target": self.target,
            "free_hit": self.free_hit,

            "current_batter_no": self.current_batter_no,
            "non_striker_no": self.non_striker_no,
            "next_batter_no": self.next_batter_no,
            "batter_balls_faced": self.batter_balls_faced,
            "batter_runs": self.batter_runs,

            "current_bowler_tag": self.current_bowler_tag,
            "last_event": self.last_event,
            "history": self.history[-800:],

            "result": self.result,
        }

    # ---------------- match flow ----------------

    def start_match(self, overs: int, wickets: int, pitch: str, dew: str):
        cfg = self.derive_config_from_overs(int(overs))
        self.overs = cfg['overs']
        self.num_bowlers = cfg['num_bowlers']
        # Ignore client-provided wickets; server enforces realism rule.
        self.wickets_total = cfg['wickets_total']
        self.balls_total = self.overs * 6
        self.pitch = (pitch or "FLAT").upper()
        self.dew = (dew or "LOW").upper()

        self.phase = "TOSS"
        self.turn = None
        self.toss_call = None
        self.toss_result = None
        self.toss_winner = None
        self.result = None
        self.last_event = "Match created. TOSS: Server flips; designated caller calls Heads/Tails."
        # keep toss_caller as configured

    def do_toss_call(self, caller_slot: int, call: str) -> Optional[str]:
        if self.phase != "TOSS":
            return "Not in TOSS phase."
        if caller_slot != self.toss_caller:
            return f"Only {self.names[self.toss_caller]} can call the toss."

        call = "H" if call == "H" else "T"
        self.toss_call = call
        self.toss_result = random.choice(["H", "T"])

        caller_wins = (self.toss_call == self.toss_result)
        self.toss_winner = caller_slot if caller_wins else 1 - caller_slot

        call_txt = "Heads" if self.toss_call == "H" else "Tails"
        res_txt = "Heads" if self.toss_result == "H" else "Tails"
        win_txt = self.names[self.toss_winner]

        self.last_event = f"TOSS: {self.names[self.toss_caller]} called {call_txt} | Server flip={res_txt} | Winner={win_txt}. Winner chooses BAT/BOWL."
        self.phase = "CHOOSE_BATBOWL"
        return None

    def do_toss_choice(self, slot: int, choice: str) -> Optional[str]:
        if self.phase != "CHOOSE_BATBOWL":
            return "Not in CHOOSE BAT/BOWL phase."
        if self.toss_winner is None:
            return "Toss not completed."
        if slot != self.toss_winner:
            return "Only toss winner can choose BAT/BOWL."

        choice = (choice or "BAT").upper()
        if choice not in ("BAT", "BOWL"):
            return "Invalid choice."

        if choice == "BAT":
            self.batting_idx = slot
        else:
            self.batting_idx = 1 - slot
        self.bowling_idx = 1 - self.batting_idx

        self.innings = 1
        self.turn = "SELECT_BOWLER"
        self.phase = "PLAYING"
        # set default/suggested bowler for over 1
        sug = self.compute_suggested_bowler()
        self.suggested_bowler_tag[self.bowling_idx] = sug
        self.current_bowler_tag[self.bowling_idx] = sug
        self.last_event = f"{self.names[self.batting_idx]} will BAT first. Bowling side must SELECT_BOWLER ({', '.join(self.allowed_bowler_tags())}). Suggested: {sug}"
        return None

    def new_game(self) -> None:
        pitch, dew, overs, wk, toss_caller = self.pitch, self.dew, self.overs, self.wickets_total, self.toss_caller
        self.reset_match(hard=False)
        self.pitch, self.dew, self.overs, self.wickets_total = pitch, dew, overs, wk
        self.balls_total = self.overs * 6
        self.toss_caller = toss_caller
        self.phase = "TOSS"
        self.last_event = "NEW GAME: TOSS started. Server flips; designated caller calls Heads/Tails."

    def select_bowler(self, slot: int, tag: str) -> Optional[str]:
        if self.phase != "PLAYING" or self.turn != "SELECT_BOWLER":
            return "Not time to select bowler."
        if slot != self.bowling_idx:
            return "Only bowling side can select bowler."

        tag = (tag or '').strip().upper()
        allowed = self.allowed_bowler_tags()
        if tag not in allowed:
            return f"Invalid bowler. Allowed: {', '.join(allowed)}"
        last = self.last_over_bowler_tag.get(slot)
        if self.num_bowlers > 1 and last == tag:
            return f"{tag} cannot bowl consecutive overs. Select a different bowler."
        self.current_bowler_tag[slot] = tag
        self.last_event = f"{self.names[slot]} selected {tag} to bowl this over."
        self.turn = "BAT"
        self.pending_bat = None
        self.pending_bowl = None
        return None

    def action_bat(self, slot: int, shot: str) -> Optional[str]:
        if self.phase != "PLAYING" or self.turn != "BAT":
            return "Not BAT turn."
        if slot != self.batting_idx:
            return "Only batting side can bat now."

        shot = (shot or "DEFEND").upper()
        if shot not in SHOTS:
            return "Invalid shot."

        self.pending_bat = {"shot": shot}
        self.last_event = f"{self.names[slot]} chose shot {shot}. Waiting for bowler..."
        self.turn = "BOWL"
        return None

    def action_bowl(self, slot: int, intent: str, length: str) -> Optional[str]:
        if self.phase != "PLAYING" or self.turn != "BOWL":
            return "Not BOWL turn."
        if slot != self.bowling_idx:
            return "Only bowling side can bowl now."
        if not self.pending_bat:
            return "No bat action yet."

        intent = (intent or "BN").upper()
        length = (length or "GOOD").upper()
        if intent not in INTENTS:
            return "Invalid intent."
        if length not in LENGTHS:
            return "Invalid length."

        self.pending_bowl = {"intent": intent, "length": length}
        self.resolve_ball()
        return None

    # -------- strike rotation helpers --------

    def swap_strike(self, team_idx: int):
        self.current_batter_no[team_idx], self.non_striker_no[team_idx] = (
            self.non_striker_no[team_idx],
            self.current_batter_no[team_idx],
        )

    def ensure_batter_stats(self, team_idx: int, batter_no: int):
        if batter_no not in self.batter_balls_faced[team_idx]:
            self.batter_balls_faced[team_idx][batter_no] = 0
        if batter_no not in self.batter_runs[team_idx]:
            self.batter_runs[team_idx][batter_no] = 0

    def new_batter_in(self, team_idx: int):
        nb = self.next_batter_no[team_idx]
        self.next_batter_no[team_idx] = nb + 1
        self.current_batter_no[team_idx] = nb
        self.ensure_batter_stats(team_idx, nb)

    # -------- ball resolution --------

    def resolve_ball(self):
        bat_team = self.batting_idx
        bowl_team = self.bowling_idx

        shot = self.pending_bat["shot"]
        intent = self.pending_bowl["intent"]
        length = self.pending_bowl["length"]

        pm = pitch_mods(self.pitch)
        dm = dew_mods(self.dew)
        sp = shot_profile(shot)
        lp = length_profile(length)
        ip = intent_profile(intent)

        # Tier3++ context: phase + pitch deterioration
        progress = (self.balls[bat_team] / max(1.0, float(self.balls_total)))
        phase = match_phase(self.overs, self.balls[bat_team])
        phm = phase_mults(phase)
        pdm = pitch_deterioration(self.pitch, progress)

        # Tier3++ bowler profile
        bowler_tag = self.current_bowler_tag[bowl_team]
        bp = self.bowler_profiles.get(bowl_team, {}).get(bowler_tag, {})
        btype = (bp.get('type') or 'PACE').upper()
        bskill = clamp_int(int(bp.get('skill', 70)), 1, 100)
        bstamina = float(bp.get('stamina', 0.8))
        bt = BOWLER_TYPE_MULTS.get(btype, BOWLER_TYPE_MULTS['PACE'])


        # current bowler fatigue impacts extras, boundaries and wicket-taking ability
        fatigue = float(self.bowler_fatigue.get(bowl_team, {}).get(bowler_tag, 0.0))
        fatigue = max(0.0, min(1.0, fatigue))

        # Tier3++: bowler skill reduces leakiness; type influences pattern
        bskill_wicket = 1.0 + (bskill - 70) / 260.0
        bskill_boundary = 1.0 - (bskill - 70) / 320.0
        bskill_extra = 1.0 - (bskill - 70) / 420.0

        fat_boundary = (1.0 + 0.45 * fatigue)   # tired bowler leaks boundaries
        fat_wicket = (1.0 - 0.25 * fatigue)     # tired bowler takes fewer wickets
        fat_extra = (1.0 + 0.60 * fatigue)      # tired bowler bowls more wides/noballs

        # Base extra probability scaled by length/intent + fatigue + type + phase + skill
        base_extra = 0.10
        p_extra_raw = (base_extra
                       * lp["extra"] * ip["extra"]
                       * fat_extra
                       * bt["extra"] * phm["extra"]
                       * max(0.70, bskill_extra))
        p_extra = max(0.01, min(0.35, p_extra_raw))
        extra_type = choose_extra(p_extra)
        extra_type = choose_extra(p_extra)

        kind = "LEGAL"
        runs_extra = 0
        runs_bat = 0
        wicket = False
        wicket_type = ""
        free_hit_after = False

        striker_no = self.current_batter_no[bat_team]
        non_striker_no = self.non_striker_no[bat_team]
        self.ensure_batter_stats(bat_team, striker_no)
        self.ensure_batter_stats(bat_team, non_striker_no)
        # Tier3++: batter skill (affects wicket risk + boundary rate)
        striker_skill = clamp_int(int(self.batter_skill.get(bat_team, {}).get(striker_no, 60)), 1, 100)
        skill_f = batter_skill_factors(striker_skill, shot)

        base_wicket = 0.075
        p_w = wicket_probability(base_wicket, [
            pm["wicket"], dm["wicket"], pdm["wicket"], phm["wicket"],
            sp["wicket"], lp["wicket"], ip["wicket"],
            bt["wicket"], bskill_wicket, fat_wicket,
            skill_f["wicket"],
        ])

        is_free_hit = bool(self.free_hit[bat_team])

        if extra_type == "WD":
            kind = "EXTRA"
            runs_extra = 1
            if random.random() < 0.20:
                runs_extra += 1
            if random.random() < 0.07:
                runs_extra += 1

        elif extra_type == "NB":
            kind = "EXTRA"
            runs_extra = 1
            free_hit_after = True
            runs_bat = bat_runs_distribution(
                sp["bat_max"],
                pm["boundary"] * dm["boundary"] * pdm["boundary"] * phm["boundary"]
                * lp["boundary"] * ip["boundary"]
                * bt["boundary"] * max(0.70, bskill_boundary) * fat_boundary * skill_f["boundary"],
                sp["six_boost"]
            )

        elif extra_type in ("B", "LB"):
            kind = "LEGAL"
            runs_extra = random.choice([0, 1, 1, 2, 2, 3, 4])
            runs_bat = 0

        else:
            kind = "LEGAL"
            runs_bat = bat_runs_distribution(
                sp["bat_max"],
                pm["boundary"] * dm["boundary"] * pdm["boundary"] * phm["boundary"]
                * lp["boundary"] * ip["boundary"]
                * bt["boundary"] * max(0.70, bskill_boundary) * fat_boundary * skill_f["boundary"],
                sp["six_boost"]
            )

        runs_total = runs_bat + runs_extra

        # wicket logic
        if kind == "LEGAL":
            self.batter_balls_faced[bat_team][striker_no] += 1
            if random.random() < p_w:
                if is_free_hit:
                    wicket = True
                    wicket_type = "RUNOUT"
                else:
                    wicket = True
                    if length == "YORKER" and random.random() < 0.40:
                        wicket_type = "BOWLED"
                    elif shot in ("PULL", "SLOG") and random.random() < 0.55:
                        wicket_type = "CAUGHT"
                    else:
                        wicket_type = random.choice(WICKET_TYPES)

        elif extra_type == "NB":
            if (not is_free_hit) and random.random() < 0.01:
                wicket = True
                wicket_type = "RUNOUT"
        elif extra_type == "WD":
            if random.random() < 0.008:
                wicket = True
                wicket_type = "RUNOUT"

        # apply score/wicket
        self.scores[bat_team] += runs_total
        self.batter_runs[bat_team][striker_no] += runs_bat

        # Tier3++: partnership tracking
        self.partnership_runs[bat_team] = int(self.partnership_runs.get(bat_team, 0) + runs_total)
        if kind == "LEGAL":
            self.partnership_balls[bat_team] = int(self.partnership_balls.get(bat_team, 0) + 1)

        if wicket:
            self.wkts[bat_team] += 1

        # strike rotation (odd total)
        if runs_total % 2 == 1:
            self.swap_strike(bat_team)

        # legal ball count + over end swap
        if kind == "LEGAL":
            self.balls[bat_team] += 1
            self.legal_in_over[bat_team] += 1

            # fatigue update for current bowler (legal balls only)
            try:
                bt_tag = bowler_tag
                self.bowler_legal_balls[bowl_team][bt_tag] += 1

                base_inc = float(bt.get("fatigue_inc", 0.030))
                inc = base_inc * (1.0 + (0.18 if intent == "BA" else 0.0)) / max(0.60, float(bstamina))
                self.bowler_fatigue[bowl_team][bt_tag] = min(1.0, self.bowler_fatigue[bowl_team][bt_tag] + inc)

                # small recovery for other bowlers (rest)
                for other_tag in self.allowed_bowler_tags():
                    if other_tag == bt_tag:
                        continue
                    cur = float(self.bowler_fatigue[bowl_team].get(other_tag, 0.0))
                    self.bowler_fatigue[bowl_team][other_tag] = max(0.0, cur - 0.003)
            except Exception:
                pass

            self.free_hit[bat_team] = False

            if self.legal_in_over[bat_team] >= 6:
                self.legal_in_over[bat_team] = 0
                self.swap_strike(bat_team)
                self.last_over_bowler_tag[bowl_team] = self.current_bowler_tag[bowl_team]

                # next over suggested bowler (deterministic rotation)
                try:
                    sug = self.compute_suggested_bowler()
                    self.suggested_bowler_tag[bowl_team] = sug
                except Exception:
                    pass

                # between-overs recovery for the bowling side
                try:
                    cur = self.current_bowler_tag[bowl_team]
                    for t in self.allowed_bowler_tags():
                        if t not in self.bowler_fatigue[bowl_team]:
                            continue
                        if t == cur:
                            self.bowler_fatigue[bowl_team][t] = max(0.0, self.bowler_fatigue[bowl_team][t] - 0.01)
                        else:
                            self.bowler_fatigue[bowl_team][t] = max(0.0, self.bowler_fatigue[bowl_team][t] - 0.04)
                except Exception:
                    pass

                self.turn = "SELECT_BOWLER"
        else:
            if extra_type == "NB":
                self.free_hit[bat_team] = True

        # new batter
        if wicket and self.wkts[bat_team] < self.wickets_total:
            # partnership ends on wicket
            self.partnership_runs[bat_team] = 0
            self.partnership_balls[bat_team] = 0
            self.new_batter_in(bat_team)

        ball_no = self.balls[bat_team]
        ov = overs_str(ball_no)

        batter_name = f"{self.names[bat_team]}-BAT{self.current_batter_no[bat_team]}"
        bowler_tag = self.current_bowler_tag[bowl_team]
        bowler_name = f"{self.names[bowl_team]}-{bowler_tag}"

        rec = {
            "innings": self.innings,
            "ball_no": ball_no,
            "over": ov,
            "batter": batter_name,
            "bowler": bowler_name,
            "shot": shot,
            "bowl_intent": intent,
            "length": length,
            "kind": kind,
            "runs_bat": runs_bat,
            "runs_extra": runs_extra,
            "extra_type": extra_type or "",
            "runs_total": runs_total,
            "wicket": wicket,
            "wicket_type": wicket_type if wicket else "",
            "free_hit_after": bool(free_hit_after),
            "score_now": self.scores[bat_team],
            "wkts_now": self.wkts[bat_team],
            "target": self.target if self.target is not None else "",
        }
        self.history.append(rec)

        fh_txt = " | FREE HIT next" if free_hit_after else ""
        wtxt = f" WICKET({wicket_type})!" if wicket else ""
        ex = f" +{extra_type}" if extra_type else ""
        self.last_event = f"{ov}: {bowler_name} {intent}/{length} vs {shot}{ex} => bat={runs_bat}, extra={runs_extra}, total={runs_total}.{wtxt}{fh_txt}"

        # chase win
        if self.innings == 2 and self.target is not None and self.scores[bat_team] >= int(self.target):
            self.finish_match("CHASE COMPLETED")
            return

        # innings end
        if self.balls[bat_team] >= self.balls_total or self.wkts[bat_team] >= self.wickets_total:
            if self.innings == 1:
                self.target = self.scores[bat_team] + 1
                self.innings = 2
                self.batting_idx = 1 - self.batting_idx
                self.bowling_idx = 1 - self.batting_idx
                self.turn = "SELECT_BOWLER"
                self.legal_in_over[self.batting_idx] = 0
                self.last_event += f" | INNINGS BREAK: target={self.target} for {self.names[self.batting_idx]}"
                self.pending_bat = None
                self.pending_bowl = None
                return
            else:
                self.finish_match("CHASE FAILED / OVERS DONE or ALL OUT")
                return

        # continue
        if self.phase == "PLAYING":
            if self.turn != "SELECT_BOWLER":
                self.turn = "BAT"
            self.pending_bat = None
            self.pending_bowl = None
