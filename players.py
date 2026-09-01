"""Yahoo <-> Sleeper player ID crosswalk.

Sleeper supplies weekly projections; Yahoo supplies roster and league state.
Nothing links them but the player's name and team, so this module normalizes
both sides into a comparable key and reports what failed to match instead of
silently dropping it.

Sleeper's /players/nfl payload is ~5MB and changes slowly. Fetch it once a day
at most and cache it; the endpoint is public and unauthenticated.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import requests

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
CACHE_DIR = Path.home() / ".cache" / "ffl-mcp"
CACHE_TTL_SECONDS = 24 * 60 * 60

# Yahoo and Sleeper disagree on a handful of team abbreviations.
TEAM_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "LA": "LAR",
    "SD": "LAC",
    "OAK": "LV",
    "STL": "LAR",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
}

# Stripped from the end of a surname before comparison.
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Yahoo names team defenses "Chicago", Sleeper keys them by team abbreviation.
DEF_POSITIONS = {"DEF", "DST", "D/ST"}


def normalize_team(team: str | None) -> str:
    if not team:
        return ""
    t = team.strip().upper()
    return TEAM_ALIASES.get(t, t)


def normalize_name(name: str) -> str:
    """Fold a display name down to something two sources can agree on.

    Handles accents, punctuation ("Ja'Marr" / "JaMarr"), generational
    suffixes, and inconsistent spacing. Deliberately does NOT strip middle
    names, since Sleeper and Yahoo both use first + last.
    """
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower()
    n = re.sub(r"[.'`\u2019\-]", "", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    parts = [p for p in n.split() if p]
    while parts and parts[-1] in SUFFIXES:
        parts.pop()
    return " ".join(parts)


def match_key(name: str, team: str | None, position: str | None) -> str:
    """The join key. Defenses key on team alone; everyone else on name+team."""
    pos = (position or "").upper().replace(".", "")
    if pos in DEF_POSITIONS:
        return f"DEF|{normalize_team(team)}"
    return f"{normalize_name(name)}|{normalize_team(team)}"


def name_only_key(name: str, position: str | None) -> str:
    pos = (position or "").upper().replace(".", "")
    if pos in DEF_POSITIONS:
        return ""
    return normalize_name(name)


def fetch_sleeper_players(force: bool = False) -> dict:
    """Return Sleeper's full player map, cached on disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "sleeper_players.json"

    if not force and cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            return json.loads(cache.read_text())

    resp = requests.get(SLEEPER_PLAYERS_URL, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    cache.write_text(json.dumps(data))
    return data


@dataclass
class Crosswalk:
    """Maps Yahoo player_id -> Sleeper player_id."""

    by_id: dict[str, str] = field(default_factory=dict)
    unmatched: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)

    def sleeper_id(self, yahoo_id: str) -> str | None:
        return self.by_id.get(str(yahoo_id))

    @property
    def match_rate(self) -> float:
        total = len(self.by_id) + len(self.unmatched)
        return len(self.by_id) / total if total else 0.0


def _index_sleeper(sleeper: dict) -> tuple[dict, dict]:
    """Build exact (name+team) and fallback (name-only) indexes."""
    exact: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}

    for sid, p in sleeper.items():
        pos = p.get("position") or ""
        team = p.get("team")

        if pos in DEF_POSITIONS:
            full = p.get("team") or ""
        else:
            full = (p.get("full_name") or
                    f"{p.get('first_name', '')} {p.get('last_name', '')}").strip()
        if not full:
            continue

        # Inactive/retired players have no team; they can't be free agents
        # worth analyzing, but keep them for name-only fallback.
        exact.setdefault(match_key(full, team, pos), []).append(sid)
        nk = name_only_key(full, pos)
        if nk:
            by_name.setdefault(nk, []).append(sid)

    return exact, by_name


def build_crosswalk(yahoo_players: list[dict], sleeper: dict | None = None) -> Crosswalk:
    """Join a list of Yahoo players to Sleeper IDs.

    yahoo_players entries need: player_id, name (full), editorial_team_abbr,
    display_position -- all present in a standard Yahoo players collection
    response.
    """
    sleeper = sleeper if sleeper is not None else fetch_sleeper_players()
    exact, by_name = _index_sleeper(sleeper)
    cw = Crosswalk()

    for yp in yahoo_players:
        yid = str(yp.get("player_id"))
        name = yp.get("name") or ""
        if isinstance(name, dict):  # Yahoo nests name as {full, first, last}
            name = name.get("full", "")
        team = yp.get("editorial_team_abbr")
        pos = (yp.get("display_position") or "").split(",")[0]

        hits = exact.get(match_key(name, team, pos), [])

        if not hits:
            # Player changed teams mid-week, or one source is stale. Fall back
            # to name alone, but only accept it if it's unambiguous.
            hits = by_name.get(name_only_key(name, pos), [])
            if len(hits) > 1:
                cw.ambiguous.append({"yahoo_id": yid, "name": name,
                                     "team": team, "candidates": hits})
                continue

        if len(hits) == 1:
            cw.by_id[yid] = hits[0]
        elif len(hits) > 1:
            cw.ambiguous.append({"yahoo_id": yid, "name": name,
                                 "team": team, "candidates": hits})
        else:
            cw.unmatched.append({"yahoo_id": yid, "name": name,
                                 "team": team, "position": pos})

    return cw


if __name__ == "__main__":
    # Smoke test against Sleeper alone -- no Yahoo access needed.
    sl = fetch_sleeper_players()
    print(f"sleeper players: {len(sl)}")

    fake_yahoo = [
        {"player_id": "1", "name": "Ja'Marr Chase",
         "editorial_team_abbr": "Cin", "display_position": "WR"},
        {"player_id": "2", "name": "Marvin Harrison Jr.",
         "editorial_team_abbr": "Ari", "display_position": "WR"},
        {"player_id": "3", "name": "Chicago",
         "editorial_team_abbr": "Chi", "display_position": "DEF"},
        {"player_id": "4", "name": "Amon-Ra St. Brown",
         "editorial_team_abbr": "Det", "display_position": "WR"},
        {"player_id": "5", "name": "Travis Etienne Jr.",
         "editorial_team_abbr": "Jac", "display_position": "RB"},
    ]
    cw = build_crosswalk(fake_yahoo, sl)
    print(f"matched:   {cw.by_id}")
    print(f"unmatched: {cw.unmatched}")
    print(f"ambiguous: {cw.ambiguous}")
    print(f"rate:      {cw.match_rate:.0%}")
