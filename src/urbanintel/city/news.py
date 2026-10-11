from __future__ import annotations

import email.utils
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

import numpy as np
import requests

from ..aoi import AOI, AnalysisFrame
from .catalog import NOMINATIM, USER_AGENT

PROMPT_VERSION = "news-extract-v5"
MAX_AGE_MONTHS = 24
PER_QUERY = 8
MAX_ARTICLES = 140

# Topic queries are neutral nouns; the second list deliberately asks for setbacks so retrieval is not one-sided
TOPICS_DEVELOPMENT = ["metro rail", "airport", "flyover", "expressway OR ring road", "railway station",
                      "electric buses", "IT park OR tech park", "industrial park OR manufacturing plant",
                      "data centre", "mall OR commercial complex", "housing project OR township",
                      "water supply OR sewage project", "hospital OR university campus"]
TOPICS_SETBACK = ["project delayed", "project stalled OR scrapped", "factory closure OR layoffs",
                  "flooding OR waterlogging", "water shortage", "construction ban"]

EVENT_TYPES = ["metro_rail", "suburban_rail_or_station", "airport", "expressway_or_ring_road",
               "flyover_or_road_widening", "bus_or_electric_transit", "it_park_or_offices",
               "industrial_or_manufacturing", "data_centre", "retail_or_commercial", "housing_or_township",
               "utilities_water_power_sewage", "health_or_education_campus", "flood_or_disaster",
               "business_closure_or_layoffs", "environmental_or_construction_restriction",
               "water_or_power_shortage", "other"]
STATUSES = ["proposed", "approved", "funded", "under_construction", "completed", "operational",
            "delayed", "stalled", "cancelled", "unclear"]
BASES = ["reported_fact", "official_decision", "announcement_or_plan", "political_claim_or_promise",
         "opinion"]
SCOPES = ["locality", "district", "citywide", "regional"]

# Fixed scoring table: magnitude of expected effect on local growth (0-1) and footprint radius in km
EFFECT = {"metro_rail": (0.9, 2.0), "suburban_rail_or_station": (0.6, 2.0), "airport": (1.0, 10.0),
          "expressway_or_ring_road": (0.8, 3.0), "flyover_or_road_widening": (0.4, 1.0),
          "bus_or_electric_transit": (0.3, 1.5), "it_park_or_offices": (0.8, 3.0),
          "industrial_or_manufacturing": (0.8, 4.0), "data_centre": (0.6, 2.0),
          "retail_or_commercial": (0.5, 1.5), "housing_or_township": (0.4, 2.0),
          "utilities_water_power_sewage": (0.5, 3.0), "health_or_education_campus": (0.4, 2.0),
          "flood_or_disaster": (0.7, 2.0), "business_closure_or_layoffs": (0.7, 3.0),
          "environmental_or_construction_restriction": (0.5, 5.0),
          "water_or_power_shortage": (0.5, 5.0), "other": (0.2, 1.5)}
STATUS_WEIGHT = {"proposed": 0.25, "approved": 0.5, "funded": 0.6, "under_construction": 0.8,
                 "completed": 1.0, "operational": 1.0, "delayed": 0.5, "stalled": 0.6, "cancelled": 0.8,
                 "unclear": 0.3}
BASIS_WEIGHT = {"reported_fact": 1.0, "official_decision": 1.0, "announcement_or_plan": 0.6,
                "opinion": 0.2, "political_claim_or_promise": 0.0}
SETBACK_STATUS = {"delayed", "stalled", "cancelled"}
HALF_LIFE_MONTHS = 12.0
ALIASES = {"bengaluru": ["Bangalore"], "mumbai": ["Bombay"], "gurugram": ["Gurgaon"],
           "kolkata": ["Calcutta"], "chennai": ["Madras"], "varanasi": ["Banaras", "Kashi"],
           "kochi": ["Cochin"], "visakhapatnam": ["Vizag"], "delhi": ["New Delhi"],
           "pune": ["Poona"], "thiruvananthapuram": ["Trivandrum"], "mysuru": ["Mysore"]}
# Region names that cover the whole study area, so a story placed there is citywide, not a point
REGIONS = {"delhi": ["NCR", "Delhi NCR", "Delhi-NCR", "National Capital Region"],
           "mumbai": ["MMR", "Mumbai Metropolitan Region"], "bengaluru": ["Bengaluru Urban"],
           "kolkata": ["KMA", "Kolkata Metropolitan Area"], "hyderabad": ["HMDA"]}
SCALE = 1.5
CITY_SCALE = 3.0
# A label must be supported by the text: a setback needs a setback word, progress needs a development word
NEG_CUES = re.compile(r"delay|stall|halt|scrap|cancel|postpon|stuck|shelv|closure|clos(e|es|ed|ing) down|"
                      r"shut|layoff|lay off|job cut|flood|waterlog|collaps|ban|shortage|crisis|damag|"
                      r"fire|accident|protest|dispute|slow|behind schedule|miss(ed|es) (the )?deadline|"
                      r"exit|pull(s|ed)? out|withdraw|loss|decline|fall|drop", re.IGNORECASE)
POS_CUES = re.compile(r"open|launch|inaugurat|complet|approv|sanction|clear|start|begin|began|build|"
                      r"construct|invest|expan|plan|propos|tender|award|commission|foundation|operational|"
                      r"new |set up|sets up|upgrad|add|introduc|unveil|allot|fund|develop|work on|"
                      r"progress|connect|link|extend|acquir|hire|hiring|jobs", re.IGNORECASE)

# Names are used only to redact them from outputs and for the counterfactual neutrality test
PARTIES = ["Bharatiya Janata Party", "BJP", "Indian National Congress", "Congress", "INC",
           "Aam Aadmi Party", "AAP", "Samajwadi Party", "Bahujan Samaj Party", "BSP",
           "Trinamool Congress", "TMC", "AITC", "DMK", "AIADMK", "CPI(M)", "CPI", "Shiv Sena",
           "Nationalist Congress Party", "NCP", "Janata Dal (United)", "JD(U)", "JD(S)",
           "Rashtriya Janata Dal", "RJD", "Telugu Desam Party", "TDP", "YSR Congress", "YSRCP",
           "Bharat Rashtra Samithi", "BRS", "Biju Janata Dal", "BJD", "AIMIM", "JMM", "MNS"]
ROLES = r"\b(chief minister|deputy chief minister|cabinet minister|union minister|minister|MLA|MP|CM|PM|prime minister|mayor|opposition leader)\b"
PARTY_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(p) for p in sorted(PARTIES, key=len, reverse=True)) + r")(?![A-Za-z])")
ROLE_RE = re.compile(ROLES, re.IGNORECASE)

SYSTEM = (
    "You extract facts about urban development from one news headline and its snippet, for a "
    "land-use research model. Rules: (1) Report only what the text states about physical or "
    "economic developments: transport, buildings, industry, utilities, closures, disasters or "
    "restrictions. (2) Be strictly neutral. Never praise or blame any government, party, person, "
    "community or ideology, and never name a political party, politician or office holder in any "
    "field. (3) Election promises, manifestos, rally speeches and claims by politicians are "
    "basis=political_claim_or_promise, whoever makes them. (4) A government or agency approval, "
    "sanction, tender award or budget allocation is basis=official_decision, whoever is in power. "
    "(5) Apply exactly the same rules to good and bad news. (6) If the text reports a concrete "
    "development (an approval, a start, a delay, a stoppage, an opening, a closure), it is a "
    "development event even when the story is framed as a political dispute: extract the "
    "development and ignore the politics. Only when there is no concrete development at all "
    "(pure politics, crime, sport, entertainment, opinion) set is_development_event=false. A one-off "
    "incident (an accident, a fire in one building, a crime, a sports or cultural event, one day of "
    "traffic or rain, a closure for routine testing) is not a development unless the text says it "
    "permanently changes infrastructure, services, industry or land use; the same rule applies to good "
    "and bad news. (7) location is the locality, road or area named in the text, or "
    "an empty string if none is named. (8) summary is at most 25 neutral words describing the "
    "development itself. (9) expected_completion_year is 0 when the text gives none. Event types: "
    "metro_rail = metro or light rail; suburban_rail_or_station = suburban trains, railway stations; "
    "airport; expressway_or_ring_road = expressways, ring roads, highways; flyover_or_road_widening = "
    "flyovers, overpasses, underpasses, elevated roads, road widening, bridges; bus_or_electric_transit "
    "= buses, electric buses, bus depots, charging stations; it_park_or_offices = IT parks, office "
    "campuses; industrial_or_manufacturing = factories, industrial areas; data_centre; "
    "retail_or_commercial = malls, markets, commercial complexes, hotels; housing_or_township; "
    "utilities_water_power_sewage; health_or_education_campus; flood_or_disaster; "
    "business_closure_or_layoffs; environmental_or_construction_restriction = construction bans, "
    "pollution curbs; water_or_power_shortage; other.")

SCHEMA = {
    "type": "object",
    "properties": {
        "is_development_event": {"type": "boolean"},
        "event_type": {"type": "string", "enum": EVENT_TYPES},
        "direction": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "status": {"type": "string", "enum": STATUSES},
        "basis": {"type": "string", "enum": BASES},
        "scope": {"type": "string", "enum": SCOPES},
        "location": {"type": "string"},
        "expected_completion_year": {"type": "integer"},
        "summary": {"type": "string"},
    },
    "required": ["is_development_event", "event_type", "direction", "status", "basis", "scope",
                 "location", "expected_completion_year", "summary"],
    "additionalProperties": False,
}


@dataclass
class Article:
    title: str
    source: str
    url: str
    published: str
    snippet: str
    query: str
    retrieval: str

    def age_months(self, now: datetime) -> float:
        try:
            d = datetime.fromisoformat(self.published)
        except ValueError:
            return MAX_AGE_MONTHS
        return max(0.0, (now - d).days / 30.44)


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def names(city: str) -> list[str]:
    return [city] + ALIASES.get(city.lower(), [])


def google_news(city: str, query: str, fetch: Callable[[str], bytes]) -> list[Article]:
    import feedparser

    who = " OR ".join(f'"{n}"' for n in names(city))
    q = quote_plus(f"({who}) {query}")
    body = fetch(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en")
    feed = feedparser.parse(body)
    out = []
    for e in feed.entries:
        try:
            d = email.utils.parsedate_to_datetime(e.get("published", "")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        title = e.get("title", "")
        src = e.get("source", {}).get("title", "") if isinstance(e.get("source"), dict) else ""
        if src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]
        out.append(Article(title=title.strip(), source=src, url=e.get("link", ""),
                           published=d.isoformat(), snippet=_strip_html(e.get("summary", ""))[:400],
                           query=query, retrieval="google_news_rss"))
    return out


def gdelt(city: str, query: str, fetch: Callable[[str], bytes]) -> list[Article]:
    who = " OR ".join(f'"{n}"' for n in names(city))
    q = quote_plus(f"({who}) ({query}) sourcecountry:india sourcelang:english")
    body = fetch(f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json"
                 f"&maxrecords=50&timespan=3months&sort=datedesc")
    try:
        arts = json.loads(body).get("articles", [])
    except json.JSONDecodeError:
        return []
    out = []
    for a in arts:
        try:
            d = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        out.append(Article(title=a.get("title", "").strip(), source=a.get("domain", ""),
                           url=a.get("url", ""), published=d.isoformat(), snippet="",
                           query=query, retrieval="gdelt_doc_2"))
    return out


def _norm(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", t.lower())) - {"the", "a", "an", "of", "in", "to", "for", "and", "on", "at", "is", "with", "by"}


def dedupe(arts: list[Article]) -> list[Article]:
    kept: list[Article] = []
    toks: list[set[str]] = []
    for a in sorted(arts, key=lambda x: x.published, reverse=True):
        t = _norm(a.title)
        if not t or any(len(t & k) / len(t | k) >= 0.7 for k in toks):
            continue
        kept.append(a)
        toks.append(t)
    return kept


def collect(city: str, fetch: Callable[[str], bytes], *, now: datetime,
            on_step: Callable[[int, int, str], None] | None = None) -> dict:
    jobs = ([("google", q, "development") for q in TOPICS_DEVELOPMENT]
            + [("google", q, "setback") for q in TOPICS_SETBACK]
            + [("gdelt", "infrastructure OR metro OR airport OR expressway", "development"),
               ("gdelt", "delayed OR stalled OR closure OR flooding", "setback")])
    found: list[Article] = []
    per_query: dict[str, int] = {}
    errors = []
    for i, (src, q, side) in enumerate(jobs, start=1):
        got = []
        # GDELT allows one request every five seconds per address
        for attempt in range(3 if src == "gdelt" else 1):
            try:
                if src == "gdelt":
                    time.sleep(6 + 10 * attempt)
                got = google_news(city, q, fetch) if src == "google" else gdelt(city, q, fetch)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == (2 if src == "gdelt" else 0):
                    errors.append(f"{src} '{q}': {str(exc)[:120]}")
        keys = [n.lower() for n in names(city)]
        got = [a for a in got if a.age_months(now) <= MAX_AGE_MONTHS
               and any(k in (a.title + " " + a.snippet).lower() for k in keys)]
        got = sorted(got, key=lambda a: a.published, reverse=True)[:PER_QUERY]
        per_query[f"{side}: {q}"] = len(got)
        found += got
        if on_step:
            on_step(i, len(jobs), f"{src}: {q} ({len(got)} recent articles)")
    unique = dedupe(found)[:MAX_ARTICLES]
    return {"articles": unique, "per_query": per_query, "errors": errors,
            "retrieved": len(found), "unique": len(unique),
            "balance": {"development_queries": len(TOPICS_DEVELOPMENT) + 1,
                        "setback_queries": len(TOPICS_SETBACK) + 1}}


def redact(text: str) -> tuple[str, bool]:
    new = PARTY_RE.sub("[party]", text)
    return new, new != text


def mentions_politics(a: Article) -> bool:
    t = f"{a.title} {a.snippet}"
    return bool(PARTY_RE.search(t) or ROLE_RE.search(t))


def neutralise(text: str) -> str:
    return ROLE_RE.sub("an official", PARTY_RE.sub("a political party", text))


def prompt_for(a: Article, city: str) -> str:
    return (f"City: {city}\nPublished: {a.published[:10]}\nSource: {a.source}\n"
            f"Headline: {a.title}\nSnippet: {a.snippet or '(none)'}")


def extract_all(arts: list[Article], city: str, extractor, *, workers: int = 4,
                on_step: Callable[[int, int, str], None] | None = None,
                cache_path: Path | None = None) -> list[dict]:
    out: list[dict | None] = [None] * len(arts)
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path and cache_path.exists() else {}
    tag = f"{PROMPT_VERSION}|{extractor.name}:{getattr(extractor, 'model', '')}"

    def key(a: Article) -> str:
        return hashlib.sha1(f"{tag}|{a.title}|{a.snippet}".encode("utf-8")).hexdigest()

    def one(i: int):
        a = arts[i]
        # The same article, prompt and model give the same answer, so a refresh only reads what is new
        if key(a) in cache:
            return i, cache[key(a)], None
        try:
            res = extractor.extract(SYSTEM, prompt_for(a, city), SCHEMA)
            cache[key(a)] = res
            return i, res, None
        except Exception as exc:  # noqa: BLE001
            return i, None, f"{type(exc).__name__}: {str(exc)[:160]}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed([pool.submit(one, i) for i in range(len(arts))]):
            i, res, err = fut.result()
            out[i] = {"article": arts[i].__dict__, "extraction": res, "error": err}
            done += 1
            if on_step:
                on_step(done, len(arts), arts[i].title[:90])
    if cache_path is not None:
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return out


AUDIT_KEYS = ("is_development_event", "event_type", "direction", "status", "basis")


def same_score(x: dict, y: dict) -> bool:
    a0, a1 = impact(x, 0), impact(y, 0)
    if a0 == a1 == 0:
        return True
    return bool(np.sign(a0) == np.sign(a1) and abs(a0 - a1) <= 0.25 * max(abs(a0), abs(a1)))


def counterfactual_audit(rows: list[dict], city: str, extractor, *, limit: int = 12) -> dict:
    # Re-reading unchanged as well as name-swapped separates a swap effect from run-to-run variation
    sample = [r for r in rows if r["extraction"] and mentions_politics(Article(**r["article"]))][:limit]
    cases = []
    for r in sample:
        a = Article(**r["article"])
        b = Article(**{**a.__dict__, "title": neutralise(a.title), "snippet": neutralise(a.snippet)})
        try:
            # Both re-reads pass the same evidence check as the original, so like is compared with like
            again = check_evidence(extractor.extract(SYSTEM, prompt_for(a, city), SCHEMA), a)[0]
            swap = check_evidence(extractor.extract(SYSTEM, prompt_for(b, city), SCHEMA), b)[0]
        except Exception:  # noqa: BLE001
            continue
        orig = r["extraction"]
        cases.append({"title": redact(a.title)[0],
                      "rerun_identical": all(again.get(k) == orig.get(k) for k in AUDIT_KEYS),
                      "swap_identical": all(swap.get(k) == orig.get(k) for k in AUDIT_KEYS),
                      "rerun_same_score": same_score(orig, again), "swap_same_score": same_score(orig, swap),
                      "swap_changed": [k for k in AUDIT_KEYS if swap.get(k) != orig.get(k)]})
    n = len(cases)

    def share(key):
        return round(sum(c[key] for c in cases) / n, 3) if n else None

    return {"tested": n, "identical": sum(c["swap_identical"] for c in cases),
            "invariance": share("swap_identical"), "score_invariance": share("swap_same_score"),
            "rerun_identical": share("rerun_identical"), "rerun_same_score": share("rerun_same_score"),
            "method": ("each article that names a party or an office holder is read twice more: unchanged, "
                       "and with those names replaced by neutral placeholders. A swap effect larger than "
                       "the unchanged re-read's variation would indicate bias."),
            "cases": cases}


def impact(ext: dict, age_months: float) -> float:
    if not ext or not ext.get("is_development_event"):
        return 0.0
    mag, _ = EFFECT.get(ext["event_type"], EFFECT["other"])
    if ext["status"] in SETBACK_STATUS:
        sign = -1.0
    else:
        sign = {"positive": 1.0, "negative": -1.0}.get(ext["direction"], 0.0)
    recency = 0.5 ** (age_months / HALF_LIFE_MONTHS)
    return sign * mag * STATUS_WEIGHT[ext["status"]] * BASIS_WEIGHT[ext["basis"]] * recency


TEMPORARY = re.compile(r"\btemporar|\b(?:till|until) (?:tomorrow|today|tonight)\b|"
                       r"\bfor (?:the|a|one|two|three|\d+) (?:day|days|hours?|night|weekend)\b", re.IGNORECASE)


def check_evidence(ext: dict | None, a: Article) -> tuple[dict | None, str | None]:
    # The same test for good and bad labels: one the text gives no cue for is set to neutral
    if not ext or not ext.get("is_development_event"):
        return ext, None
    text = f"{a.title} {a.snippet}"
    out = dict(ext)
    # A temporary change, good or bad, is not a development
    if TEMPORARY.search(text):
        out.update(is_development_event=False)
        return out, "temporary change, not a development"
    if out["status"] in SETBACK_STATUS and not NEG_CUES.search(text):
        out.update(status="unclear", direction="neutral")
        return out, "setback status without a setback word"
    if out["direction"] == "negative" and not NEG_CUES.search(text):
        out["direction"] = "neutral"
        return out, "negative direction without a setback word"
    if out["direction"] == "positive" and not POS_CUES.search(text):
        out["direction"] = "neutral"
        return out, "positive direction without a development word"
    return out, None


def cluster_events(rows: list[dict], now: datetime, city: str = "") -> list[dict]:
    events: dict[tuple, dict] = {}
    for r in rows:
        ext = r["extraction"]
        if not ext or not ext.get("is_development_event"):
            continue
        a = Article(**r["article"])
        loc = re.sub(r"[^a-z0-9]+", " ", ext["location"].lower()).strip()
        # A location that only names the city is the whole city, not a point at its centre
        whole = [re.escape(n.lower()) for n in names(city) + REGIONS.get(city.lower(), [])]
        if city and re.sub(r"\b(" + "|".join(whole) + r"|city|india)\b", "", loc).strip(" ,-") == "":
            loc = ""
            ext = {**ext, "location": "", "scope": "citywide"}
        group = "setback" if ext["status"] in SETBACK_STATUS else "progress"
        key = (ext["event_type"], loc, group)
        e = events.setdefault(key, {"event_type": ext["event_type"], "location": ext["location"].strip(),
                                    "scope": ext["scope"], "articles": [], "sources": set(),
                                    "best": 0.0, "status": ext["status"], "basis": ext["basis"],
                                    "direction": ext["direction"], "summary": ext["summary"],
                                    "expected_completion_year": ext["expected_completion_year"]})
        v = impact(ext, a.age_months(now))
        e["articles"].append({"title": redact(a.title)[0], "source": a.source, "url": a.url,
                              "published": a.published[:10], "impact": round(v, 4)})
        e["sources"].add(a.source or (a.url.split("/")[2] if a.url.count("/") >= 2 else "unknown"))
        if abs(v) > abs(e["best"]):
            e.update(best=v, status=ext["status"], basis=ext["basis"], direction=ext["direction"],
                     summary=ext["summary"], scope=ext["scope"])
    out = []
    for e in events.values():
        n = len(e["sources"])
        corroboration = min(1.0, 0.5 + 0.25 * n)
        summary, flagged = redact(e["summary"])
        summary = ROLE_RE.sub("officials", summary)
        out.append({**{k: v for k, v in e.items() if k not in ("sources", "best")},
                    "summary": summary, "summary_redacted": flagged, "n_sources": n,
                    "corroboration": corroboration, "impact": round(e["best"] * corroboration, 4)})
    return sorted(out, key=lambda x: -abs(x["impact"]))


PLACE_CATEGORIES = {"place", "boundary"}
SPLIT = re.compile(r"\s*(?:-|\u2013|,|/|\bto\b|\band\b)\s*")
ELSEWHERE = "elsewhere"


def _nominatim(params: dict) -> dict | None:
    try:
        r = requests.get(f"{NOMINATIM}/search", headers={"User-Agent": USER_AGENT}, timeout=30,
                         params={"format": "jsonv2", "limit": 1, "countrycodes": "in", **params})
        time.sleep(1.1)
        return r.json()[0] if r.ok and r.json() else None
    except (requests.RequestException, ValueError, IndexError):
        return None


def _geocode_one(place: str, aoi: AOI, cache: dict) -> tuple[float, float, str] | None:
    key = "v2:" + place.lower().strip()
    if key == "v2:":
        return None
    if key not in cache:
        lon0, lat0, lon1, lat1 = aoi.bbox_ll
        hit = _nominatim({"q": f"{place}, {aoi.name}", "viewbox": f"{lon0},{lat1},{lon1},{lat0}", "bounded": 1})
        cache[key] = [float(hit["lon"]), float(hit["lat"]), hit.get("category", "")] if hit else None
    return tuple(cache[key]) if cache[key] else None


def _elsewhere(place: str, aoi: AOI, cache: dict) -> bool:
    # A state, district or city outside the study area ("Odisha", "Hyderabad") is another place,
    # even when a building inside the area carries its name
    key = "away2:" + place.lower().strip()
    if key not in cache:
        hit = _nominatim({"q": place, "featureType": "settlement"})
        lon0, lat0, lon1, lat1 = aoi.bbox_ll
        cache[key] = bool(hit and int(hit.get("place_rank", 30)) <= 16
                          and not (lon0 <= float(hit["lon"]) <= lon1 and lat0 <= float(hit["lat"]) <= lat1))
    return cache[key]


def geocode(place: str, aoi: AOI, cache: dict) -> tuple[float, float] | str | None:
    # A point; None when the place cannot be found (the event then counts citywide);
    # or ELSEWHERE when every place it names lies outside the study area
    city = {n.lower() for n in names(aoi.name) + REGIONS.get(aoi.name.lower(), [])}
    parts = [p.strip() for p in SPLIT.split(place)[:3] if len(p.strip()) >= 3]
    named = [p for p in parts if p.lower() not in city]
    whole = _geocode_one(place, aoi, cache)
    if whole is not None and whole[2] in PLACE_CATEGORIES:
        return whole[:2]
    if named and all(_elsewhere(p, aoi, cache) for p in named):
        return ELSEWHERE if len(named) == len(parts) else None
    if whole is not None:
        return whole[:2]
    # "Kalena Agrahara-Tavarekere" or "Sector 5, Noida": try each named place on its own
    for p in named:
        if not _elsewhere(p, aoi, cache):
            pt = _geocode_one(p, aoi, cache)
            if pt is not None:
                return pt[:2]
    return None


def zone_index(events: list[dict], aoi: AOI, coarse: AnalysisFrame,
               cache: dict) -> tuple[np.ndarray, float, list[dict]]:
    # Located events say where; citywide ones only say how much, so they form a separate city figure
    xs, ys = coarse.xy_centres()
    X, Y = np.meshgrid(xs, ys)
    total = np.zeros(coarse.shape, dtype="float64")
    city_total = 0.0
    placed = []
    for e in events:
        if e["impact"] == 0:
            continue
        _, radius = EFFECT.get(e["event_type"], EFFECT["other"])
        pt = None if e["scope"] == "citywide" else geocode(e["location"], aoi, cache)
        if pt == ELSEWHERE:
            # Kept for the record but scores nothing: the story is about another place
            e["placed"] = ELSEWHERE
        elif pt is None:
            city_total += e["impact"]
            e["placed"] = "citywide"
        else:
            x, y = aoi.to_metres(*pt)
            d = np.hypot(X - x, Y - y) / 1000.0
            total += e["impact"] * np.exp(-(d / radius) ** 2)
            e.update(placed="located", lon=pt[0], lat=pt[1], radius_km=radius)
        placed.append(e)
    return np.tanh(total / SCALE).astype("float32"), float(np.tanh(city_total / CITY_SCALE)), placed


CACHE_HOURS = 24


def fetch_stage(city: str, fetch: Callable[[str], bytes], *, on_step=None,
                cache_path: Path | None = None) -> dict:
    # Articles fetched in the last day are reused, so re-reading the news costs no download
    now = datetime.now(timezone.utc)
    if cache_path is not None and cache_path.exists():
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        when = datetime.fromisoformat(saved["fetched"])
        if (now - when).total_seconds() < CACHE_HOURS * 3600:
            got = {**saved, "articles": [Article(**a) for a in saved["articles"]], "now": when,
                   "reused_from": saved["fetched"]}
            if on_step:
                on_step(1, 1, f"reused {got['unique']} articles fetched at {saved['fetched'][:16]} UTC")
            return got
    got = collect(city, fetch, now=now, on_step=on_step)
    got["now"] = now
    if cache_path is not None:
        cache_path.write_text(json.dumps({**{k: v for k, v in got.items() if k not in ("articles", "now")},
                                          "fetched": now.isoformat(),
                                          "articles": [a.__dict__ for a in got["articles"]]}),
                              encoding="utf-8")
    return got


def process_stage(city: str, aoi: AOI, coarse: AnalysisFrame, extractor, got: dict, *,
                  cache_path: Path, on_step=None, extraction_cache: Path | None = None) -> tuple[dict, np.ndarray]:
    now = got["now"]
    rows = extract_all(got["articles"], city, extractor, workers=getattr(extractor, "workers", 4),
                       on_step=on_step, cache_path=extraction_cache)
    overrides = []
    for r in rows:
        r["raw_extraction"] = r["extraction"]
        r["extraction"], why = check_evidence(r["extraction"], Article(**r["article"]))
        if why:
            overrides.append({"title": redact(r["article"]["title"])[0], "reason": why})
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    events = cluster_events(rows, now, city)
    index, city_index, placed = zone_index(events, aoi, coarse, cache)
    cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    audit = counterfactual_audit(rows, city, extractor)
    ok = [r for r in rows if r["extraction"]]
    dev = [r for r in ok if r["extraction"]["is_development_event"]]
    basis_counts: dict[str, int] = {}
    srcs: dict[str, int] = {}
    for r in dev:
        basis_counts[r["extraction"]["basis"]] = basis_counts.get(r["extraction"]["basis"], 0) + 1
        s = r["article"]["source"] or "unknown"
        srcs[s] = srcs.get(s, 0) + 1
    result = {
        "prompt_version": PROMPT_VERSION,
        "extractor": f"{extractor.name}:{getattr(extractor, 'model', '')}",
        "retrieved": got["retrieved"], "unique_articles": got["unique"], "per_query": got["per_query"],
        "articles_fetched": got["now"].isoformat(), "articles_reused": "reused_from" in got,
        "fetch_errors": got["errors"], "extracted": len(ok),
        "extraction_errors": [r["error"] for r in rows if r["error"]][:10],
        "development_articles": len(dev), "events": placed,
        "positive_events": sum(1 for e in placed if e["impact"] > 0 and e.get("placed") != ELSEWHERE),
        "negative_events": sum(1 for e in placed if e["impact"] < 0 and e.get("placed") != ELSEWHERE),
        "basis_counts": basis_counts, "top_sources": sorted(srcs.items(), key=lambda kv: -kv[1])[:8],
        "max_source_share": round(max(srcs.values()) / len(dev), 3) if dev else None,
        "audit": audit, "retrieval_balance": got["balance"],
        "evidence_overrides": overrides, "city_news_index": round(city_index, 3),
        "located_events": sum(1 for e in placed if e.get("placed") == "located"),
        "elsewhere_events": sum(1 for e in placed if e.get("placed") == ELSEWHERE),
        "scoring": {"effect": EFFECT, "status_weight": STATUS_WEIGHT, "basis_weight": BASIS_WEIGHT,
                    "half_life_months": HALF_LIFE_MONTHS, "scale": SCALE,
                    "corroboration": "min(1, 0.5 + 0.25 x distinct sources)",
                    "zone_index": "tanh(sum over located events of impact x exp(-(d/r)^2) / 1.5)",
                    "city_news_index": "tanh(sum of citywide and unlocated event impacts / 3)",
                    "evidence_check": ("a setback status or negative direction needs a setback word in the "
                                       "headline or snippet, a positive direction needs a development word; "
                                       "otherwise the label is set to neutral; a change the text calls "
                                       "temporary or one-day is not a development"),
                    "elsewhere": ("a story whose places are all a state, district or city outside the "
                                  "study area is kept for the record and scores nothing")},
        "articles": [{"title": redact(r["article"]["title"])[0], "source": r["article"]["source"],
                      "url": r["article"]["url"], "published": r["article"]["published"][:10],
                      "retrieval": r["article"]["retrieval"], "query": r["article"]["query"],
                      "extraction": r["extraction"], "error": r["error"],
                      "impact": (round(impact(r["extraction"], Article(**r["article"]).age_months(now)), 4)
                                 if r["extraction"] else None)} for r in rows],
    }
    return result, index
