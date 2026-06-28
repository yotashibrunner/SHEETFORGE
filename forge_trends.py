#!/usr/bin/env python3
"""
forge_trends.py  -  SheetForge trend finder

Discovers and ranks spreadsheet/template niches by demand-with-weak-supply,
then emits a `catalog`-shaped queue that forge_batch.py turns into products.

Pipeline:
    discover candidates  ->  pull signals  ->  score  ->  IP-safe filter
                         ->  rank          ->  write trend_queue.json
                                                + catalog.generated.json
                         ->  (optional) hand winners to the forge

Signal sources (pluggable, graceful degradation):
    GoogleTrends  - interest level + rising/breakout flag        (pytrends, unofficial)
    Reddit        - mention velocity in template-intent posts    (public .json, no auth)
    Etsy          - listing count + autocomplete (SUPPLY signal) (opt-in, brittle, no API)

Honesty notes:
  * pytrends and the Etsy probes are unofficial; they break when Google/Etsy change
    things. Everything is wrapped so a dead source degrades the score, never crashes
    the run.
  * Without the Etsy source, supply_gap is a HEURISTIC, not measured. The "winners"
    are then "rising demand" picks, not verified demand-minus-supply. Turn Etsy on
    (or paste in your own listing counts) before trusting the gap number.

Run:
    pip install requests pytrends      # anthropic only needed for --ip-check
    python forge_trends.py --offline             # mock signals, proves the pipeline
    python forge_trends.py                        # live Trends + Reddit
    python forge_trends.py --etsy --ip-check      # add supply probe + IP classifier
    python forge_trends.py --build --top 8        # also run forge_batch on winners
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ----------------------------------------------------------------------------- #
#  Eric's verticals  -  domain-authority weighting.
#  A niche that overlaps these gets a fit bonus: it's where slop guesses wrong
#  and your listings read with real authority. Tune weights freely.
# ----------------------------------------------------------------------------- #
VERTICALS = {
    "reselling":   {"weight": 1.00, "seeds": ["ebay reseller", "etsy seller", "poshmark", "amazon fba", "flipping inventory", "online arbitrage"]},
    "automotive":  {"weight": 0.95, "seeds": ["auto repair shop", "fleet maintenance", "car maintenance", "mechanic job", "vehicle mileage", "diy car"]},
    "homestead":   {"weight": 0.90, "seeds": ["homestead", "off grid", "chicken flock", "garden planting", "canning", "food preservation"]},
    "farm_spice":  {"weight": 0.90, "seeds": ["garlic farm", "herb garden", "farmers market", "small farm", "csa share", "spice business"]},
    "smallbiz":    {"weight": 0.70, "seeds": ["small business", "side hustle", "freelancer", "etsy shop", "craft business", "1099 taxes"]},
    "_general":    {"weight": 0.40, "seeds": ["budget", "savings", "debt payoff", "meal plan", "wedding", "fitness", "habit", "project"]},
}

# Template archetypes + a saturation prior (1.0 = wide open, 0.1 = a bloodbath).
# Used as the supply_gap fallback when the Etsy source is off.
ARCHETYPES = {
    "tracker":     0.55,
    "log":         0.65,
    "planner":     0.45,
    "budget":      0.20,   # ~10k competitors, race to the bottom
    "calculator":  0.80,   # tools are hard for slop to copy -> your edge
    "dashboard":   0.75,
    "inventory":   0.70,
    "schedule":    0.50,
    "checklist":   0.40,
}

# Words that signal "this person wants a spreadsheet/template" -> discovery filter.
INTENT = re.compile(
    r"\b(spreadsheet|template|tracker|planner|log\b|logbook|calculator|"
    r"dashboard|inventory|budget(?:ing)?|checklist)\b", re.I)

# Subreddits worth scanning for emerging "I need to track X" demand.
SUBREDDITS = [
    "personalfinance", "smallbusiness", "Etsy", "Flipping", "ResellingBusiness",
    "homestead", "gardening", "AutoDetailing", "MechanicAdvice", "ynab",
    "ExcelTips", "spreadsheets", "sidehustle",
]

UA = "SheetForge-TrendFinder/1.0 (personal research; contact via github yotashibrunner)"


# ----------------------------------------------------------------------------- #
#  Data model
# ----------------------------------------------------------------------------- #
@dataclass
class Candidate:
    niche: str                       # e.g. "ebay reseller"
    archetype: str                   # e.g. "tracker"
    vertical: str = "_general"
    # raw signals (0..1 unless noted)
    trends_interest: float = 0.0     # 0..1  (Google interest / 100)
    trends_rising: bool = False
    reddit_mentions: int = 0
    etsy_listings: int = -1          # -1 = unknown
    etsy_top_quality: float = -1.0   # -1 = unknown, else 0..1 (1 = polished comp)
    # derived
    demand: float = 0.0
    velocity: float = 0.0
    supply_gap: float = 0.0
    fit: float = 0.0
    ip_safe: bool = True
    ip_reason: str = ""
    score: float = 0.0
    title: str = ""
    keywords: list = field(default_factory=list)

    @property
    def query(self) -> str:
        return f"{self.niche} {self.archetype}".strip()


# ----------------------------------------------------------------------------- #
#  Candidate generation:  seeds x archetypes  +  live discovery
# ----------------------------------------------------------------------------- #
def seed_candidates() -> list:
    out = []
    for vname, v in VERTICALS.items():
        for seed in v["seeds"]:
            for arch in ARCHETYPES:
                out.append(Candidate(niche=seed, archetype=arch, vertical=vname))
    return out


def discover_from_reddit(session, limit_per_sub=40):
    """Pull rising/new posts, keep template-intent phrases we didn't seed.
    Returns {phrase: mention_count}. Public JSON; no auth, just polite UA + sleep."""
    found = {}
    for sub in SUBREDDITS:
        for sort in ("new", "rising"):
            url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit={limit_per_sub}"
            try:
                r = session.get(url, timeout=12)
                if r.status_code != 200:
                    continue
                for child in r.json().get("data", {}).get("children", []):
                    d = child.get("data", {})
                    text = f"{d.get('title','')} {d.get('selftext','')}"
                    if INTENT.search(text):
                        # crude noun-phrase grab around the intent word
                        for m in INTENT.finditer(text):
                            window = text[max(0, m.start() - 40): m.end() + 10]
                            phrase = _clean_phrase(window)
                            if phrase:
                                found[phrase] = found.get(phrase, 0) + 1
                time.sleep(1.1)   # be a good citizen
            except Exception as e:
                _warn(f"reddit {sub}/{sort}: {e}")
    return found


def _clean_phrase(window: str) -> str:
    window = re.sub(r"[^a-zA-Z ]", " ", window).lower()
    words = [w for w in window.split() if len(w) > 2]
    return " ".join(words[-4:]) if len(words) >= 2 else ""


# ----------------------------------------------------------------------------- #
#  Signal sources
# ----------------------------------------------------------------------------- #
class GoogleTrendsSource:
    """interest_over_time + rising-related-queries via pytrends (UNOFFICIAL)."""
    def __init__(self):
        self.pt = None
        try:
            from pytrends.request import TrendReq
            self.pt = TrendReq(hl="en-US", tz=300)
        except Exception as e:
            _warn(f"pytrends unavailable, Trends disabled: {e}")

    def enrich(self, c: Candidate):
        if not self.pt:
            return
        try:
            self.pt.build_payload([c.query], timeframe="today 12-m", geo="US")
            df = self.pt.interest_over_time()
            if df is not None and not df.empty and c.query in df:
                series = df[c.query].tolist()
                c.trends_interest = (sum(series[-8:]) / 8) / 100.0  # recent avg
                # rising = last quarter clearly above first
                first, last = series[: len(series)//4] or [0], series[-len(series)//4:] or [0]
                c.trends_rising = (sum(last)/len(last)) > 1.25 * (sum(first)/len(first) + 1e-6)
            time.sleep(1.5)  # pytrends rate-limits hard
        except Exception as e:
            _warn(f"trends '{c.query}': {e}")


class EtsySource:
    """SUPPLY probe: approx listing count + a cheap top-result quality read.
    No official keyword API -> this scrapes the public results page and WILL
    break when Etsy changes markup. Opt-in only. Treat numbers as rough."""
    def __init__(self, session):
        self.s = session

    def enrich(self, c: Candidate):
        try:
            url = f"https://www.etsy.com/search?q={re.sub(r' ', '+', c.query)}"
            r = self.s.get(url, timeout=15)
            if r.status_code != 200:
                return
            html = r.text
            m = re.search(r"([\d,]+)\s+results", html)
            if m:
                c.etsy_listings = int(m.group(1).replace(",", ""))
            # crude "slop vs polished" proxy: bestseller badges per page of results.
            badges = len(re.findall(r"Bestseller", html))
            c.etsy_top_quality = min(1.0, badges / 12.0)  # many badges => strong comps
            time.sleep(2.0)
        except Exception as e:
            _warn(f"etsy '{c.query}': {e}")


# ----------------------------------------------------------------------------- #
#  IP-safe classifier  (Anthropic API)  -  flags trademarked planner/brand names
# ----------------------------------------------------------------------------- #
def ip_check(cands, model="claude-sonnet-4-6"):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        _warn("ANTHROPIC_API_KEY not set -> skipping IP check (all marked safe).")
        return
    try:
        import anthropic
    except Exception:
        _warn("anthropic sdk missing -> skipping IP check.")
        return
    client = anthropic.Anthropic(api_key=key)
    names = [c.query for c in cands]
    prompt = (
        "You screen spreadsheet-template product names for trademark / brand risk "
        "before they're sold on Etsy. For EACH name, return whether it's safe to use "
        "as a generic template title. UNSAFE = contains a registered brand/planner "
        "trademark (e.g. Erin Condren, Passion Planner, YNAB, Monarch, Clockify) or a "
        "protected character/franchise. Generic descriptive niches are SAFE.\n\n"
        "Return ONLY a JSON array, one object per input, same order, no prose:\n"
        '[{"name":"...","safe":true,"reason":"..."}]\n\n'
        "Names:\n" + "\n".join(f"- {n}" for n in names)
    )
    try:
        resp = client.messages.create(
            model=model, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        txt = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        txt = re.sub(r"```json|```", "", txt).strip()
        verdicts = json.loads(txt)
        by_name = {v["name"]: v for v in verdicts}
        for c in cands:
            v = by_name.get(c.query)
            if v:
                c.ip_safe = bool(v.get("safe", True))
                c.ip_reason = v.get("reason", "")
    except Exception as e:
        _warn(f"ip check failed, leaving all safe: {e}")


# ----------------------------------------------------------------------------- #
#  Scoring
# ----------------------------------------------------------------------------- #
WEIGHTS = {"demand": 0.40, "velocity": 0.25, "gap": 0.25, "fit": 0.10}


def score_all(cands, max_reddit):
    for c in cands:
        # demand: Trends interest blended with normalized Reddit mentions
        reddit_norm = (c.reddit_mentions / max_reddit) if max_reddit else 0.0
        c.demand = 0.7 * c.trends_interest + 0.3 * reddit_norm

        # velocity: rising flag is the strong signal; reddit chatter nudges it
        c.velocity = (0.7 if c.trends_rising else 0.0) + 0.3 * min(1.0, reddit_norm * 2)

        # supply_gap: measured from Etsy if we have it, else archetype prior
        if c.etsy_listings >= 0:
            # fewer listings + weaker top comps => bigger gap
            volume_gap = 1.0 - min(1.0, c.etsy_listings / 25000.0)
            quality_gap = 1.0 - (c.etsy_top_quality if c.etsy_top_quality >= 0 else 0.5)
            c.supply_gap = 0.6 * volume_gap + 0.4 * quality_gap
        else:
            c.supply_gap = ARCHETYPES.get(c.archetype, 0.5)  # ESTIMATED

        # fit: domain authority weight
        c.fit = VERTICALS.get(c.vertical, {}).get("weight", 0.4)

        c.score = round(100 * (
            WEIGHTS["demand"]   * c.demand   +
            WEIGHTS["velocity"] * c.velocity +
            WEIGHTS["gap"]      * c.supply_gap +
            WEIGHTS["fit"]      * c.fit
        ), 1)

        c.title, c.keywords = _title_and_tags(c)
    return cands


def _title_and_tags(c: Candidate):
    niche = c.niche.title()
    arch = c.archetype.title()
    title = f"{niche} {arch}".strip()
    base = [c.niche, c.archetype, f"{c.niche} {c.archetype}", "excel template",
            "google sheets", "printable", "digital download"]
    return title, list(dict.fromkeys(base))[:13]   # Etsy allows 13 tags


# ----------------------------------------------------------------------------- #
#  Output
# ----------------------------------------------------------------------------- #
def write_outputs(cands, top, outdir):
    winners = [c for c in cands if c.ip_safe][:top]

    queue = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "weights": WEIGHTS,
        "count": len(winners),
        "items": [asdict(c) for c in winners],
    }
    qpath = os.path.join(outdir, "trend_queue.json")
    with open(qpath, "w") as f:
        json.dump(queue, f, indent=2)

    # catalog.generated.json -> shaped for forge_batch.py.
    # NOTE: field names mirror the documented catalog (niche + template pair).
    # If your real catalog.json uses different keys, remap here (one line each).
    catalog = [
        {
            "niche": c.niche,
            "template": c.archetype,
            "title": c.title,
            "tags": c.keywords,
            "trend_score": c.score,
        }
        for c in winners
    ]
    cpath = os.path.join(outdir, "catalog.generated.json")
    with open(cpath, "w") as f:
        json.dump(catalog, f, indent=2)

    return qpath, cpath, winners


def maybe_build(catalog_path, forge_dir):
    """Hand the generated catalog to the existing forge batch runner, if present."""
    batch = os.path.join(forge_dir, "forge_batch.py")
    if not os.path.exists(batch):
        _warn(f"forge_batch.py not found in {forge_dir} -> skipping build. "
              f"Queue + catalog are written; run your batch runner on catalog.generated.json.")
        return
    print(f"\n>> handing winners to the forge: {batch}")
    try:
        subprocess.run([sys.executable, batch, catalog_path], cwd=forge_dir, check=True)
    except subprocess.CalledProcessError as e:
        _warn(f"forge_batch exited {e.returncode}. Catalog is valid; inspect the build log.")


# ----------------------------------------------------------------------------- #
#  Offline mock  -  injects synthetic signals so the pipeline is provable here
# ----------------------------------------------------------------------------- #
def mock_signals(cands):
    import random
    random.seed(42)
    for c in cands:
        base = VERTICALS.get(c.vertical, {}).get("weight", 0.4)
        c.trends_interest = round(min(1.0, max(0.0, random.gauss(0.35 * base + 0.2, 0.18))), 3)
        c.trends_rising = random.random() < (0.18 + 0.25 * base)
        c.reddit_mentions = max(0, int(random.gauss(6 * base, 4)))


# ----------------------------------------------------------------------------- #
#  Plumbing
# ----------------------------------------------------------------------------- #
def _warn(msg):
    print(f"   [warn] {msg}", file=sys.stderr)


def make_session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    return s


def main():
    ap = argparse.ArgumentParser(description="SheetForge trend finder")
    ap.add_argument("--offline", action="store_true", help="mock signals, no network")
    ap.add_argument("--etsy", action="store_true", help="enable Etsy supply probe (brittle)")
    ap.add_argument("--ip-check", action="store_true", help="run Anthropic trademark screen")
    ap.add_argument("--build", action="store_true", help="run forge_batch.py on winners")
    ap.add_argument("--top", type=int, default=12, help="how many winners to keep")
    ap.add_argument("--limit", type=int, default=0, help="cap candidates (0 = all; live runs: set ~80)")
    ap.add_argument("--outdir", default=".", help="where to write json")
    ap.add_argument("--forge-dir", default=".", help="dir containing forge_batch.py")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    print(">> generating candidates")
    cands = seed_candidates()

    if args.offline:
        print(">> OFFLINE: injecting mock signals")
        mock_signals(cands)
    else:
        session = make_session()
        print(">> discovering live niches from Reddit")
        discovered = discover_from_reddit(session)
        # fold the strongest discovered phrases in as extra candidates
        for phrase, n in sorted(discovered.items(), key=lambda kv: -kv[1])[:25]:
            arch = next((a for a in ARCHETYPES if a in phrase), "tracker")
            cands.append(Candidate(niche=phrase, archetype=arch, vertical="_general",
                                   reddit_mentions=n))

        if args.limit:
            cands = sorted(cands, key=lambda c: -c.reddit_mentions)[: args.limit]

        print(f">> enriching {len(cands)} candidates with Google Trends "
              f"(this is the slow part; pytrends rate-limits)")
        gt = GoogleTrendsSource()
        for i, c in enumerate(cands, 1):
            gt.enrich(c)
            if i % 10 == 0:
                print(f"   trends {i}/{len(cands)}")

        if args.etsy:
            print(">> probing Etsy supply (brittle, opt-in)")
            etsy = EtsySource(session)
            for c in cands:
                etsy.enrich(c)

    max_reddit = max((c.reddit_mentions for c in cands), default=0)
    print(">> scoring")
    score_all(cands, max_reddit)
    cands.sort(key=lambda c: -c.score)

    if args.ip_check:
        print(">> IP / trademark screen (top 40)")
        ip_check(cands[:40])

    qpath, cpath, winners = write_outputs(cands, args.top, args.outdir)

    print("\n================  TOP WINNERS  ================")
    measured = any(c.etsy_listings >= 0 for c in winners)
    for i, c in enumerate(winners, 1):
        gap_tag = "" if measured else " (gap est.)"
        rise = " ^rising" if c.trends_rising else ""
        flag = "" if c.ip_safe else "  [IP RISK]"
        print(f"{i:>2}. {c.score:>5}  {c.title:<38} "
              f"[{c.vertical}]{rise}{gap_tag}{flag}")
    if not measured:
        print("\nNOTE: supply_gap is ESTIMATED from archetype priors (Etsy source off).")
        print("      These are rising-DEMAND picks. Run with --etsy to verify weak supply.")

    print(f"\nwrote: {qpath}")
    print(f"wrote: {cpath}")

    if args.build:
        maybe_build(cpath, args.forge_dir)


if __name__ == "__main__":
    main()
