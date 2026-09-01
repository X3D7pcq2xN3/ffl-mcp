"""Assemble the weekly digest: scored data in, prose recommendation out.

Division of labor: this module does every calculation. Projections, start/sit
comparisons, bye-week holes, and free-agent ranking are all computed here from
validated code. The model receives finished numbers and reasons about them --
whether a 3-point edge justifies a waiver claim, whether an injury designation
changes the call -- but never recomputes a projection.

That split is deliberate. Arithmetic in code can be validated (see
validate_scoring.py); judgment cannot. Keep the arithmetic here.
"""

from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass

import requests

import notify

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

# How many free agents to send. The pool is hundreds deep; the model only
# needs the plausible adds, and a long list buries the real signal.
CANDIDATES_PER_POSITION = 6

# Noise floors. A projection is an estimate, and a sub-2-point gap between
# two players is well inside the error of that estimate -- acting on it is
# coin-flipping with extra steps.
#
# These exist here rather than in the prompt because a filter is testable and
# a judgment instruction is not: handed a list of positive-delta findings, a
# model reads it as a to-do list and reports the marginal ones while arguing
# against them. Filter first, then ask for judgment on what survives.
#
# Tune from real results. If a week produces nothing and you later wish it
# had flagged something, lower these. If the digest feels noisy, raise them.
MIN_SWAP_GAIN = 2.0        # points a bench player must beat a starter by
MIN_CANDIDATE_GAIN = 2.0   # points a free agent must beat your worst by

# Exception: a starter who cannot play (bye, out, IR) is not a marginal
# comparison -- any legal replacement beats zero. Swaps into a slot flagged
# as a hole bypass MIN_SWAP_GAIN.

SYSTEM_PROMPT = """You advise on one fantasy football roster.

Every projection you are given was computed under this league's own scoring
rules. Treat them as accurate. Do not recompute, re-rank by your own
estimates, or substitute general player knowledge for the numbers provided.

Reason ONLY from the data in the payload. You are given projections, roster
slots, injury designations, bye weeks, and ownership percentages. You are NOT
given matchup quality, defensive rankings, weather, snap counts, or target
share. Do not invent them. An opponent abbreviation is identification, not
evidence -- never argue a player is favored or disadvantaged by their
opponent. If a recommendation would need information you do not have, say
what would settle it instead of guessing.

Do not assume a player's gender. Use the player's name or "they".

The payload lists the league's starting slots. Every lineup change you
recommend must be legal under those slots: name the slot a player moves into,
and confirm the vacated slot still gets filled. Never suggest a bench player
for a slot their position cannot occupy.

Your job is judgment on top of the numbers:
- Is a projected edge large enough to act on, or is it noise?
- Does an injury designation or bye change the call?
- Is a waiver claim worth spending when the upgrade is marginal?

You are given ONE week of projections. That is enough to decide who starts
this week. It is not enough to decide who to cut: a low weekly projection may
be a bye, an injury, or a bad week for a player worth keeping. Recommend a
DROP only when the payload gives a reason beyond a single week's number, and
name that reason. Otherwise, when an add requires a corresponding drop, say
the roster spot has to come from somewhere and leave the choice to me.

Report every item you would act on yourself. There is no minimum and no
maximum. Some weeks the right answer is one line saying the lineup is set;
some weeks there are five real problems. Never pad, and never omit a real
recommendation to stay short.

The test for including an item: would you make this move? If your own answer
is "probably not" or "it's marginal," leave it out entirely. Do not report a
move and then argue against it -- that costs the reader attention and gives
them nothing. A difference inside projection noise is not a finding.

OUTPUT FORMAT

Read on a phone, in a plain-text chat. No markdown is rendered: asterisks,
pound signs, and pipe tables show up as literal characters and make it worse.

Match this shape exactly:

Lineup
  RB     Runner C   was Runner B, bye
  W/R/T  Catcher C  was Runner C   +3.9

Claim
  FA Back  RB 10.4  31% owned, waivers close tonight

Check
  Catcher B is Q. If out, Catcher C to WR, Runner C to W/R/T.

Rules for that shape:
- Three blocks: Lineup, Claim, Check. Omit any block with nothing in it.
- Block name alone on its line. Two spaces indent for entries.
- No #, *, |, or table syntax anywhere. Ever.
- Lineup lists only slots that CHANGE, as final state. Never explain the
  sequence or add a sentence after the table -- the final state is the whole
  instruction. One table even when several findings share one fix.
- Give +X.X when a projection gap drove it, or the reason when it was forced.
- Claim: name, position, projection, and ONE fact that decides it. If a claim
  needs a drop, add "needs a roster spot" -- do not pick who to cut.
- Check: what might change, and the fallback, in one line.
- Every line under 15 words. No line wraps to a third phone line.

If nothing needs doing, the entire response is: Lineup is set, nothing worth
claiming.

Be direct about uncertainty. "Projections disagree here" is more useful than
false confidence."""


@dataclass
class Player:
    name: str
    position: str
    slot: str | None      # roster slot, or None if on bench
    projection: float
    team: str = ""
    opponent: str = ""
    status: str = ""      # Q, D, O, IR, or empty
    on_bye: bool = False
    owned_pct: float | None = None
    on_waivers: bool = False

    def to_dict(self) -> dict:
        d = {"name": self.name, "pos": self.position,
             "proj": round(self.projection, 1)}
        if self.slot:
            d["slot"] = self.slot
        if self.opponent:
            d["opp"] = self.opponent
        if self.status:
            d["status"] = self.status
        if self.on_bye:
            d["bye"] = True
        if self.owned_pct is not None:
            d["owned_pct"] = round(self.owned_pct)
        if self.on_waivers:
            d["waivers"] = True
        return d


# Roster slots that accept more than one position. A slot name is matched
# case-insensitively against these keys; anything else is treated as a
# dedicated slot that only its own position can fill.
FLEX_SLOTS = {
    "W/R": {"WR", "RB"},
    "W/T": {"WR", "TE"},
    "W/R/T": {"WR", "RB", "TE"},
    "FLEX": {"WR", "RB", "TE"},
    "Q/W/R/T": {"QB", "WR", "RB", "TE"},
    "SUPERFLEX": {"QB", "WR", "RB", "TE"},
    "OP": {"QB", "WR", "RB", "TE"},
}


def slot_accepts(slot: str | None, position: str) -> bool:
    """Can `position` legally occupy `slot`?

    Yahoo rejects an illegal lineup outright, so a suggestion that can't be
    executed is worse than no suggestion -- it costs a trip to the app to
    discover it doesn't work.
    """
    if not slot:
        return False
    key = slot.strip().upper()
    if key in FLEX_SLOTS:
        return position in FLEX_SLOTS[key]
    return key == position.upper()


def find_start_sit(starters: list[Player], bench: list[Player],
                   flex_eligible: set[str] | None = None,
                   min_gain: float = MIN_SWAP_GAIN) -> list[dict]:
    """Bench players outprojecting a starter at a slot they can legally fill.

    Swaps below min_gain are dropped as noise -- unless the starter cannot
    play, in which case any legal replacement is worth naming.
    """
    findings = []
    for benched in bench:
        if benched.on_bye or benched.status in ("O", "IR"):
            continue
        for starter in starters:
            if starter.projection >= benched.projection:
                continue
            slot = starter.slot or ""
            if not slot_accepts(slot, benched.position):
                continue

            gain = benched.projection - starter.projection
            unavailable = starter.on_bye or starter.status in ("O", "IR")
            if gain < min_gain and not unavailable:
                continue

            findings.append({
                "type": "start_sit",
                "slot": slot,
                "start": benched.to_dict(),
                "over": starter.to_dict(),
                "gain": round(gain, 1),
                "forced": unavailable,
            })
    findings.sort(key=lambda f: (f["forced"], f["gain"]), reverse=True)
    return findings


def find_holes(starters: list[Player]) -> list[dict]:
    """Starting slots filled by someone on bye, out, or projecting near zero."""
    holes = []
    for p in starters:
        reason = None
        if p.on_bye:
            reason = "bye"
        elif p.status in ("O", "IR"):
            reason = f"out ({p.status})"
        elif p.projection < 1.0:
            reason = "no projection"
        if reason:
            holes.append({"type": "hole", "slot": p.slot,
                          "player": p.to_dict(), "reason": reason})
    return holes


def rank_candidates(free_agents: list[Player],
                    roster: list[Player],
                    per_position: int = CANDIDATES_PER_POSITION,
                    min_gain: float = MIN_CANDIDATE_GAIN) -> list[dict]:
    """Free agents who beat your worst rostered player at their position.

    Beating your worst bench player by a point is not a reason to spend a
    waiver claim, so anything under min_gain is dropped before the model
    sees it.
    """
    worst_by_pos: dict[str, float] = {}
    for p in roster:
        if p.on_bye or p.status in ("O", "IR"):
            continue
        cur = worst_by_pos.get(p.position)
        if cur is None or p.projection < cur:
            worst_by_pos[p.position] = p.projection

    by_pos: dict[str, list[Player]] = {}
    for fa in free_agents:
        floor = worst_by_pos.get(fa.position)
        if floor is None or fa.projection - floor < min_gain:
            continue
        by_pos.setdefault(fa.position, []).append(fa)

    out = []
    for pos, players in by_pos.items():
        players.sort(key=lambda p: p.projection, reverse=True)
        for p in players[:per_position]:
            out.append({
                "type": "candidate",
                "player": p.to_dict(),
                "beats_worst_rostered": round(
                    p.projection - worst_by_pos[pos], 1),
            })
    out.sort(key=lambda c: c["beats_worst_rostered"], reverse=True)
    return out


def roster_slots(starters: list[Player]) -> list[dict]:
    """The league's starting slots and what each accepts.

    Without this the model can only infer lineup structure from which slots
    happen to be occupied, which is how it ends up suggesting a starter be
    moved to "his bench spot" -- a place that does not exist.
    """
    slots = []
    for p in starters:
        key = (p.slot or "").strip().upper()
        slots.append({
            "slot": p.slot,
            "accepts": sorted(FLEX_SLOTS[key]) if key in FLEX_SLOTS else [key],
            "current": p.name,
        })
    return slots


def build_payload(week: int, starters: list[Player], bench: list[Player],
                  free_agents: list[Player], scoring: dict,
                  flex_eligible: set[str] | None = None) -> dict:
    roster = starters + bench

    return {
        "week": week,
        "scoring_notes": {
            "ppr": scoring.get("rec", 0),
            "te_premium": scoring.get("bonus_rec_te", 0) or None,
        },
        "roster_slots": roster_slots(starters),
        "data_provided": [
            "projections (computed under this league's scoring)",
            "roster slots and eligibility",
            "injury status", "bye weeks", "ownership percentage",
        ],
        "data_NOT_provided": [
            "matchup quality", "defensive rankings", "weather",
            "snap counts", "target share", "recent form",
        ],
        "lineup": [p.to_dict() for p in starters],
        "bench": [p.to_dict() for p in bench],
        "findings": (find_holes(starters)
                     + find_start_sit(starters, bench)[:5]),
        "available": rank_candidates(free_agents, roster),
    }


def ask_model(payload: dict, api_key: str | None = None) -> str:
    notify.load_env()  # explicit, not a side effect of importing notify
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env or environment")

    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 900,
            "system": SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": (
                    "Week " + str(payload["week"]) + " roster review.\n\n"
                    + json.dumps(payload, indent=1)
                ),
            }],
        },
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    return "".join(b.get("text", "") for b in body.get("content", [])
                   if b.get("type") == "text").strip()


def strip_markdown(text: str) -> str:
    """Remove markdown the model emitted despite being told not to.

    A prompt rule is a request; this is the guarantee. Pipes and pound signs
    render as literal noise in a plain-text chat, which is exactly the thing
    that makes a digest not worth reading.
    """
    out = []
    for line in text.splitlines():
        s = line.strip()
        # Drop table separator rows: |---|---|
        if s.startswith("|") and set(s) <= set("|-: "):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)          # headers
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)    # bold
        line = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", line)
        line = re.sub(r"^\s*[-*+]\s+", "  ", line)      # bullets -> indent
        if "|" in line:                                  # table row -> spaces
            line = "  " + "  ".join(
                c.strip() for c in line.strip().strip("|").split("|")
                if c.strip())
        out.append(line.rstrip())

    # Collapse runs of blank lines
    cleaned, blank = [], False
    for line in out:
        if not line.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def run(week: int, starters, bench, free_agents, scoring) -> str:
    """Assemble, ask, deliver. Reports its own failure rather than dying quiet."""
    try:
        payload = build_payload(week, starters, bench, free_agents, scoring)
        text = strip_markdown(ask_model(payload))
        notify.send(f"Week {week}\n\n{text}", markdown=False)
        return text
    except Exception as exc:
        notify.send_failure(f"week {week} digest", exc)
        raise


def demo() -> tuple:
    """Fixture roster for testing without Yahoo access.

    Deliberately includes: a bye-week starter, a Q-tagged starter, a bench
    player who beats a starter at a legal slot, a bench player who beats a
    starter at an ILLEGAL slot (TE vs a dedicated RB slot), and a free agent
    below every rostered player.
    """
    starters = [
        Player("Passer A", "QB", "QB", 18.4, opponent="@SF"),
        Player("Runner A", "RB", "RB", 14.1, opponent="vs DAL"),
        Player("Runner B", "RB", "RB", 6.1, on_bye=True),
        Player("Catcher A", "WR", "WR", 15.8, opponent="@GB"),
        Player("Catcher B", "WR", "WR", 9.2, status="Q", opponent="vs NYJ"),
        Player("Tight A", "TE", "TE", 7.7, opponent="@MIA"),
        Player("Runner C", "RB", "W/R/T", 8.0, opponent="vs LAR"),
    ]
    bench = [
        Player("Catcher C", "WR", None, 11.9, opponent="vs CHI"),
        Player("Runner D", "RB", None, 4.2, opponent="@BUF"),
        Player("Tight B", "TE", None, 8.9, opponent="vs DEN"),
    ]
    free_agents = [
        Player("FA Back", "RB", None, 10.4, owned_pct=31, on_waivers=True),
        Player("FA Wide", "WR", None, 8.1, owned_pct=12),
        Player("FA End", "TE", None, 9.6, owned_pct=44, on_waivers=True),
        Player("FA Scrub", "RB", None, 2.0, owned_pct=1),
    ]
    scoring = {"rec": 0.5, "rec_yd": 0.1, "rush_yd": 0.1}
    return starters, bench, free_agents, scoring


if __name__ == "__main__":
    import sys

    starters, bench, free_agents, scoring = demo()

    if "--send" in sys.argv:
        # Full path: assemble -> Anthropic -> Telegram.
        print(run(3, starters, bench, free_agents, scoring))
    elif "--ask" in sys.argv:
        # Model call only, printed locally. No Telegram, no cost surprise.
        payload = build_payload(3, starters, bench, free_agents, scoring)
        print(ask_model(payload))
    else:
        # Default: assembly only. No network, no API key needed.
        payload = build_payload(3, starters, bench, free_agents, scoring)
        print(json.dumps(payload, indent=2))
