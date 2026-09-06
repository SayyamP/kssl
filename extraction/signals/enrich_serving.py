"""Fill the REMAINING serving tables from extracted Layer A+B data -- the enrichment step.

    python enrich_serving.py                    # run every step, in order
    python enrich_serving.py --only tenders
    python enrich_serving.py --demo             # per-step parser asserts, no DB, no LLM
    python enrich_serving.py --limit 10         # cap LLM calls per step (smoke run)

serving_fill.py turned documents into signal cards; this module fills the rest of the
dashboard -- competitors, partnerships, geo footprint, tenders, innovations, sources,
matchups -- so the Partnerships / Geo / Positioning / Tender / Innovation panes show
pipeline data. Same honesty contract:

  * every value traces to the extracted corpus (propositions with evidence quotes) or is
    mechanically computed; a field the corpus doesn't state stays NULL, never ''.
    Grounding is checked, not assumed: short fields go through _in_hay (a proper noun /
    designator the statements carry, or two content tokens), free prose goes through
    ground_text sentence by sentence, and a sentence naming something the statements
    never mention is dropped -- if nothing survives, the row is refused.
  * LLM replies are validated field by field; a malformed reply is a counted refusal,
    never a half row. Closed vocabularies (KSSL_CATS, techCats ids, rel codes) are
    enforced by refusing the row, not by coercing it.
  * recency (serving_fill.article_date + is_recent_ym) gates time-stamped CLAIMS
    (tenders, competitor update lines); company PROFILES draw on the whole relevant
    corpus but always carry provenance (srcs/src/sources/url = the document url).
  * idempotent: each step deletes its own origin='pipeline' subset first, then inserts
    fresh. origin='reference' rows are never touched.

Known schema deviations from the natural keys one would pick (reported, not hidden):
  * serving.tender.id and serving.matchup.matchup_id are INTEGER PKs, so 'plt_<doc>'
    style keys are impossible; pipeline tenders use 5000+n and matchups 9000+n (n by
    sorted document id -- deterministic for a given corpus), with the source document
    url carried in srcs.
  * serving.geo_comp PK is (id); the archive holds a reference row id='KSSL', but that
    was never a collision -- reference ids are uppercase codes and pipeline ids are
    lowercase slugs, and the two origins are served through different views. The client
    now gets its own geo_comp row (id=slug, isBf=true) and its presence rows are keyed
    by the SAME comp_id, so geoData and geoComps join.
  * PKs shared across origins (innovation (area,ord), geo_presence (comp,country,ord),
    source_registry (ord), company_source (company,ord), tender/matchup ids) get the
    pipeline range offset ORD0=1000 so reference rows are never collided with.
"""
import argparse
import json
import os
import re
import stage_timer
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from serving_fill import (  # noqa: E402  (helpers are REUSED, not duplicated)
    DSN, MODEL, article_date, ask, category_conflict, clip, country_names,
    date_label, esc, is_dup,
    is_fetch_fallback, is_listing, is_recent_ym, is_relevant, kssl_cats, load_terms,
    off_portfolio, parse_date, recent_cutoff, suppressed_ids, title_tokens,
)
import portfolio  # noqa: E402  (the client's product list + the tag join, shared)
from llmapi import client as llm_client  # noqa: E402  (every model call goes through the API)
# `publishable` (the tier-graded source bar) lives in the ENGINE's source_tiers; the pipeline's
# own source_tiers.py is a different module (tier_of/LABEL), so load the engine copy by path
# rather than colliding the module name on sys.path.
import importlib.util as _ilu  # noqa: E402
_st_spec = _ilu.spec_from_file_location(
    "engine_source_tiers", str(HERE.parent / "engine" / "source_tiers.py"))
_st = _ilu.module_from_spec(_st_spec); _st_spec.loader.exec_module(_st)  # type: ignore
publishable = _st.publishable  # noqa: E402  (ONE source bar, shared)
import roster  # noqa: E402  (the curated roster, shared with serving_fill)
from aliases import (  # noqa: E402  (ONE identity layer, shared with serving_fill)
    CLIENT_MARKS, canonical as canon_name, client_led, fold as fold_name,
    has_proper_name,
    is_client, is_description,
    is_force, is_one_org, merge as alias_merge,
)

REF = json.loads((HERE.parent / "reference_dataset.json").read_text(encoding="utf-8"))
ORD0 = 1000          # pipeline ord offset -- reference rows own the low range
REV_ORD0 = 2000      # revive_partners owns 2000+; neither writer deletes the other's
TENDER_ID0 = 5000    # integer PK range for pipeline tenders
MATCHUP_ID0 = 9000   # integer PK range for pipeline matchups


# How many profile calls may be in flight at once. The serving node publishes six slots
# (num_parallel) and this step was using exactly one of them: a rebuild walked ~200
# companies single file while the card sat at 0/6 running. The calls are independent of
# each other, so the only reason to serialise them was that nobody had unserialised them.
# Default six to match the node; the gateway caps each node at num_parallel anyway, so a
# larger number queues rather than helps.
# HOW MANY MODEL CALLS THIS PASS HAS IN FLIGHT AT ONCE, and it comes from the
# environment so there is ONE number for the whole stack. The serving node
# (DESKTOP-J9F0LTF, qwen2.5:14b) offers six parallel slots; a step that calls the model
# one at a time uses one of them and leaves five idle -- measured on the farm dashboard,
# the pinned 14b sat at 2/6 running at 7.6 tok/s while every 7b node beside it ran
# 6/6 at 220 tok/s.
#
# NO STEP PICKS ITS OWN WIDTH. extraction/docker-compose.yml sets KSSL_ENRICH_WORKERS
# for the enrich service; this default exists only so a hand-run outside compose behaves
# the same way, and the two must not drift.
ENRICH_WORKERS = max(1, int(os.environ.get("KSSL_ENRICH_WORKERS") or 6))


def _ask(prompt, npredict=600, timeout=None):
    """serving_fill.ask with a configurable budget: profile/tender JSON replies do not
    fit the card step's 300-token cap, and a truncated JSON is a lost row.

    Goes through the LLM API like every other model call. The budget still lives here
    because it is a property of THIS step's output, not of the node that serves it --
    the node decides how long that many tokens may take, which is why the timeout is no
    longer computed from a hardcoded GPU-era default.
    """
    # same instrumentation as serving_fill.ask: these two functions are every
    # model call the pipeline makes, so between them they account for the whole
    # LLM stage.
    with stage_timer.stage("llm", meta={"model": MODEL, "npredict": npredict}) as st:
        text, meta = llm_client.ask(prompt, npredict=npredict, timeout=timeout,
                                    model=MODEL, with_meta=True)
        st.items(1).tokens(int(meta.get("eval_count") or 0))
        _note_via((meta or {}).get("via"))
        return text


# WHICH BACKEND ANSWERED IS PART OF WHETHER THE ROW SHOULD EXIST. llmapi silently
# fails over to a 7b on a CPU box when the farm is unreachable, and returns that fact
# in meta["via"] -- which both of the pipeline's two model-calling functions asked for
# and then threw away, keeping only the token count. So the standing rule that serving
# tables are written by the 14B was enforced by nothing at all: a farm outage produced
# a pass of 7b-written cards that are indistinguishable, afterwards, from good ones.
#
# This does NOT refuse the answer. During an outage a 7b card is arguably better than
# no card, and that is the operator's call, not this function's. What it does is make
# the choice VISIBLE: every fallback answer is counted, and the first one in a pass
# says so loudly, so "the farm was down for this pass" is a line in the log rather
# than something to be inferred from quality complaints weeks later.
_VIA_SEEN = {}


def _note_via(via):
    if not via:
        return
    _VIA_SEEN[via] = _VIA_SEEN.get(via, 0) + 1
    if via != "farm" and _VIA_SEEN[via] == 1:
        print("[ALERT] %s: a model answer came from %r, NOT the farm. Serving rows "
              "written from here are %s output, not the %s serving model. Counted in "
              "the pass summary." % (__name__, via, via, MODEL),
              file=sys.stderr, flush=True)


def via_counts():
    """-> {backend: answers}. Printed in the pass summary so a run that quietly ran on
    the fallback is visible in the same line as everything else it did."""
    return dict(_VIA_SEEN)


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "x"


def word_rx(term):
    return re.compile(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)")


def _json_reply(raw):
    """Shared reply envelope: NONE / prose-wrapped JSON / garbage -> dict or None."""
    if not raw or raw.strip().upper().startswith("NONE"):
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _s(v, cap=400):
    """Optional string field: '' and non-strings collapse to None (absence is NULL)."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or v.lower() in ("null", "none", "n/a", "unknown", "not stated"):
        return None
    return v[:cap]


# Function words and corporate boilerplate carry no evidence, so they never count as
# an overlap token (an 'assess' sentence made only of these is not grounded).
_STOP = {"the", "and", "for", "with", "from", "that", "this", "have", "has", "had",
         "its", "their", "into", "also", "been", "were", "are", "was", "will",
         "which", "company", "companies", "limited", "group", "including", "such",
         "other", "these", "those", "them", "there", "than", "then", "when", "while",
         "about", "over", "under", "more", "most", "some", "both", "well", "very",
         "actively", "involved", "significant", "advanced", "various", "further"}


def _has_word(tok, hay):
    """Word-boundary presence -- 'arms' must not match inside 'armscor'."""
    return re.search(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", hay) is not None


def _content_toks(text, min_tok=4):
    return [w for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(w) >= min_tok and w not in _STOP]


def _designators(text, skip_first=False):
    """The tokens a claim can be CHECKED on: proper nouns and alphanumeric
    designators. 'F-22 Raptor' -> {'22', 'raptor'}; 'defence systems' -> set().
    skip_first drops a sentence's leading word, which is capitalised by grammar."""
    out, first = set(), True
    for m in re.finditer(r"[^\W_]+(?:[-/'’][^\W_]+)*", str(text or ""), re.UNICODE):
        tok, lead = m.group(0), first
        first = False
        if lead and skip_first:
            continue
        low = tok.lower()
        # 'F-22', '155mm', 'Su-30MKI' are ONE designator, not a bare '22' that any
        # number in the haystack would satisfy.
        if any(c.isdigit() for c in low) and any(c.isalpha() for c in low):
            out.add(low)
            continue
        for part in re.findall(r"[a-z0-9]+", low):
            if len(part) < 2 or part in _STOP:
                continue
            if any(c.isdigit() for c in part) or tok[:1].isupper():
                out.add(part)
    return out


def _in_hay(text, hay, min_tok=4):
    """Traceability gate for a SHORT field that must be STATED.

    STRENGTHENED (audit C3): the old rule passed on any ONE content token of >= 4
    chars, so every claim about a company passed on the company's own name -- it was
    named a hallucination guard while guarding almost nothing. A field now has to
    match on something specific: a proper noun / alphanumeric designator the
    statements actually contain, or TWO distinct content tokens they contain."""
    if not text:
        return False
    hay = (hay or "").lower()
    if any(_has_word(t, hay) for t in _designators(text)):
        return True
    return len({t for t in _content_toks(text, min_tok) if _has_word(t, hay)}) >= 2


# Do not split inside an abbreviation: "expanding ... in the U.S. and Germany"
# is ONE sentence, and splitting it manufactured an ungrounded fragment.
_SENT_SPLIT = re.compile(r"(?<![A-Z]\.)(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def _entailed(sentence, hay, own=frozenset()):
    """One sentence of free LLM prose is carried by the statements only if
    EVERY proper noun / designator it names (bar the company's own name) is stated,
    and at least half its content words are. This is what `assess` is gated on:
    'F-22 Raptor' and 'U.S. Air Force' have zero corpus occurrences, so the
    sentence asserting them cannot be traced and is dropped."""
    hay = (hay or "").lower()
    des = {t for t in _designators(sentence, skip_first=True) if t not in own}
    if any(not _has_word(t, hay) for t in des):
        return False
    toks = [t for t in _content_toks(sentence) if t not in own]
    return sum(1 for t in toks if _has_word(t, hay)) >= 2


def ground_text(text, hay, own_name=None):
    """Sentence-by-sentence grounding of a multi-sentence LLM field -> the kept
    text, or None when too little of it survives. Returning None REFUSES the row:
    an assessment we cannot trace is worse than no assessment."""
    if not text:
        return None
    own = set(_content_toks(own_name)) | _designators(own_name) if own_name else set()
    sents = [x.strip() for x in _SENT_SPLIT.split(text) if x.strip()]
    if not sents:
        return None
    kept = [x for x in sents if _entailed(x, hay, own)]
    return " ".join(kept) if kept else None


# --------------------------------------------------------------------------- corpus io

def load_docs(cur):
    cur.execute("""SELECT document_id, title, source_id, language, url, meta->>'set'
                     FROM extracted.document""")
    return {r[0]: {"title": r[1], "source": r[2], "lang": r[3], "url": r[4],
                   "set": r[5]} for r in cur.fetchall()}


def load_props(cur):
    cur.execute("""SELECT document_id, i, subject, predicate, object, time_txt,
                          place_txt, modality, ev_quote
                     FROM extracted.proposition ORDER BY document_id, i""")
    by_doc = {}
    for did, i, s, p, o, tt, pt, mo, q in cur.fetchall():
        by_doc.setdefault(did, []).append(
            {"s": s or "", "p": p or "", "o": o or "", "t": tt, "pl": pt,
             "m": mo, "q": q or ""})
    return by_doc


def prop_line(pr, url=None, qn=180):
    base = "- %s %s %s -- \"%s\"" % (pr["s"], pr["p"], pr["o"], clip(pr["q"], qn))
    return base + (" (%s)" % url if url else "")


# ------------------------------------------------------------------- company candidates

def reference_names():
    """The same name sources load_terms uses, restricted to actual COMPANY names
    (competitor names, geo companies, matchup companies, registry companies)."""
    names = [v.get("name", "") for v in REF.get("competitors", {}).values()]
    names += [g.get("name", "") for g in REF.get("geoComps", [])]
    names += [m.get("compBy") for m in REF.get("matchups", {}).values()
              if isinstance(m.get("compBy"), str)]
    names += [r.get("company") for r in REF.get("sourceRegistry", [])
              if isinstance(r.get("company"), str)]
    names += ["Kalyani", "Bharat Forge", "KSSL"]
    return sorted({n.strip() for n in names if n and len(n.strip()) >= 4})


def merge_candidates(names):
    """One identity per company: aliases.merge folds legal suffixes, the client
    group's spellings, known alias pairs, then word-boundary containment."""
    return alias_merge(names)
def apply_roster_allowlist(cur, merged):
    """Filter the candidate companies to the curated roster before profiling.

    The rule lives in roster.py because serving_fill needs the same one: it decides
    whether a card may be called a threat. Two implementations drifting apart is how a
    company lands on the Competitor tab with all its news filed as watch.

    Advisory -- no table or an empty one means no opinion, and the roster is whatever
    the corpus mentioned, exactly as before.
    """
    kept = roster.allows(merged, roster.keys(cur))
    if len(kept) != len(merged):
        print("companies: allowlist kept %d of %d candidate(s)"
              % (len(kept), len(merged)), flush=True)
    return kept


def company_mentions(aliases, docs, props_by_doc):
    """-> (doc_ids, props_with_url) where any alias word-boundary-matches the title
    or a proposition subject/object."""
    rxs = [word_rx(a) for a in aliases]
    # A company whose only handles are short acronyms (<=4 chars, e.g. "AAE") collides with
    # unrelated uses of the same letters -- "AAE" the UAE wiring maker vs "AAE" = Armee de
    # l'Air et de l'Espace, the French air force. For an acronym-only company, refuse a doc
    # that is itself about an armed force, so a Reaper deployment can't contaminate the profile.
    short_only = bool(aliases) and all(len(str(a).strip()) <= 4 for a in aliases)
    hit_docs, hit_props = [], []
    for did, prs in props_by_doc.items():
        d = docs.get(did)
        if d is None:
            continue
        if short_only and is_force(d["title"] or ""):
            continue
        doc_hit = any(rx.search((d["title"] or "").lower()) for rx in rxs)
        doc_props = []
        for pr in prs:
            so = ("%s %s" % (pr["s"], pr["o"])).lower()
            if any(rx.search(so) for rx in rxs):
                doc_props.append((did, pr))
        if doc_hit or doc_props:
            hit_docs.append(did)
            hit_props.extend(doc_props)
    return hit_docs, hit_props


# ------------------------------------------------------------------- step 1: companies

# The five roles that are not a rival, whatever the company makes. `prime` is the only
# admitting value; `None` (unknown / older model output) leaves the decision to the clauses.
ROLES = ("prime", "supplier", "integrator", "services", "trader", "civil")
NOT_RIVAL_ROLES = ("supplier", "integrator", "services", "trader", "civil")

PROFILE_PROMPT = """You profile companies for a defence-intelligence dashboard for KSSL
(Kalyani Strategic Systems, the defence arm of the Kalyani Group / Bharat Forge, India).
KSSL sells exactly these nine product lines and nothing else:
  1 Artillery -- towed, mounted and self-propelled 155mm/105mm guns, mortars, rocket artillery
  2 Ammunition -- large- and small-calibre rounds, shells, propellant, fuzes, warheads
  3 Small Arms -- rifles, carbines, sniper rifles, machine guns, pistols
  4 Protected & Armoured Vehicles -- MRAPs, APCs, IFVs, light tactical vehicles, turrets
  5 Armoured Vehicle MRO -- overhaul and upgrade of armoured platforms, running gear, barrels
  6 Naval guns and the MRAUV underwater vehicle -- NOT ships, boats or submarines
  7 UAVs & Drones -- tactical ISR UAS, loitering munitions, FPV drones
  8 Missiles & Air Defence -- ATGMs, SAMs, air-defence systems
  9 Precision Components & Forgings -- shell and barrel forgings sold to other gun makers
Below are extracted statements about "%s", each with its supporting quote.

If "%s" is NOT a company (a country, government, ministry, armed force) or the
statements are too thin to profile it, reply exactly: NONE
If the statements appear to describe MORE THAN ONE organization sharing this name -- e.g.
a company AND an armed force, air force, navy or government body that share an acronym --
use ONLY the statements clearly about the defence COMPANY and ignore the rest; if you
cannot tell which statements are about the company, reply exactly: NONE

Otherwise reply with ONLY this JSON (no prose around it):
{"sector": "<its defence sector(s), stated or directly evident in the statements, else null>",
 "hq": "<headquarters city/country ONLY if a statement states it, else null>",
 "assess": "<2-3 sentences, in ENGLISH: what the statements show THIS company doing --
            concrete orders, products, moves; no generic filler and no speculation>",
 "threat": "<high|medium|low -- its competitive threat to KSSL, judged only from the
            statements, else null. Kalyani/KSSL/Bharat Forge is the CLIENT GROUP itself:
            for it, threat is always null>",
 "products": ["<product/system names the statements explicitly name as THIS company's OWN --
             never a partner's or a customer's product that merely appears alongside it>"],
 "role": "<prime | supplier | integrator | services | trader | civil --
          prime: sells complete weapons, vehicles, munitions or UAVs under its own name;
          supplier: sells components, materials, engines, gearboxes, castings, propulsion
            or subsystems INTO another company's end product;
          integrator: assembles or integrates other companies' systems;
          services: consultancy, IT/software, logistics, staffing, test and evaluation, or
            MRO of other makers' equipment;
          trader: markets or exports other makers' products;
          civil: its products are commercial or consumer, not defence>",
 "dir": "<client if it IS Kalyani/KSSL/Bharat Forge (one group);
         rival ONLY if the statements show this company DESIGNS AND MANUFACTURES, as an end
           product it sells under its own name, something in one of the nine lines above --
           a company KSSL would meet across a tender, not across a purchase order;
         otherwise other. Answer other for: manned aircraft and helicopters (including a
           crewed aircraft converted to uncrewed flight); ships, boats, submarines, unmanned
           surface vessels, torpedoes; satellites and launchers; radars, sonars,
           electro-optics, electronic warfare, radios, C2 and mission software; body armour
           and soldier equipment; civilian or consumer products; a supplier of components,
           materials, engines, gearboxes, castings, propulsion or subsystems to other OEMs;
           a consultancy, IT/software/cyber firm, systems integrator, logistics, staffing or
           test-and-evaluation services provider; a research organisation; a procurement
           agency; an export or trading house; and any company whose only link to a product
           is a partnership to market, integrate or licence somebody else's.
         A company that makes BOTH (say, aircraft AND missiles) is rival>"}

Rules: use ONLY the statements; never add facts you know from elsewhere; unstated
fields are null; an empty product list is fine. Write all text fields in ENGLISH.

Statements about %s:
%s"""


# The PROFILE_PROMPT describes KSSL as an "Indian maker of artillery, ammunition,
# armoured vehicles, small arms, drones". Two rivals came back with that exact list,
# in that exact order, as their own 'sector' -- the prompt's words leaking into the
# data. _in_hay cannot see it, because each of those words does occur somewhere.
_PORTFOLIO_SEQ = [re.compile(r) for r in (
    r"artiller",
    r"ammunition|munitions",
    r"armou?red[ -]*(?:vehicle|fighting|personnel|car|platform)?",
    r"small[ -]*arms",
    r"drones?|uavs?|unmanned",
)]
_HEDGE_RX = re.compile(
    r"(?<!\w)(possibly|likely|probably|perhaps|presumably|apparently|seemingly|"
    r"may (?:be|include)|might (?:be|include)|could (?:be|include)|potentially)(?!\w)",
    re.I)


def prompt_echo(text):
    """True when a field just plays the prompt's own KSSL portfolio list back at us,
    in the prompt's order (>= 4 of the 5 items, in sequence). A genuine two-item
    sector like 'armoured vehicles, artillery' is NOT an echo."""
    low = (text or "").lower()
    last, n = -1, 0
    for rx in _PORTFOLIO_SEQ:
        m = rx.search(low, last + 1)
        if m and m.start() > last:
            last = m.start()
            n += 1
    return n >= 4


def parse_profile(raw, hay, name=None):
    d = _json_reply(raw)
    if d is None:
        return None
    if name is not None and (is_force(name) or not is_one_org(name)):
        return None                      # a country/ministry/armed force is no company
    assess = _s(d.get("assess"), 600)
    if not assess:
        return None
    assess = ground_text(assess, hay, name)
    if not assess:
        return None                      # every sentence ungrounded -> refuse the row
    threat = _s(d.get("threat"), 10)
    if threat:
        threat = threat.lower()
        if threat not in ("high", "medium", "low"):
            return None                      # invented vocabulary refuses the row
    direction = (_s(d.get("dir"), 10) or "other").lower()
    if direction not in ("rival", "client", "other"):
        direction = "other"
    # ROLE: what KIND of company it is, asked of the model directly. Measured over the last
    # full rebuild, the model's own judgement produced 103 of 110 refusals and all six regex
    # clauses together produced 3 -- the leverage is in what we ask, not in what we pattern
    # match afterwards. A supplier, an integrator, a trader and a consumer-drone maker are
    # four things no regex reliably tells apart and the model already knows.
    role = (_s(d.get("role"), 12) or "").lower() or None
    if role and role not in ROLES:
        role = None                          # invented vocabulary -> unknown, not a refusal
    sector = _s(d.get("sector"), 160)
    if sector and (not _in_hay(sector, hay) or prompt_echo(sector)
                   or _HEDGE_RX.search(sector)):
        sector = None                        # untraceable / prompt echo / hedged -> NULL
    hq = _s(d.get("hq"), 120)
    if hq and not _in_hay(hq, hay):
        hq = None
    products = d.get("products") or []
    if not isinstance(products, list):
        products = []
    products = [_s(p, 90) for p in products if isinstance(p, str)]
    products = [p for p in products if p and p.lower() in hay][:12]
    return {"sector": sector, "hq": hq, "assess": assess, "threat": threat,
            "products": products, "dir": direction, "role": role}


# A nav page, a tag index, a careers page or a media listing is not a company update.
# 'Avoimet tyopaikat | Patria' (open positions) and 'BrahMos in Media' were shown as
# dated company news (audit M9).
CAREER_RX = re.compile(
    r"(avoimet\s+ty[oö]paikat|open positions|vacanc|career|"
    r"\bjobs?\b|\bin media\b|media\s*(?:cent|room)|press\s*releases?|newsroom|"
    r"news\s*archive|\btag\b|\bcategory\b|sitemap|contact us|privacy)", re.I)


def usable_update(url, title, patterns, props_t):
    """A document may back a dated 'update' line only if it is one STORY about this
    company: not a listing/tag/careers page, and on-portfolio by is_relevant()."""
    if not title or is_listing(url) or CAREER_RX.search(title):
        return False
    return is_relevant(patterns, title, props_t)


def product_names(products):
    """Products are STORED as objects ({id, name, category, source, source_url}); every
    Python consumer -- rate_threat, step_matchups, the competitor gate -- wants the name.
    One conversion at the read boundary rather than isinstance checks scattered over four
    call sites, and tolerant of the bare-string form the reference archive still holds
    and is never rebuilt into."""
    out = []
    for pr in products or []:
        nm = pr if isinstance(pr, str) else (pr or {}).get("name") or ""
        nm = str(nm).strip()
        if nm:
            out.append(nm)
    return out


def product_rows(names, use, docs):
    """[{id, name, category?, source?, source_url?}] -- the product list as objects.

    KSSL VPS_DB.docx asks products to carry id, name, category, description, image,
    source and source_url. Four of those this pipeline can fill from what it already
    holds; `description` and `image` it cannot, and they are absent rather than empty --
    a product blurb the corpus never wrote is the kind of plausible filler this
    dashboard removed once already.

    `category` bands the product by ITS OWN name where the name says what it is, instead
    of by its company's sector, which the Products page used for everything -- so a firm's
    radars and its trucks came out under one label. It is a narrow win, not a broad one:
    measured over the real corpus it fills 4 products in 112, because real names are model
    designations (Switchblade, VSR-700, M-346) that carry no category word. Never wrong
    when present, and Products.jsx keeps the company sector as the fallback.

    `source_url` is the document whose statement actually named the product -- the same
    statements the profile was built from, so the citation is the evidence, not a guess.
    """
    key_label = {k: v for v, k in REF["CAT_KEY"].items()}
    out, seen = [], set()
    for nm in names or []:
        key = slug(nm)
        if not key or key in seen:
            continue
        seen.add(key)
        row = {"id": key, "name": esc(nm)}
        band = categorise_product(nm)
        if band:
            row["category"] = key_label.get(band, band)
        rx = word_rx(nm)
        for did, pr in use or []:
            blob = ("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])).lower()
            if rx.search(blob):
                d = docs.get(did) or {}
                if d.get("url"):
                    row["source_url"] = d["url"]
                    row["source"] = d.get("source")
                break
        out.append(row)
    return out


def rate_threat(products, n_docs):
    """A MEASURED threat rating with the measurement attached, replacing a constant:
    every rival used to be stored 'high', which is not a rating. Inputs are countable
    -- how many KSSL portfolio bands the company's STATED products fall into, and how
    much corpus stands behind it. Returns (threat, threatNote)."""
    key_label = {k: v for v, k in REF["CAT_KEY"].items()}
    bands = sorted({b for b in (categorise_product(p) for p in product_names(products)) if b})
    labels = [key_label.get(b, b) for b in bands]
    if len(bands) >= 2 and n_docs >= 3:
        threat = "high"
    elif bands or n_docs >= 3:
        threat = "medium"
    else:
        threat = "low"
    note = ("%d corpus document(s); stated products fall in %s"
            % (n_docs, ", ".join(labels) if labels else "no KSSL category"))
    return threat, note


# A company that only SELLS SERVICES around defence is not a rival to a maker of guns and
# vehicles, however much defence work it does. Every phrase below was taken from the assess
# text of a row that is in serving.competitors today and should never have been: Accenture
# ("digital enablement ... for defense logistics and information systems"), SAIC ("a
# technology integrator that collaborates with other defense companies"), Amentum ("a wide
# range of services including research and development, test and evaluation, and supply
# chain management"), Applied Intuition ("software-defined vehicle capabilities").
#
# The list is deliberately BUSINESS-MODEL words, not technology areas. `cybersecurity`,
# `electronics` and `information systems` are NOT here: Bharat Electronics and Elbit carry
# them as product lines, and a technology area a real manufacturer also works in cannot be
# the thing that disqualifies it.
_SERVICES_RX = re.compile(
    r"(?<!\w)(consultanc\w*|advisory (?:firm|services)|systems? integrat\w*|"
    r"technology integrat\w*|integrator|outsourc\w*|staffing|professional services|"
    r"managed services|range of services|digital (?:enablement|transformation)|"
    r"digital forensics|software[- ]defined|supply chain management|"
    r"test and evaluation)(?!\w)", re.I)
# ...unless the same evidence shows it actually MAKES something. Short and unambiguous on
# purpose: `delivers` and `develops` are absent, because a consultancy delivers and develops
# too -- they were the words that let the services rows in.
_MAKES_RX = re.compile(
    r"(?<!\w)(manufactur\w*|produces|producing|production of|builds|"
    r"forges|forging|shipyard|foundry|arsenal)(?!\w)", re.I)


# THE FOURTH CLAUSE: "directly competing with KSSL". The gate above admits any defence
# manufacturer -- which let Doodle Labs in on products ["radio systems"]. It makes
# jam-resistant mesh radios for drones; KSSL forges barrels and builds artillery, and the two
# never meet in a tender. Real company, real defence manufacturing, not a rival.
#
# The obvious test -- require a product to fall in one of KSSL's nine bands -- was measured
# against the live table and REFUSED: the band vocabulary is brand-blind, so AeroVironment
# ("Switchblade", "Shrike", "Puma") and Atlas Elektronik carry no category word and would be
# deleted alongside the genuine mismatches. 77 of 150 rows would have gone, real rivals
# among them.
#
# So the rule is inverted: default-allow, with positive evidence of a DIFFERENT business.
# And it fires only when EVERY stated product is outside KSSL's world. Requiring merely one
# was measured too -- it deleted Leonardo, which builds naval guns, on an "SPC Cloud e
# Sicurezza" entry, and Kongsberg on a radar. `products` is not a catalogue; it is whatever
# the recent corpus happened to mention, so one stray entry must never condemn a company.
#
# Precision over recall, deliberately: on the live table this removes 3 rows and keeps every
# real competitor. Boeing and Dassault survive it, because "F-18" and "Rafale" match nothing
# here -- catching those needs vocabulary work, not a stricter rule.
_OUT_OF_PORTFOLIO = re.compile(
    r"(?<!\w)("
    r"radio|radios|transceiver|datalink|waveform|satcom|antenna|antennas"
    r"|avionic|avionics|flight display|flight displays|cockpit"
    r"|satellite|satellites|launch vehicle|space launch|orbital"
    r"|radar|radars|sonar|sonars"
    r"|fighter jet|airliner|business jet|helicopter|helicopters"
    r"|turbofan|turboprop|jet engine|aero engine|aircraft engine"
    r"|software|cyber|cloud|middleware"
    # F1 NAVAL PLATFORMS. KSSL's naval band is "Naval guns / MRAUV" -- it SELLS a gun to a
    # shipyard. A yard that builds the hull is a customer, not a rival, and the naval keyword
    # bag described a navy rather than KSSL's naval line.
    r"|frigate|destroyer|corvette|submarine|warship|patrol vessel|opv"
    r"|shipbuilding|shipyard|surface combatant|torpedo"
    # F2 MANNED AIRCRAFT. None of the nine bands is an aircraft. Generic words only --
    # chasing "Rafale", "AH-1Z", "JF-17" is vocabulary whack-a-mole and belongs in the prompt.
    r"|fighter|fighters|combat aircraft|aircraft|attack helicopter|airlifter"
    r")(?!\w)", re.I)


# F4 EXPORT AND TRADING HOUSES. Rosoboronexport sells Kalashnikov's rifles and Mil's
# helicopters; it manufactures nothing. Keyed on NAME and SECTOR only, never on `assess` --
# the assess says "manufactured by Kalashnikov" and _MAKES_RX would rescue it on someone
# else's factory.
_TRADER_RX = re.compile(r"(?<!\w)(export|import|trading)(?!\w)", re.I)


# ---------------------------------------------------------------- the band, gate-side
#
# THE HOLE THIS CLOSES. `out_of_portfolio` rejected only when NOTHING banded into one of
# KSSL's nine categories AND every product also matched a hand-written out-of-business
# regex. Measured on the live table, the second condition held for 1 of the 35 candidate
# rows -- so the first never got to bite, and 35 of 98 admitted rows made nothing KSSL
# makes: Airbus and Dassault (aircraft), Fincantieri and Naval Group (shipyards), Saildrone,
# Mehler (body armour), Auriga Space. The rule is now simply: no band, no row.
#
# Text that must never band, stripped BEFORE banding rather than checked after it. Stripping
# is what makes the broad words in the client's own vocabulary safe: `vehicle` cannot be
# reached through "unmanned surface vehicle", and `drone` cannot be reached through
# "counter-drone" or "drone detection" -- a system built to defeat an X is not an X, and
# L3Harris's "drone detection system" and Zone 5's "drone-defeat systems" both banded as
# UAVs. NOT a bare `aircraft`: that word is inside the uav keyword "unmanned aircraft
# system", and stripping it deleted TEKEVER's AR5 -- a real UAV rival. The manned-aircraft
# phrases below are specific for that reason.
_NOT_KSSL_RX = re.compile(r"(?<!\w)("
    r"helicopters?|rotorcraft|rotary[- ]wing|fighter(?: jets?| aircraft)?s?|combat aircraft"
    r"|airlifters?|jets?|airliners?|trainer aircraft"
    r"|frigates?|destroyers?|corvettes?|submarines?|warships?|patrol vessels?|opv"
    r"|shipbuilding|shipyard|surface combatants?|torpedo(?:es)?|vessels?|boats?|catamarans?"
    r"|usvs?|(?:unmanned|autonomous|uncrewed) surface (?:vehicles?|vessels?|ships?)"
    r"|unmanned surface|autonomous surface"
    r"|satellites?|launch vehicles?|space launch|orbital|electromagnetic launcher"
    r"|radars?|sonars?|electronic warfare|ew suites?|jammers?|datalinks?|radios?|avionics"
    r"|c2|command[- ]and[- ]control|combat management|mission systems?|electronics suites?"
    r"|targeting systems?|drone detection"
    r"|counter[- ]?(?:rocket|artillery)(?:[ -]+(?:rocket|artillery|and mortar|ram))*"
    r"|counter[- ]?(?:drone|uas|uav|unmanned)|anti[- ]drone"
    r"|drone[- ](?:interception|defeat)|contra drones|c-uas|c-uav"
    r"|helmets?|vests?|body armou?r|ballistic protection"
    # Applied Intuition, named by the client: "software-defined vehicle platform" reached
    # the pav keyword `vehicle` on a product that is software.
    r"|software[- ]defined|simulation software|digital twins?"
    r")(?!\w)", re.I)

# The client's vocabulary describes the CATEGORIES; these are the product NAMES the corpus
# actually uses for them. Every entry was taken from a row in the live table that a human
# reads as an obvious rival and the bander could not see.
_GATE_ADD = {
    "art":   ["nemo", "archer", "himars", "m777", "self-propelled howitzer",
              "mobile howitzer", "ramjet artillery"],
    "ammo":  ["m\u00fchimmat", "dpicm", "smart ammunition", "cased telescoped"],
    "sa":    ["lmg", "light machine gun", "assault rifle", "shotgun", "negev", "arad",
              "ak-203", "ak200", "belt-fed"],
    "pav":   ["6x6", "6\u00d76", "8\u00d78", "humvee", "hmmwv", "jltv", "rws",
              "remote weapon station", "ugv", "unmanned ground", "tactical vehicle",
              "light tactical", "combat vehicle", "ifv", "light tank",
              "armoured platform", "armored platform"],
    "naval": ["naval gun", "uuv", "unmanned underwater", "autonomous underwater", "remus",
              "hugin", "seafox", "seacat", "mrauv", "underwater vehicle"],
    "uav":   ["uas", "unmanned aerial system", "uncrewed aerial", "unmanned aircraft system",
              "loitering munition", "switchblade", "kargu", "warmate", "fpv", "black hornet",
              "collaborative combat"],
    "msl":   ["pac-3", "nasams", "samp/t", "iris-t", "aster", "surface-to-air",
              "cruise missile", "air-defence", "air-defense", "manpads", "shorad",
              "strike missile", "ballistic missile"],
}
# Words that band a NAVY, or a SENSOR, rather than a product KSSL sells. `naval` and `marine`
# put every shipyard in the table into KSSL's naval-GUN band; `isr` banded WESCAM sensor
# pods as drones; `male` banded "MALE drone with BAE" partnerships.
# `vehicle` is dropped for the same reason, and it is free: measured over all 107 live rows,
# removing it changes not one verdict, because the specific words (armoured, mrap, apc, tank,
# ugv, combat vehicle, tactical vehicle, ifv, 8x8) carry every real case. What it stops is
# "software-defined vehicle platform" -- Applied Intuition, named by the client -- and
# "YFQ-44A air vehicle" reaching Protected & Armoured Vehicles.
_GATE_DROP = {"naval": {"naval", "marine"}, "uav": {"isr", "male", "swarm"},
              "pav": {"troop", "vehicle"}}
_GATE_VOCAB = None


def _gate_vocab():
    global _GATE_VOCAB
    if _GATE_VOCAB is None:
        out = []
        for key, meta in (REF.get("CAT_META") or {}).items():
            kws = [k for k in meta.get("kw", []) if k not in _GATE_DROP.get(key, ())]
            for kw in kws + _GATE_ADD.get(key, []):
                if len(kw) >= 2:
                    out.append((len(kw), kw, key, _band_rx(kw)))
        _GATE_VOCAB = sorted(out, reverse=True)          # longest keyword wins
    return _GATE_VOCAB


def gate_band(text):
    """The KSSL category this text names, or None -- with what KSSL does not sell removed
    first. Separate from categorise_product(), which labels a product for display and must
    stay literal about the name it was given."""
    hay = _NOT_KSSL_RX.sub(" ", (text or "").lower())
    for _n, _kw, key, rx in _gate_vocab():
        if rx.search(hay):
            return key
    return None


def out_of_business(product):
    """The whole product is a class KSSL is in no part of: it names one, and nothing is
    left that bands. Chooses the REFUSAL WORDING only -- never admits or rejects by itself,
    so a sonar house the client's own archive calls an MRAUV rival still gets its band."""
    return bool(_NOT_KSSL_RX.search(product or "")) and gate_band(product) is None


def out_of_portfolio(products):
    """True when every product this company states sits outside KSSL's categories.

    Two conditions, both required: nothing bands into one of the nine KSSL categories, AND
    every single product matches a business KSSL is not in. Either alone is too blunt --
    see the note above.
    """
    products = [p for p in (products or []) if (p or "").strip()]
    if not products:
        return False                      # no evidence either way; the products check owns this
    if any(categorise_product(p) for p in products):
        return False                      # it makes something KSSL makes
    return all(_OUT_OF_PORTFOLIO.search(p) for p in products)


# THE FIFTH CLAUSE: A SUPPLIER IS NOT A RIVAL. A rival fields an END SYSTEM and meets KSSL
# across a tender; a company that sells INTO someone else's end system meets KSSL across a
# purchase order. Both make defence hardware, and clause four cannot tell them apart --
# titanium castings for a 155mm howitzer land squarely in Artillery.
#
# The named cases, all sitting as dir='rival' today:
#   PTC Industries   "metallic airframe assembly"     -- BAE's Indian foundry: it casts the
#                                                        M777's saddle, cradle and carriage.
#                                                        BAE is the rival; PTC is BAE's chain.
#   RENK Group       "drive systems for armored ..."  -- gearboxes for vehicle OEMs
#   Safran Hel. Eng. "turboshaft engines"             -- propulsion for airframers
#   SSAB             "Armox 500 AM Powder"            -- a steel mill; it sells KSSL its plate
#
# EVERY stated product must be a component, material or subsystem -- the same discipline as
# clause four, and for the same reason. One driveline entry must never delete a prime that
# also builds vehicles.
_COMPONENT_RX = re.compile(
    r"(?<!\w)("
    # NOT a bare "steel" or "blank": "Insta Steel Eagle drone solution" is a drone, and a
    # "blank" is ammunition before it is a barrel blank. Brand names eat broad material words.
    r"steel plate|steel plates|armou?red steel|armou?r steel|steel powder|steel mill"
    r"|plate|plates|billet|billets|alloy|alloys|superalloy|powder|titanium|ingot"
    r"|casting|castings|forging|forgings|barrel blank"
    r"|airframe|aerostructure|structure|structures|sub-?assembly|assembly|assemblies"
    r"|sub-?system|sub-?systems|component|components"
    r"|drive system|drive systems|transmission|transmissions|gearbox|gearboxes|powertrain"
    r"|axle|axles|suspension|track link|road wheel"
    r"|engine|engines|turbine|turbines|turboshaft|turbomotor|turbofan|turboprop|propulsion"
    r"|rocket motor|rocket motors"
    r"|bearing|bearings|actuator|actuators|valve|valves"
    r"|gear unit|gear units|power-?pack|power-?packs|coupling|couplings|clutch|clutches"
    r"|control system|control systems|dacs"
    r")(?!\w)", re.I)

# ...EXCEPT the parts KSSL ITSELF sells. Two of the nine categories -- Precision Components
# & Forgings, and Armoured Vehicle MRO -- are component businesses, so "sells parts" cannot
# disqualify on its own without deleting KSSL's own competitors. A house selling 155mm shell
# forgings meets KSSL across a tender for exactly that; a house selling gearboxes meets it
# across a purchase order. The client settled the gearbox case by naming RENK, so `gearbox`
# is deliberately NOT here.
_KSSL_PART_RX = re.compile(
    r"(?<!\w)(forg\w*|barrels?|shells?|overhaul|refit|road wheels?|tracks?|sprockets?|"
    r"crankshafts?)(?!\w)", re.I)


def sells_components(products):
    """True when the evidence shows parts and no KSSL-category system of its own.

    THE ALL-PRODUCTS RULE WAS DEAD BY CONSTRUCTION. Measured on the live table: 0 of 105
    admitted rows had an all-component product list, and in a full rebuild the clause fired
    once. RENK Group -- named by the client as a non-competitor -- was admitted because only
    4 of its 8 products matched, "gear units" and "power-packs" not being in the vocabulary.
    One product line that merely SOUNDS like a system rescued every supplier.

    So: EVERY product is a part, and none of them is a part KSSL sells itself. The band
    rule below is what catches the ordinary supplier (a gearbox bands nothing); this clause
    exists for the supplier whose parts DO band -- PTC Industries reaches Precision
    Components through "metallic airframe assembly", SSAB reaches Armoured Vehicles through
    "armoured steel plate", and both would otherwise be admitted.
    """
    products = [p for p in product_names(products) if p.strip()]
    if not products:
        return False
    if not all(_COMPONENT_RX.search(p) for p in products):
        return False                     # one end system of its own rescues the whole row
    return not any(_KSSL_PART_RX.search(p) for p in products)


# THE SIXTH CLAUSE: THE PRODUCTS MUST BE ITS OWN. Palladyne AI is stored with products
# ["HARPY", "HAROP", "Mini HARPY"] -- Israel Aerospace Industries' loitering munitions, which
# Palladyne partnered to "manufacture, integrate, and market". The profile attributed IAI's
# catalogue to the marketing partner, so a software company inherited a rival's weapons and
# passed every test above on them.
#
# The evidence says so in plain English: a possessive naming a DIFFERENT company, followed by
# the product. A company's own possessive ("Kongsberg's PROTECTOR") is excluded by name, which
# is why the name is passed in.
_POSSESSIVE_RX = re.compile(r"\b([A-Z][\w.&-]*(?:\s+[A-Z][\w.&-]*){0,3})(?:\u2019s|'s)\s+([^.]{0,110})")


def borrowed_products(prof, name=""):
    """True when EVERY stated product is credited in the evidence to another named company."""
    products = product_names(prof.get("products"))
    if not products:
        return False
    own = {t for t in re.findall(r"\w+", (name or "").lower()) if len(t) > 2}
    claimed = set()
    for m in _POSSESSIVE_RX.finditer(prof.get("assess") or ""):
        owner = m.group(1).lower()
        if own and any(t in owner for t in own):
            continue                                  # its own product, properly credited
        tail = m.group(2).lower()
        for p in products:
            head = p.strip().lower()[:20]
            if head and head in tail:
                claimed.add(p)
    return len(claimed) == len(products)


# THE OWNER'S OWN LIST IS GROUND TRUTH, AND IT KNOWS THE CATEGORY. REF.competitors and every
# matchup's compBy are the client saying by hand "these are our rivals" -- and a matchup says
# more than that: it carries `cat`, so it says "a rival in Artillery", pairing that company's
# named product against a named KSSL product.
#
# It used to be consulted as a BOOLEAN that skipped every clause below, which made those
# clauses dead for 41 of 107 rows and meant one loose entry admitted a company outright.
# As a BAND SOURCE it does the same job with none of that: it carries the nine rows whose
# products are pure model designations -- Leonardo (76mm naval guns), Kongsberg/Saab/HII/
# Atlas Elektronik (AUVs against KSSL's MRAUV), AeroVironment, WB Group, Patria, L&T (K9
# Vajra) -- and it carries nothing it has not named a category for. Hindustan Aeronautics,
# in neither list, is refused as an aircraft OEM instead of being shielded.
#
# Keyed through aliases.fold(canonical(...)), not slug(): the archive writes "Bharat Heavy
# Electricals Limited" and "Armoured Vehicles Nigam Limited" where the corpus writes the
# name without its legal suffix, and slug() matched neither.
_ARCHIVE_BANDS = None


def _archive_band_map():
    out = {}
    for m in (REF.get("matchups") or {}).values():
        cb, cat = (m or {}).get("compBy"), REF.get("CAT_KEY", {}).get((m or {}).get("cat"))
        if isinstance(cb, str) and cb and cat and not is_client(cb):
            out.setdefault(fold_name(canon_name(cb)), set()).add(cat)
    for v in (REF.get("competitors") or {}).values():
        n = (v or {}).get("name") or ""
        if not n or is_client(n):
            continue
        for part in re.split(r"[\u00b7,/]", (v or {}).get("sector") or ""):
            band = gate_band(part)
            if band:
                out.setdefault(fold_name(canon_name(n)), set()).add(band)
    return out


def archive_bands(name):
    """The KSSL categories the client's own archive says this company competes in."""
    global _ARCHIVE_BANDS
    if _ARCHIVE_BANDS is None:
        try:
            _ARCHIVE_BANDS = _archive_band_map()
        except Exception:                                    # noqa: BLE001
            _ARCHIVE_BANDS = {}                              # never fatal
    return _ARCHIVE_BANDS.get(fold_name(canon_name(name or ""))) or set()


# How many extracted statements a profile call is allowed to read, and HOW they are chosen.
#
# THE BUG THIS REPLACES. It used to be `cprops[:25]` -- the first 25 statements in
# document order. company_mentions returns every statement of every document that names
# the company, grouped by document, so for a company the corpus covers heavily the first
# 25 statements all come from ONE arbitrary article. Measured on production:
#
#   Saab      2,262 docs, 12,051 statements -> profile listed ONE product ("Nimbrix"),
#                                              role=integrator  -> refused
#   Leonardo  1,701 docs,  7,834 statements -> products [], dir=other  -> refused
#   Northrop    475 docs,  1,113 statements -> a torpedo and a mine detector
#   HSW          14 docs,     19 statements -> Borsuk IFV, artillery barrels -> admitted
#
# The signature is unmistakable: the more the corpus knows about a company, the worse its
# profile. The two biggest rivals on the feed -- Saab at 46 signal cards, Leonardo at 41 --
# had no competitor row at all, so the Competitor tab disagreed with its own feed.
#
# The fix is to SPREAD: one statement per document, round-robin, so 60 statements come
# from 60 different articles instead of one. Re-measured the same way, Saab comes back
# rival/prime with Carl-Gustaf M4, RBS 70 NG and Gripen E, and Leonardo with the Hitfist
# turret -- both admitted. Babcock (services) and Naval Group (shipyard) still refuse,
# which is the gate working rather than the sample failing.
#
# Note what this does NOT do: it does not prefer statements that mention KSSL's
# categories. Choosing the evidence by the answer we want would make the portfolio gate
# self-fulfilling. Every document gets an equal voice; only the count went up.
PROFILE_STATEMENTS = 60


def spread_statements(cprops, n=PROFILE_STATEMENTS):
    """n of `cprops` [(doc_id, prop), ...] spread across documents, not the first n."""
    by_doc = {}
    for did, pr in cprops:
        by_doc.setdefault(did, []).append((did, pr))
    out, i = [], 0
    while len(out) < n:
        took = False
        for d in by_doc:
            if i < len(by_doc[d]):
                out.append(by_doc[d][i])
                took = True
                if len(out) >= n:
                    break
        if not took:
            break
        i += 1
    return out


def competes_with_kssl(prof, name=""):
    """-> (admit, reason). Is this profile a DIRECT DEFENCE COMPETITOR, or merely a company
    the corpus mentions near defence?

    The client's rule is that every row must compete with KSSL head-on: no supplier, no
    third party. So the question each clause asks is not "is this a defence company" but
    "would KSSL meet it across a tender".

      manufacturer  -- the model judged it a maker of end products (dir == 'rival') and did
                       not call it a supplier, integrator, services firm, trader or a
                       consumer brand (role)
      capability    -- the statements name at least one product of its OWN
      not services  -- its own description is not a services business with no making in it
      not a trader  -- it sells its own catalogue, not somebody else's
      its own       -- the products are not another company's, credited to it by a marketing
                       partnership
      not a vendor  -- it does not sell only parts INTO other people's systems, unless the
                       part is one KSSL sells too (forgings, barrels, MRO)
      in portfolio  -- and the decisive one: something it makes falls in one of KSSL's nine
                       categories. A radio maker is a defence manufacturer and still not a
                       rival to a gun house; so is a shipyard, and so is an aircraft OEM.

    A refusal is not a deletion: the profile is still built and still counted, it simply does
    not become a competitor row. `client` is passed through untouched.
    """
    d = (prof or {}).get("dir")
    if d == "client":
        return True, "client"
    if d != "rival":
        return False, "not a rival (dir=%s)" % (d or "none")
    role = (prof or {}).get("role")
    if role in NOT_RIVAL_ROLES:
        return False, "not a prime (role=%s)" % role
    # NORMALISE ONCE, HERE. products are STORED as objects ({id,name,category,source,...})
    # and arrive as bare strings from parse_profile. A dict raises AttributeError in a clause
    # that is outside any try, which kills the whole pass; and where it does not raise, the
    # bander str()s the dict and matches keywords against the SOURCE URL, which banded
    # AeroVironment as UAVs because its citation link contains "drone".
    prods = product_names(prof.get("products"))
    if not prods:
        return False, "no product of its own in the statements"
    hay = "%s %s" % (prof.get("assess") or "", prof.get("sector") or "")
    if _SERVICES_RX.search(hay) and not _MAKES_RX.search(hay):
        return False, "services business, no manufacturing evidence"
    if _TRADER_RX.search("%s %s" % (name or "", prof.get("sector") or "")):
        return False, "an export/trading house, not a manufacturer"
    if borrowed_products(prof, name):
        return False, "products belong to another company (%s)" % ", ".join(prods[:2])
    if sells_components(prods):
        return False, "supplies parts KSSL does not sell (%s)" % ", ".join(prods[:2])
    # THE PORTFOLIO TEST. A product of its own, or -- where the corpus only ever names model
    # designations -- the client's archive. `sector` may CONFIRM a band but never carry the
    # row alone: measured, sector-only admits were four rows and three of them were wrong
    # (Firestorm Labs' product is a 3D-printing factory, not an aircraft; MARSS and LBA are
    # a C-UAS and an unknown). A company whose evidence names no product in any KSSL
    # category has not shown it competes with KSSL.
    bands = {gate_band(p) for p in prods} | archive_bands(name)
    bands.discard(None)
    if not bands:
        if all(out_of_business(p) for p in prods):
            return False, ("makes aircraft/ships/sensors/protection, not KSSL's business "
                           "(%s)" % ", ".join(prods[:2]))
        return False, "nothing in KSSL's nine categories (%s)" % ", ".join(prods[:3])
    sector_band = gate_band(prof.get("sector"))
    if sector_band:
        bands.add(sector_band)
    return True, "rival in %s" % ", ".join(sorted(bands))


def load_profiles(cur):
    """Profiled pipeline companies, from the DB (so --only steps stay independent)."""
    cur.execute("""SELECT comp_id, ord, name, dir, hq, products
                     FROM serving.competitors WHERE origin='pipeline' ORDER BY ord""")
    return [{"comp_id": r[0], "ord": r[1], "name": r[2], "dir": r[3], "hq": r[4],
             "products": product_names(r[5])} for r in cur.fetchall()]


def step_companies(cur, con, docs, props_by_doc, limit=None):
    # Carry interim OSINT columns (agent-populated leadership/facilities, and hq where
    # the corpus has none) across the rebuild. This step DELETEs+re-INSERTs pipeline
    # competitors from the corpus and its INSERT does not carry those columns, so
    # without this snapshot every enrich pass silently wipes them (the Adani-empty bug).
    # `partners` is on that list too, and the INSERT below writes NULL rather than the
    # '[]' it used to: COALESCE only fills a column the rebuild left empty, so an empty
    # array would have beaten the carried value and the tie data would still be lost.
    # roster.CARRIED_COLUMNS is the single list; the old inline one named three columns
    # and `sales` was not among them, so the harvest wrote annual revenue and the next
    # pass deleted it -- 0 of 42 on the tab for a field that had already been extracted.
    _carry = roster.carry_snapshot(cur)
    # Own range only: revive_partners writes companies the crawl never profiled at
    # ord >= REV_ORD0. A blanket delete took them, and their ties, with it.
    # Snapshot the WHOLE row, not just the interim columns above. The roster is rebuilt
    # from zero every pass and a company reappears only if its ONE profile call succeeds,
    # so a farm timeout silently deleted curated rivals: Leonardo sat at 84 signal cards
    # and no competitor row, and the Competitor tab disagreed with its own feed. The
    # carry-forward after the INSERT puts a curated row back when its call fails.
    cur.execute("""SELECT comp_id, to_jsonb(c) FROM serving.competitors c
                    WHERE origin='pipeline' AND ord < %s""", (REV_ORD0,))
    _prev = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("DELETE FROM serving.competitors WHERE origin='pipeline' AND ord < %s",
                (REV_ORD0,))
    cur.execute("SELECT company FROM serving.signal_card WHERE origin='pipeline'")
    card_companies = {r[0] for r in cur.fetchall() if r[0]}

    ref_names = reference_names()
    candidates = set(card_companies)
    for n in ref_names:
        dids, _ = company_mentions({n}, docs, props_by_doc)
        if len(dids) >= 2:
            candidates.add(n)
    merged = merge_candidates(candidates)
    print("companies: %d candidate(s) after merge (%d card compan(ies), %d raw)"
          % (len(merged), len(card_companies), len(candidates)), flush=True)
    # Filter BEFORE profiling: every survivor costs one LLM profile call, and the run
    # that prompted this was making 324 of them to build a 425-company roster nobody
    # asked for.
    merged = apply_roster_allowlist(cur, merged)

    patterns, _comp = load_terms()
    cutoff, cur_year = recent_cutoff()
    rows, refused, no_props, over_limit, calls, not_company = [], 0, 0, 0, 0, 0
    not_competitor, why_counts = 0, {}
    # PLAN every model call first, then run them TOGETHER. The profile call IS the cost of
    # this step -- everything around it is in-memory filtering over docs already loaded --
    # and issuing them one at a time is why a rebuild crawls: the serving node advertises
    # six slots and this step kept exactly one of them busy.
    #
    # Only the calls are parallel. Everything below stays sequential and in the SAME order
    # as before, because the ord numbering and the client/dedup rules depend on that order.
    plan = []
    for name, aliases in sorted(merged.items()):
        if is_force(name) or not is_one_org(name):
            not_company += 1     # a country/government/ministry/armed force, or two orgs
            continue
        dids, cprops = company_mentions(aliases, docs, props_by_doc)
        if not cprops:
            no_props += 1
            continue
        if limit and len(plan) >= limit:
            over_limit += 1
            continue
        use = spread_statements(cprops)
        plan.append({
            "name": name, "dids": dids, "use": use,
            "lines": "\n".join(prop_line(pr, docs[did]["url"]) for did, pr in use),
            "hay": " ".join("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])
                            for _d, pr in use).lower(),
        })
    calls = len(plan)

    def _profile(item):
        """One profile call. Returns the exception rather than raising it, so one bad
        company cannot take the whole batch down with it."""
        try:
            return item, _ask(PROFILE_PROMPT % (item["name"], item["name"],
                                                item["name"], item["lines"])), None
        except Exception as e:                                    # noqa: BLE001
            return item, None, e

    if plan:
        print("companies: %d profile call(s), %d at a time"
              % (len(plan), min(ENRICH_WORKERS, len(plan))), flush=True)
        with ThreadPoolExecutor(max_workers=min(ENRICH_WORKERS, len(plan))) as ex:
            answers = list(ex.map(_profile, plan))
    else:
        answers = []

    for item, raw, err in answers:
        name, dids, use, hay = item["name"], item["dids"], item["use"], item["hay"]
        if err is not None:
            refused += 1
            print("  %s: %s" % (name, err), flush=True)
            continue
        prof = parse_profile(raw, hay, name)
        if prof is None:
            refused += 1
            continue
        # The model's threat word is an opinion, not a rating: it answered 'high' for
        # every rival. The stored rating is measured, and carries its measurement.
        if prof["dir"] == "rival":
            prof["threat"], prof["threat_note"] = rate_threat(prof["products"],
                                                              len(dids))
        else:
            prof["threat"], prof["threat_note"] = None, None
        if is_client(name):
            prof["dir"] = "client"
            prof["threat"] = None        # the client group is never a threat to itself
            prof["threat_note"] = None
        # THE COMPETITOR TEST. Everything above profiles the company; this decides whether a
        # competitor is what it is. Checked before the update lines below, which are the
        # expensive part and are wasted on a row that is not going to be written.
        admit, why = competes_with_kssl(prof, name)
        if not admit:
            not_competitor += 1
            why_counts[why.split(" (")[0]] = why_counts.get(why.split(" (")[0], 0) + 1
            continue
        # dated recent docs -> update lines (recency rule: updates are CLAIMS)
        updates = []
        for did in dids:
            ymd = article_date(cur, did)
            if not (ymd and is_recent_ym(ymd[:2], cutoff, cur_year)):
                continue
            props_t = [(pr["s"], pr["p"], pr["o"]) for pr in props_by_doc.get(did, [])]
            if usable_update(docs[did]["url"], docs[did]["title"], patterns, props_t):
                updates.append(((ymd[0], ymd[1] or 0, ymd[2] or 0),
                                {"t": date_label(ymd),
                                 "d": esc(clip(docs[did]["title"] or did, 110))}))
        updates = [u for _k, u in sorted(updates, key=lambda x: x[0], reverse=True)][:6]
        # The UI renders competitors.updates as an HTML string (UI_CONTRACT s8.3);
        # a list of dicts prints as [object Object]. Same dated {t,d} events, as HTML.
        upd_html = "".join("<div><b>%s</b> — %s</div>" % (u["t"], u["d"])
                           for u in updates)
        srcs, seen_u = [], set()
        for did, _pr in use:
            u = docs[did]["url"]
            if u and u not in seen_u:
                seen_u.add(u)
                srcs.append({"label": docs[did]["source"], "url": u})
        site = None
        tok = next((t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 4),
                   None)
        for did in dids:   # company-owned domain among its own docs -> site
            u = docs[did]["url"] or ""
            m = re.match(r"https?://([^/]+)", u)
            if m and tok and tok in m.group(1).lower():
                site = "https://" + m.group(1)
                break
        rows.append({"name": name, "prof": prof, "updates": updates,
                     "upd_html": upd_html,
                     # built HERE because `use` -- the statements this profile was read
                     # from -- is in scope only inside this loop; the INSERT below is a
                     # second pass over `rows` and no longer has them.
                     "products": product_rows(prof["products"], use, docs),
                     "srcs": srcs[:8], "site": site})

    rows.sort(key=lambda r: (0 if r["prof"]["dir"] == "rival" else 1,
                             r["name"].lower()))
    for i, r in enumerate(rows, start=1):
        p = r["prof"]
        cid = slug(r["name"])
        cur.execute("""INSERT INTO serving.competitors
                         (comp_id, ord, name, dir, sector, hq, threat, assess, updates,
                          center, partners, site, srcs, products, "threatNote", origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,
                               'pipeline')
                       ON CONFLICT (comp_id) DO NOTHING""",
                    (cid, ORD0 + i, esc(r["name"]), p["dir"], esc(p["sector"]) or None,
                     esc(p["hq"]) or None, p["threat"], esc(p["assess"]),
                     json.dumps(r["upd_html"] if r["updates"] else []),
                     json.dumps({"id": cid, "label": r["name"]}),
                     r["site"], json.dumps(r["srcs"]),
                     json.dumps(r["products"]),
                     p.get("threat_note")))
    # Put back any CURATED company this pass failed to rebuild. Only allowlisted names:
    # a company nobody chose to track should still fall off when the corpus stops
    # mentioning it -- this protects the curated roster, it does not freeze the table.
    _rk = roster.keys(cur)
    carried = 0
    if _rk:
        for _cid, _row in _prev.items():
            if not roster.on_roster(_row.get("name") or "", _rk):
                continue
            cur.execute("SELECT 1 FROM serving.competitors WHERE comp_id=%s", (_cid,))
            if cur.fetchone():
                continue
            cur.execute("""INSERT INTO serving.competitors
                           SELECT (jsonb_populate_record(
                                     NULL::serving.competitors, %s::jsonb)).*
                           ON CONFLICT (comp_id) DO NOTHING""",
                        (json.dumps(_row),))
            carried += cur.rowcount
    if carried:
        print("companies: carried %d curated row(s) forward (not rebuilt this pass)"
              % carried, flush=True)

    # Restore the snapshotted interim columns onto the freshly-rebuilt rows.
    _restored = roster.carry_restore(cur, _carry)
    if _restored:
        print("companies: restored curated columns on %d row(s)" % _restored, flush=True)
    con.commit()
    print("companies: %d written, %d refused, %d skipped no-props, %d not a company, "
          "%d not a competitor, %d over limit"
          % (len(rows), refused, no_props, not_company, not_competitor, over_limit),
          flush=True)
    # Say WHY the gate refused, per reason. A silent filter that halves the table is
    # indistinguishable from a broken query the next time someone asks where a rival went.
    for why, n in sorted(why_counts.items(), key=lambda kv: -kv[1]):
        print("  not a competitor -- %s: %d" % (why, n), flush=True)
    return {"written": len(rows), "refused": refused, "no_props": no_props,
            "not_company": not_company, "not_competitor": not_competitor,
            "why": why_counts, "over_limit": over_limit}


# --------------------------------------------------------------- step 2: partnerships

# WHAT IS EVEN WORTH ASKING ABOUT. This runs on the predicate alone, so it decides
# which relationships the tab can ever contain -- a verb missing here is a partnership
# type that does not exist as far as this pipeline is concerned.
#
# It used to hold only the announcement vocabulary: partner, JV, MoU, alliance,
# agreement, teaming, collaboration, licence. Every supply, manufacturing, distribution
# and R&D word was absent, so "X supplies engines to Y" and "X manufactures the hull
# under contract to Y" were never nominated -- the `supply` relationship could only be
# reached when an announcement word happened to appear in the same predicate. The tab
# had a supplier category that the corpus could not populate.
#
# The additions come from revive_partners.REL_RX, which had the right vocabulary all
# along and is wired to nothing.
PART_RX = re.compile(
    r"(partner|joint venture|\bjv\b|\bmou\b|memorandum|alliance|\bagreement|"
    r"team(?:ed|ing|s)? up|collaborat|tie-?up|joint bid|licen[cs]|consortium|"
    # supply and manufacture
    # `manufactur\w* for` was wrong: the object sits between the verb and the
    # preposition ("manufactures the airframe for KNDS"), so the two are almost never
    # adjacent. Same shape as builds/produces below.
    #
    # EVERY TAIL IS \bfor\b, NOT `for`. Without the boundary, `.{0,30}for` matches the
    # start of "forces", "forgings", "foreign" and "forward" -- in a defence corpus
    # "builds up its forces" and "produces armoured forgings" both nominated, and paid
    # for a model call each. Same reason `suppl(?:y|ies|ied|ier)` now excludes "supply
    # chain" and "supplies of", and `distribut` excludes "distributes dividends":
    # these were measured over-matches, not hypotheticals.
    r"suppl(?:y|ies|ied|ier)(?!\s+(?:chain|of\b))|subcontract|contract manufactur|"
    r"manufactur\w* .{0,30}\bfor\b|assembl\w* .{0,30}\bfor\b|"
    r"builds? .{0,30}\bfor\b|produces? .{0,30}\bfor\b|"
    # co-development and research
    r"co-?develop|co-?produc|co-?design|jointly develop|joint(?:ly)? research|"
    # distribution and integration. `\bdealers?\b` and `\bdistribut` keep "dealership"
    # and "distribution agreement" while dropping "distributed the report".
    # LONGEST ALTERNATIVE FIRST: written `distribut(?:e|es|ed|or|ion)` the engine
    # matches "distribute" inside "distributed" and any trailing test then looks at
    # the wrong character.
    #
    # NO NEGATIVE LOOKAHEAD HERE, deliberately. One was tried, to drop "distributed
    # the report" and "distributes dividends" -- and it also dropped "distributes the
    # system for" and, because `(?:the|a|...)` has no boundary of its own, every
    # "distribution agreement with". Separating a distribution TIE from a distributed
    # REPORT needs the sentence, not the verb, and the model is the thing that reads
    # the sentence. The cap is what pays for the residue: none of these over-matches
    # is in PART_STRONG_RX, so they rank last and are the first statements dropped.
    r"distribut(?:ion|ors?|es|ed|e)|resell|\bdealers?\b|"
    r"channel partner|integrat\w* .{0,30}\binto\b|"
    r"selected .{0,40}to suppl)", re.I)

# THE TEN TYPES THE TAB IS FOR, and the label each one prints. `rel` is the key the
# frontend colours by; `ptype` is what a reader sees. The old vocabulary was six values
# in which manufacturing, distribution, R&D, integration and licensing had nowhere to go
# -- they all landed on `tech` or `other`, so the tab could not tell a contract
# manufacturer from a technology transfer.
PART_TYPES = {
    "supply":        "Supply agreement",
    "manufacturing": "Manufacturing",
    "technology":    "Technology / ToT",
    "licensing":     "Licensing",
    "rnd":           "R&D / research",
    "distribution":  "Distribution / reseller",
    "jv":            "Joint venture",
    "integration":   "Integration / platform",
    # ONE catch-all, and it is last. There were two -- `strategic` and `other` -- with
    # descriptions the model could not tell apart ("an MoU with no narrower type" vs
    # "a partnership none of the above describes"), so a museum sponsorship landed on
    # `other` and 61% of everything else on `strategic`. Removing the catch-all
    # ALTOGETHER is worse: measured, the model already over-commits when it has one
    # (`manufacturing` for a supply tie), and a specific wrong label beats a vague true
    # one only if you never have to read it. `other` stays in REL_PTYPE for old rows.
    "strategic":     "Partnership / MoU",
}

# THE RELATIONSHIPS THAT ARE NOT PARTNERSHIPS. The model is asked to NAME these rather
# than answer NONE, because "the tab shows things that are not partnerships" and "the
# corpus is quiet" look identical in a log that only counts refusals. Each one was
# visible on the dashboard on 2026-09-06:
#
#   acquisition  Adani/Alpha Design and Adani/General Aeronautics, both typed
#                "Acquisition / stake". Ownership has its own home -- serving.
#                competitor_structure, filled by step_structure from these same
#                propositions with an ownership prompt that explicitly excludes
#                partnerships. Storing it here duplicated the claim under a name that
#                said the opposite.
#   customer     Adani/Indian Navy, typed "Supply / customer" -- one bucket for a
#                supplier and a buyer, which are opposite relationships.
#   investment   capital is not a business relationship of this kind.
#   award        a procurement outcome, not an alliance.
#
# Kept OUT of PART_TYPES on purpose: a value in both maps would be storable.
PART_NOT_A_TIE = {
    "acquisition": "ownership -- step_structure owns it",
    "customer":    "a sale, not a partnership",
    "investment":  "capital, not a partnership",
    "award":       "a procurement outcome, not a partnership",
}

PART_PROMPT = """Below is ONE extracted statement from a defence-news article, with its
supporting quote. Decide what business relationship, if any, it states between two
NAMED organizations.

Reply exactly NONE if: either side is not a named organization; the statement only
mentions both without stating a relationship; the tie is announced intent with no named
counterpart; the two sides are the same company or one is part of the other; or the
quote does not support it.

THESE ARE NOT PARTNERSHIPS. If the statement describes one, say so in `rel` using the
word given:
  acquisition  - one buys, merges with, or takes a stake in the other
  customer     - the buyer is the END USER: an armed force, government, agency, airline
                 or operator that will USE the product. A COMPANY buying parts, work or
                 services to build into its own product is NOT a customer -- that is
                 `supply` or `manufacturing`, with `a` as the side doing the work.
  investment   - one funds the other
  award        - a government or agency picks a winner for a programme

DECIDE `rel` IN THIS ORDER. Stop at the first that fits:
   1  the text names a jointly owned company or a joint venture     -> jv
   2  one makes or assembles something for the other                -> manufacturing
   3  one supplies parts, subsystems or services to the other       -> supply
   4  one licenses the other's design or intellectual property      -> licensing
   5  technology transfer, ToT, or shared engineering               -> technology
   6  they research or develop something NEW together               -> rnd
   7  one fits its product into the other's platform                -> integration
   8  one sells, resells or distributes the other's product         -> distribution
   9  ONLY if the text names the agreement (MoU, LOI, alliance, teaming,
      "collaboration") but says NOTHING about what they will do     -> strategic

Reply with ONLY this JSON, in ENGLISH:
{"a": "<organization 1 -- ONE name, never 'X and Y'>",
 "b": "<organization 2 -- ONE name, never 'X and Y'>",
 "rel": "<one of: jv | manufacturing | supply | licensing | technology | rnd |
          integration | distribution | strategic | acquisition | customer |
          investment | award>",
 "basis": "<the words from the Quote that decided `rel`, copied VERBATIM, at most 15
           words. If nothing in the Quote states what they do together, use rule 9.>",
 "note": "<one line stating what was agreed, exactly as the quote says -- an MoU is not
          a contract, a plan is not a delivery>",
 "status": "<active if it is in force; ended if the quote says it has ended, was
            dissolved or expired; announced if it is signed but not yet operating>",
 "date": "<date the relationship STARTED, ONLY if stated, else null>",
 "ended": "<date it ENDED, ONLY if the quote says it ended, else null>",
 "country": "<country of organization b ONLY if stated, else null>"}

If the statement ties THREE or more organizations, pick the one pair the quote actually
binds; if no single pair is asserted, reply NONE.

Article: %s
Statement: %s %s %s
Quote: "%s"
"""


# WHAT THE MODEL'S OWN `basis` SPAN MUST CONTAIN for a narrow type to stand. Run on the
# SPAN, never on the quote: a 300-character defence quote contains "technology" and
# "develop" almost unconditionally, so gating the quote passes everything. A fifteen-word
# span the model had to copy out cannot be vacuous the same way -- and `_in_hay` proves
# it was really copied rather than invented.
#
# DOWNGRADE, NEVER REFUSE. A mis-typed tie is still a tie; vague and true beats specific
# and wrong. This stops a FABRICATED type (jv or licensing with nothing behind it); it
# does not stop a misreading where the vocabulary is genuinely present.
# MEASURED, THEN NARROWED TO THREE. The first version gated all eight narrow types and
# made the labelling WORSE: on the same 80 statements the catch-all went from 57% to
# 80%, `technology` from 4 to 0 and `supply` from 5 to 1. Reading the seven downgrades
# says why -- the model's basis quotes the CONTEXT that decided the type, not the type's
# own keyword. "Combined with Rheinmetall's capabilities" is a real technology tie;
# "we are also the prime contractor" is a real supply tie; neither contains the word the
# gate was looking for.
#
# So it now guards only the three types with lexis distinctive enough that a basis
# lacking it means the label was invented rather than read -- which is what the gate was
# ever for. jv is the consequential one: it asserts a jointly owned company, and two
# equity purchases reached the live tab wearing it. The other five keep their answer;
# `basis` is still parsed and stored for every type, as the evidence for the LABEL that
# the tab has never had.
PART_BASIS_RX = {
    "jv":           re.compile(r"joint venture|\bjv\b|jointly (?:owned|held)", re.I),
    "licensing":    re.compile(r"licen[cs]", re.I),
    "distribution": re.compile(r"distribut|resell|dealer|channel", re.I),
}

def _as_of_str(ymd):
    """article_date returns (y, m|None, d|None). Stored as a STRING -- "2010",
    "2010-03", "2010-03-15" -- because a three-element array in jsonb is something the
    reader has to reassemble, and the only consumer is a line of text on a card."""
    if not ymd:
        return None
    y = ymd[0] if isinstance(ymd, (list, tuple)) else ymd
    if not y:
        return None
    parts = [str(int(y))]
    for i in (1, 2):
        v = ymd[i] if isinstance(ymd, (list, tuple)) and len(ymd) > i else None
        if not v:
            break
        parts.append("%02d" % int(v))
    return "-".join(parts)


def _trim_name(name):
    """Punctuation a company name never ends in. Run BOTH before and after canon_name:
    the suffix fold is what leaves the comma behind."""
    return re.sub(r"[\s,;:.\-]+$", "", str(name or "")).strip()


def _basis_in(span, hay):
    """Was this span really COPIED out of the evidence, or invented to justify a label?

    Not `_in_hay`: that needs a designator or two content tokens of four characters, so
    a true two-word basis ("supply", "joint venture") could never pass it. The prompt
    asks for the words VERBATIM, so verbatim is the test -- normalised for whitespace
    and case, and nothing else. A model that paraphrases instead of copying fails here,
    which is the correct answer to "show me the words".
    """
    if not span or not hay:
        return False
    n = lambda t: re.sub(r"[^a-z0-9]+", " ", str(t).lower()).strip()
    sp, h = n(span), n(hay)
    return bool(sp) and sp in h


# A jointly owned company, as words. Used to tell an acquisition from a JV in a note
# that carries ownership language: both are ownership, only one is a tie.
JV_RX = re.compile(r"(joint venture|\bjv\b|jointly (?:owned|held))", re.I)

# OWNERSHIP WORDS OWN_RX DOES NOT CARRY. It requires a qualifier -- "majority stake",
# "controlling shareholding" -- or an `acquir*` verb, so the live tab's own wording,
# "Strategic stake in drone company", matched nothing and was published as a JOINT
# VENTURE. Kept local to this step rather than widened into OWN_RX: that regex is
# step_structure's candidate filter over the whole corpus, and changing what it selects
# is a separate measurement from fixing what this step stores.
PART_OWN_RX = re.compile(r"\bstakes?\s+in\b|\bequity\b|\bshareholding\b", re.I)

# A museum, a charity or a trade body is a sponsorship or a membership, not a business
# partnership. Universities, institutes and research councils are deliberately NOT here:
# CSIR, the Kyiv School of Economics and Aalto-yliopisto are real R&D counterparties.
NONCOMMERCIAL_RX = re.compile(
    r"\b(museum|foundation|charit\w*|association|federation|chamber of)\b", re.I)


# Function words that mark English prose. Single-character tokens are excluded on
# purpose: Hungarian 'a' is also English 'a', and it was the only "English" word in an
# untranslated Hungarian note that also misquoted its source (audit M10).
_EN_FUNC = {
    "the", "and", "for", "with", "from", "that", "this", "have", "has", "had", "will",
    "was", "were", "are", "its", "their", "into", "over", "under", "after", "before",
    "between", "through", "against", "about", "which", "been", "also", "not", "but",
    "than", "then", "when", "while", "both", "each", "other", "more", "of", "to", "in",
    "on", "by", "at", "as", "an", "is", "be", "it", "or", "we", "they", "he", "she",
    "would", "under", "within", "including", "per", "up",
}


def is_english(text, min_tok=5):
    """The prompt asks for an English one-liner; a verbatim foreign quote belongs in
    the evidence, not in a label. Also enforces a MINIMUM length: 'collaborates' is
    not a statement of what was agreed."""
    toks = [t for t in re.findall(r"[^\W\d_]+", str(text or "").lower(), re.UNICODE)
            if len(t) >= 2]
    if len(toks) < min_tok:
        return False
    letters = [c for c in str(text) if c.isalpha()]
    if letters and sum(1 for c in letters if ord(c) > 127) / len(letters) > 0.12:
        return False                      # mostly non-ASCII letters -> not English
    hits = sum(1 for t in toks if t in _EN_FUNC)
    return hits >= (1 if len(toks) <= 8 else 2)


def parse_partnership(raw, hay=None, name_hay=None):
    """-> dict or None. `rel` may be one of PART_TYPES (storable) or PART_NOT_A_TIE
    (a real relationship that is not a partnership); the caller decides which.

    Returning the excluded kinds rather than None is deliberate. A silent NONE makes
    "the model correctly refused an acquisition" indistinguishable from "the model saw
    nothing", and the acquisitions on the tab were never noticed because nothing counted
    them.

    TWO HAYSTACKS, because the two checks ask different questions. The ORGANISATIONS
    must come from the statement itself (`name_hay` = subject/predicate/object): a name
    that appears only in the surrounding quote is a co-mention, and that is how
    "Lockheed Martin <-> NATO" was manufactured out of "Lockheed Martin has been a
    strategic partner in Europe". The BASIS is copied out of the quote by definition, so
    it is checked against the wider `hay`. `name_hay` defaults to `hay`, which is the
    old single-haystack behaviour.
    """
    d = _json_reply(raw)
    if d is None:
        return None
    a, b = _s(d.get("a"), 90), _s(d.get("b"), 90)
    note = _s(d.get("note"), 300)
    rel = (_s(d.get("rel"), 16) or "").lower()
    if not a or not b or not note:
        return None
    # "Merlin," -- the model copies a name out of "Merlin, Inc." and keeps the comma.
    # _s strips whitespace and nothing else, so the punctuation reached the tab.
    a, b = _trim_name(a), _trim_name(b)
    if not a or not b:
        return None
    if not is_one_org(a) or not is_one_org(b):
        return None                       # 'X and Y' in one field is two orgs, refused
    # A PHRASE IS NOT A FIRM. aliases.is_description reads the capitalisation shape --
    # a name capitalises throughout, a phrase carried out of a sentence does not. It
    # existed for the roster and was never applied here, so "Australian industry" was
    # stored as a supply partner of Kongsberg.
    #
    # ONLY ON MULTI-WORD NAMES. is_description splits on non-word characters, so a
    # hyphenated single word reads as "capitalised then lowercase" and it calls
    # "Aalto-yliopisto" a description -- a Finnish university this file's own tests
    # already pin as a real R&D counterparty. A description is a phrase; a phrase has
    # a space in it.
    if (" " in a and is_description(a)) or (" " in b and is_description(b)):
        return None
    # A museum is a sponsorship, not a business relationship: "Patria partners with the
    # Finnish Aviation Museum" is true, and is not competitive intelligence.
    if NONCOMMERCIAL_RX.search(a) or NONCOMMERCIAL_RX.search(b):
        return None
    if is_force(a) or is_force(b):
        return None                       # 'den brasilianska regeringen' is not a
    # A COUNTRY IS NOT AN ORGANISATION. serving_fill.country_names() exists for exactly
    # this -- its own docstring says "'Thailand', 'Australia' and 'India' all reached
    # signal_card.company" -- and it was never applied to a partnership side. Probing
    # the live 14b against the real corpus stored "Paramount Group <-> Kazakhstan" as
    # a strategic partnership and "Elbit Systems <-> Australia" as a customer: the
    # country is the market or the buyer, never the partner.
    _cn = country_names()
    if fold_name(a) in _cn or fold_name(b) in _cn:
        return None
    if not has_proper_name(a) or not has_proper_name(b):
        return None                       # NAMED organization -- the prompt's own rule
    if not is_english(note):
        return None                       # one-word / untranslated notes are labels
    _nh = name_hay if name_hay is not None else hay
    if _nh is not None and not (_in_hay(a, _nh) and _in_hay(b, _nh)):
        return None                       # both orgs must come from the STATEMENT
    # AND AGAIN AFTER CANONICALISATION, because canon_name is what CREATES the problem:
    # "Merlin, Inc." trims to "Merlin, Inc", then the legal-suffix fold drops "Inc" and
    # hands back "Merlin," with the comma restored. Trimming only on the way in looked
    # like a fix and shipped the same broken name -- measured on the live 14b, twice.
    a, b = _trim_name(canon_name(a)), _trim_name(canon_name(b))
    if not a or not b:
        return None
    if slug(a) == slug(b):
        return None
    # ONE CORPORATE FAMILY IS NOT A TIE. "Nammo Cheltenham supplies Nammo" and
    # "Rheinmetall / American Rheinmetall Munitions" are ownership, and a reader would
    # not call either a partnership. Containment either way, on folded names.
    _fa, _fb = fold_name(a), fold_name(b)
    if _fa and _fb and (word_rx(_fa).search(_fb) or word_rx(_fb).search(_fa)):
        return None
    if rel not in PART_TYPES and rel not in PART_NOT_A_TIE:
        return None
    # THE MIRROR OF parse_structure's GUARD, which has kept partnership language out of
    # ownership since it was written -- and had no counterpart, so ownership language
    # flowed freely the other way. Checked on the NOTE, exactly as the original does:
    # the hand-written rows had precisely this shape, `rel: jv` over a note reading
    # "Strategic stake in drone company". A joint venture is jointly OWNED, so it is
    # the one ownership word that stays a tie.
    if (OWN_RX.search(note) or PART_OWN_RX.search(note)) and not JV_RX.search(note):
        rel = "acquisition"
    # THE MODEL'S OWN EVIDENCE FOR THE TYPE. A narrow type has to be able to point at
    # the words it came from; one that cannot is a guess wearing a specific label.
    basis = _s(d.get("basis"), 160) or ""
    downgraded = False
    _brx = PART_BASIS_RX.get(rel)
    if _brx is not None and not (_brx.search(basis)
                                 and (hay is None or _basis_in(basis, hay))):
        rel, downgraded = "strategic", True
    # A tie the source says is over is still worth showing -- as over. It had no
    # representation at all before, so the only way to say it was to write it into the
    # type label, which is how "Historical Joint Venture (Ended 2013)" came to render
    # as a live alliance edge identical to the current ones.
    status = (_s(d.get("status"), 12) or "").lower()
    # A DATE HAS A DIGIT IN IT. `_s` nulls "null"/"none"/"n/a" and nothing else, so a
    # model answering the "else null" instruction with "ongoing", "no", "-", "present"
    # or "not applicable" produced a truthy `ended` -- and the rule below then read
    # that as a stated end date and flipped a live joint venture to ended. Measured:
    # 'ongoing', 'no', 'not applicable', '-' and 'present' all did exactly that.
    # A bare number is the opposite mistake: _s refuses non-strings, so the model
    # answering {"ended": 2013} lost a real end year.
    _raw_end = d.get("ended")
    if isinstance(_raw_end, (int, float)) and not isinstance(_raw_end, bool):
        _raw_end = str(int(_raw_end))
    ended = _s(_raw_end, 40)
    if ended and not any(c.isdigit() for c in ended):
        ended = None
    if status not in ("active", "ended", "announced"):
        status = "ended" if ended else "active"
    if ended and status != "ended":
        status = "ended"                  # a stated end date outranks a guessed status
    return {"a": a, "b": b, "rel": rel, "note": note, "status": status,
            "ended": ended, "basis": basis, "downgraded": downgraded,
            "date": _s(d.get("date"), 40), "country": _s(d.get("country"), 60)}


def tie_confidence(urls, side):
    """-> (confidence, why). The publishability rule already grades the source; this
    step called it and threw the verdict away, keeping only the prose.

    `publishable` returns (ok, why, tier, n_independent) and `ok` was assigned to a
    variable nothing read, so a tie from one anonymous blog and a tie stated by the
    manufacturer were stored identically and the UI had nothing to tell them apart
    with. Three values, because that is what the rule actually distinguishes.
    """
    ok, why, tier, n = publishable(urls, side)
    if tier == "official":
        return "official", why
    if ok and (n or 0) >= 2:
        return "corroborated", why
    return "single_source", why


# The label a reader sees, keyed by `rel`. PART_TYPES is the definition; the six legacy
# keys stay so rows written before 2026-09-06 still print a label instead of their raw
# key. `supply` deliberately no longer says "Supply / customer" -- a supplier and a
# buyer are opposite relationships and that one bucket held both.
REL_PTYPE = dict(PART_TYPES)
REL_PTYPE.update({"tech": "Technology / ToT", "mou": "MoU / strategic",
                  "acq": "Acquisition / stake", "other": "Partnership"})

# How many statements ONE competitor is worth asking about in a single pass.
# See bucket_partnership_candidates for why a cap exists at all.
#
# A value of 0 or less is IGNORED rather than honoured. `if per_comp and ...` reads 0 as
# "no cap", so `KSSL_PART_PER_COMP=0` would have been an undocumented way to reinstate
# the unbounded pass this whole mechanism exists to prevent -- and it would have looked
# like a way to turn the feature off.
PART_PER_COMP = int(os.environ.get("KSSL_PART_PER_COMP") or 0) or 40
if PART_PER_COMP < 1:
    PART_PER_COMP = 40

# The client gets its own, larger budget. serving.partner -- the client's whole partner
# roster, and what the overlap read measures every rival against -- is deleted and
# rebuilt from scratch each pass out of this ONE bucket. A rival capped at 40 loses its
# 41st-strongest statement; the client capped at 40 loses part of the roster itself.
PART_CLIENT_CAP = int(os.environ.get("KSSL_PART_CLIENT_CAP") or 0) or 200

# Statements that assert a tie outright, as against ones that only imply it. Used to
# ORDER a competitor's statements so the cap above keeps the strongest -- never to gate
# them, because "collaborates with" is weak evidence and still evidence.
PART_STRONG_RX = re.compile(
    r"(joint venture|\bjv\b|\bmou\b|memorandum|\bagreement|licen[cs]|consortium|"
    r"partnership with|partnership between|partners with|partnered with|"
    r"signed|teamed up|tie-?up|"
    # THE NEW TYPES RANK TOO. Widening PART_RX without widening this one is how the
    # cap quietly undoes the widening: a genuine "supplies engines to" scored the same
    # as an over-match and lost the tie-break on quote length, so the very statements
    # the supply/manufacturing/distribution types were added for were the ones the cap
    # discarded first.
    r"subcontract|contract manufactur|co-?develop|co-?produc|"
    r"suppl(?:y|ies|ied|ier)(?!\s+(?:chain|of\b))|"
    r"distribut(?:or|ion)|resell|channel partner)", re.I)

# The client's own ties go to serving.partner, not to a competitor row, so they need a
# bucket of their own. Not a comp_id: no competitor may ever be called this.
CLIENT_BUCKET = "__client__"

# THE TWO STATEMENTS THAT DECIDE WHICH TIES SURVIVE A PASS, named so the test can run
# the ones that ship instead of a retyped copy that drifts. A drifted copy of the reset
# is exactly the failure that hides here: it would still look like a working test while
# production quietly doubled or deleted every tie.
#
# RESET: drop only what this writer put there. A revived tie and a hand-written one both
# carry a different `origin` (or none at all) and both stay. The old predicate was
# `p ? 'origin'`, which kept the ENRICHED rows too -- harmless only for as long as the
# step never reached its own commit.
#
# NEVER RUN UNSCOPED WHILE THE PASS IS IN FLIGHT. The two scoped forms below are what
# the step uses, and the reason is the whole point of the per-bucket commits: a global
# reset committed up front empties every competitor before the first model call, so an
# interrupted pass leaves the tab THINNER than it found it -- the opposite of the
# guarantee. A competitor is reset once, at the moment its first tie of this pass is
# written, inside the same transaction as that write.
_PART_RESET = """UPDATE serving.competitors
                    SET partners = coalesce((SELECT jsonb_agg(p)
                          FROM jsonb_array_elements(coalesce(partners,'[]'::jsonb)) p
                         WHERE p->>'origin' IS DISTINCT FROM 'enriched'), '[]'::jsonb)
                  WHERE origin='pipeline'"""
# One competitor, immediately before this pass's first write to it.
PART_RESET_ONE_SQL = _PART_RESET + " AND comp_id = %s"
# The sweep, and only on a COMPLETE pass: every competitor this pass found nothing for
# still holds last pass's ties, and a tie the corpus no longer supports must not live
# forever. A run that stopped early has not looked at them yet, so it must not judge
# them -- hence the caller's `if not stop`.
PART_RESET_REST_SQL = _PART_RESET + " AND NOT (comp_id = ANY(%s::text[]))"

# APPEND: add this batch in front of whatever the reset left. No second filter here --
# re-filtering on the way in is how the archive revival got erased the first time.
PART_APPEND_SQL = """UPDATE serving.competitors
                        SET partners = %s::jsonb || coalesce(partners, '[]'::jsonb),
                            updated_at = now()
                      WHERE comp_id=%s AND origin='pipeline'"""


def bucket_partnership_candidates(profiles, docs, props_by_doc,
                                  per_comp=PART_PER_COMP,
                                  client_cap=PART_CLIENT_CAP):
    """Which statements are worth one model call each, grouped by whose row the answer
    can land on.  -> ({bucket: [(document_id, prop)]}, stats)

    THE BOUND THAT MAKES THIS STEP FINISH. It used to take every proposition whose
    predicate matched PART_RX and ask the model about each one: 4,546 calls on the
    staging corpus, ~7,000 on production's, issued sequentially against a farm that
    fails over to a CPU box under load. Measured 2026-09-06: the production enrich
    container had been inside this one step for eight hours and had never once reached
    its own summary line. Nothing kills the pass -- entrypoint.sh runs it to completion
    and only then sleeps -- so this is not a timeout, it is a step that takes most of a
    day while steps 4-10 wait behind it, and that loses everything to any interruption
    in that window because the whole step used to commit once at the end.

    Two observations cut that to a few hundred without weakening a single answer:

      1. ONLY ASK WHAT CAN BE STORED. A tie lands on a competitor row (or on
         serving.partner, for the client). A statement naming neither is asked about,
         answered, parsed, gated -- and then counted as an orphan and dropped. Of the
         4,546 candidates, 1,448 name a tracked competitor or the client. The other
         3,098 calls were paid for and discarded before this function existed.

      2. THE SAME SENTENCE ARRIVES MANY TIMES. Wire copy is syndicated, and the same
         subject/predicate/object reaches the corpus from a dozen domains. Deduped per
         bucket, 1,448 becomes 1,397.

    The cap is what turns a bound into a guarantee: one competitor held 237 statements,
    and a corpus that grows makes that number grow with it. At 40 per competitor the
    whole step is 656 calls on staging -- roughly an hour -- and the number stops
    depending on how big the corpus gets. Statements are ordered by PART_STRONG_RX
    first, so what the cap discards is always the weakest evidence, and ties are broken
    on (document_id, subject) so the same corpus asks the same questions twice running.

    A bucket is not an assertion that the tie belongs to that competitor -- the model
    still names both sides and step_partnerships still lands the answer on whichever
    side it profiles, possibly both. The bucket only decides what is worth asking.

    THE CEILING THIS BUYS THE THROUGHPUT WITH, stated plainly. The ordering is
    deterministic, so a competitor over the cap is asked about the SAME strongest 40
    statements every pass, and the other 197 are never asked at all -- not "asked
    later". On the staging corpus that is 760 statements a pass, across the 19 buckets
    that hit the cap. Deliberate for now: the ranking puts the outright assertions
    first, and a tie that only ever appears in weak language is the one most likely to
    be refused anyway. The upgrade is not a bigger cap -- it is to remember which
    statements have already been judged and spend each pass's budget on the ones that
    have not, which needs a table this step does not have yet. `KSSL_PART_PER_COMP`
    raises the cap in the meantime, linearly in cost.
    """
    # The client is excluded from the competitor regexes on purpose. step_companies can
    # write a pipeline row with dir='client', and if it does, every statement naming
    # Bharat Forge would land in that row's bucket AND in CLIENT_BUCKET -- two model
    # calls for one statement, the second of which dies in seen_pairs AFTER it has been
    # paid for. Its ties belong in serving.partner either way.
    rxs = [(p["comp_id"], word_rx(p["name"])) for p in profiles
           if not is_client(p["name"])]
    client_rxs = [word_rx(m) for m in CLIENT_MARKS]
    buckets = {}
    n_cand = n_named = n_dup = 0
    for did in sorted(props_by_doc):
        if did not in docs:
            continue
        for pr in props_by_doc[did]:
            if not PART_RX.search(pr["p"] or ""):
                continue
            n_cand += 1
            hay = ("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])).lower()
            hits = [cid for cid, rx in rxs if rx.search(hay)]
            if any(rx.search(hay) for rx in client_rxs):
                hits.append(CLIENT_BUCKET)
            if not hits:
                continue
            n_named += 1
            for b in hits:
                buckets.setdefault(b, []).append((did, pr))

    # RANK FIRST, THEN DEDUPE, THEN CAP -- in that order, and the order is the point.
    # Deduping during collection would keep whichever copy the corpus happened to yield
    # first; ranking first means the survivor of a set of rewrites is the strongest
    # phrasing with the longest quote, which is the one most likely to be answerable.
    n_capped = 0
    for b, rows in buckets.items():
        rows.sort(key=lambda dp: (0 if PART_STRONG_RX.search(dp[1]["p"] or "") else 1,
                                  -len(dp[1]["q"] or ""), dp[0], dp[1]["s"] or ""))
        # KEYED ON THE TWO ENDS, NOT ON THE WHOLE SENTENCE. `seen_pairs` in
        # step_partnerships is keyed on the pair of organisations the model names, so a
        # second statement about the same two companies can never produce a second
        # stored tie -- it is a call paid for and then thrown away. Wire copy rewrites
        # the verb and leaves the ends alone: "is partnering with", "collaborates with"
        # and "partnered with" are all the same Rheinmetall/Lockheed tie, and an s+p+o
        # key treats each rewrite as a new question.
        #
        # MEASURED BEFORE ADOPTING, because it trades coverage for calls: on the
        # staging corpus it takes 1,456 uncapped calls to 1,376, and the 78 statements
        # it gives up sit in 63 (subject, object) groups. The twelve largest were read
        # by hand and every one was the same tie in different words. It is a 5% saving,
        # not a large one -- the value is that the cap below now counts roughly
        # "distinct counterparties" rather than "distinct sentences".
        # THE DUPLICATES ARE THE CORROBORATION. Dropping them outright made
        # `corroborated` unreachable: tie_confidence was called with the one surviving
        # document's url, so `publishable` never saw two independent domains and every
        # tie in the system graded `single_source` -- a three-value scale shipping as
        # two. The sibling documents are the evidence that the same pair is stated in
        # more than one place, which is exactly what the source bar asks. Carried on
        # the kept row rather than asked about again: one call, all the urls.
        seen, keep, alt = set(), [], {}
        for did, pr in rows:
            ends = (fold_name(pr["s"] or ""), fold_name(pr["o"] or ""))
            if ends in seen:
                n_dup += 1
                alt.setdefault(ends, []).append(did)
                continue
            seen.add(ends)
            keep.append((did, pr))
        for did, pr in keep:
            ends = (fold_name(pr["s"] or ""), fold_name(pr["o"] or ""))
            if alt.get(ends):
                # capped: the source bar needs two independent domains, not fifty
                pr["alt_docs"] = alt[ends][:8]
        cap = client_cap if b == CLIENT_BUCKET else per_comp
        if cap and len(keep) > cap:
            n_capped += len(keep) - cap
            keep = keep[:cap]
        buckets[b] = keep
    calls = sum(len(v) for v in buckets.values())
    return buckets, {"candidates": n_cand, "named": n_named, "duplicate": n_dup,
                     "over_cap": n_capped, "calls": calls,
                     "buckets": len(buckets)}


def owned_elsewhere(props_by_doc, did, pr):
    """-> the sibling proposition proving this pair is an ACQUISITION, or None.

    THE ONE ERROR CLASS THAT SAYS THE OPPOSITE OF THE TRUTH on the tab. Adani's 50%
    purchase of General Aeronautics reached the model as `Adani Defence & Aerospace |
    partnering with | General Aeronautics`, over a CEO quote saying "is partnering with
    us" -- and the model answered `strategic`, faithfully. The acquisition is stated in
    the SAME article, in a different proposition ("acquires | 50% equity stake in"),
    which the partnership question never sees.

    So look there before paying for the call. The predicate test is step_structure's own
    candidate rule (OWN_RX over predicate+object), scoped to THIS statement's two ends
    so a subsidiary aside about a third party cannot refuse a real tie -- measured on 33
    dumped ties, document-wide scope would have refused up to 10 of them and pair scope
    refuses exactly the one that is wrong.

    A compound subject ("Saab and Embraer") folds to a string that matches nothing here,
    so it is a miss and never a false refusal.
    """
    ends = [word_rx(fold_name(x)) for x in (pr.get("s"), pr.get("o"))
            if fold_name(x or "")]
    if len(ends) < 2:
        return None
    for sib in props_by_doc.get(did) or ():
        if sib is pr or not OWN_RX.search("%s %s" % (sib.get("p") or "",
                                                     sib.get("o") or "")):
            continue
        spo = fold_name("%s %s %s" % (sib.get("s") or "", sib.get("p") or "",
                                      sib.get("o") or ""))
        if all(rx.search(spo) for rx in ends):
            return sib
    return None


def step_partnerships(cur, con, docs, props_by_doc, limit=None):
    """Read partnership ties out of the corpus and land them on the competitor rows.

    COMMITS AS IT GOES, one flush per bucket. The old shape did every model call and
    then committed once at the very end, so anything that interrupted a pass -- a
    deploy, the farm dying, the DB socket dropping into run()'s retry -- threw away
    every tie it had found, across a window that was most of a day. Partial progress is
    the whole point: 30 competitors rewritten and 14 still holding last pass's ties
    beats 44 rolled back.

    Which is why the reset is PER COMPETITOR and inside the same transaction as the
    write that replaces it (see flush). A global reset committed up front would empty
    all 44 before the first model call, and an interrupted pass would then leave the
    tab emptier than it found it -- a worse outcome than the rollback it replaced.

    TWO THINGS THE COMMITS CHANGE FOR AN OPERATOR, neither of them new bugs but both
    newly reachable:

      * `--limit` IS NOT A DRY RUN. It used to be near enough to one, because nothing
        committed until the end and a Ctrl-C undid the lot. Now every bucket it gets
        through is written, and a complete run rebuilds serving.partner. Point it at
        staging, not at production, when smoke-testing.
      * A HAND-RUN SCRIPT CAN LOSE A FLUSH. revive_partners.py, discover_ties.py and
        mark_shared.py each SELECT the whole partners column and write it back. That
        raced with a single commit at the end of the pass for a moment; it now races
        with an hour of them. Run them when the enrich loop is stopped.
    """
    profiles = load_profiles(cur)
    if not profiles:
        print("partnerships: no profiled companies -- run companies first", flush=True)
        return {"written": 0, "refused": 0, "skipped": 0}
    prof_ids = {p["comp_id"] for p in profiles}
    prof_rx = [(p, [word_rx(p["name"])]) for p in profiles]

    buckets, bstats = bucket_partnership_candidates(profiles, docs, props_by_doc)
    print("partnerships: %d candidate prop(s) -> %d naming a tracked company "
          "(%d duplicate, %d over the %d/company cap) -> %d model call(s) "
          "across %d bucket(s)"
          % (bstats["candidates"], bstats["named"], bstats["duplicate"],
             bstats["over_cap"], PART_PER_COMP, bstats["calls"], bstats["buckets"]),
          flush=True)

    # One query for every document this pass may cite, rather than one per tie.
    _as_of = {}
    try:
        _dids = sorted({d for rows in buckets.values() for d, _p in rows})
        for _d in _dids:
            _as_of[_d] = _as_of_str(article_date(cur, _d))
    except Exception as e:                                            # noqa: BLE001
        print("partnerships: article dates unavailable (%s) -- ties will carry no "
              "as_of" % e, flush=True)

    reset_done = set()

    def flush(pending):
        """Write one bucket's ties and commit. THIS is the partial progress: a pass
        that dies keeps every bucket it finished, and every competitor it never reached
        keeps the ties it already had.

        The reset is per competitor and lives in the SAME transaction as the write that
        replaces it, so a competitor is never left holding nothing. Once per pass:
        a second bucket landing on the same competitor appends to the first."""
        n = 0
        for cid_, plist in pending.items():
            if not plist:
                continue
            if cid_ not in reset_done:
                cur.execute(PART_RESET_ONE_SQL, (cid_,))
                reset_done.add(cid_)
            cur.execute(PART_APPEND_SQL, (json.dumps(plist), cid_))
            n += cur.rowcount
        con.commit()
        return n

    found = refused = errored = calls = downgraded = 0
    seen_pairs, not_tie, by_type = set(), {}, {}
    client_rows, orphans, ownership, written_to = [], [], [], set()
    stop = False
    def _ask_one(item):
        """One model call, in a worker thread. Returns everything the sequential half
        needs, so nothing but the HTTP wait happens in parallel."""
        did_, pr_ = item
        try:
            return item, _ask(PART_PROMPT % (docs[did_]["title"] or did_, pr_["s"],
                                             pr_["p"], pr_["o"],
                                             clip(pr_["q"], 300)), npredict=300), None
        except Exception as e:                                    # noqa: BLE001
            return item, None, e

    for _bucket, rows in buckets.items():
        pending = {}
        # THE FREE REFUSALS FIRST. owned_elsewhere reads propositions already in memory,
        # so a pair the same article calls an acquisition never reaches the model.
        todo = []
        for did, pr in rows:
            _own = owned_elsewhere(props_by_doc, did, pr)
            if _own is not None:
                not_tie["acquisition"] = not_tie.get("acquisition", 0) + 1
                ownership.append("%s / %s (same article: %s %s)"
                                 % (pr["s"], pr["o"], _own.get("p"), _own.get("o")))
                continue
            todo.append((did, pr))
        if limit:
            room = max(0, limit - calls)
            if len(todo) > room:
                todo, stop = todo[:room], True

        # ENRICH_WORKERS AT A TIME, not one. The serving node offers six parallel slots
        # and this step used exactly one of them -- measured on the farm dashboard, the
        # pinned 14b sat at 2/6 running while a pass crawled through it single file at
        # 7.6 tok/s. step_companies has taken the node ENRICH_WORKERS-wide since it was
        # written; this is the same shape.
        #
        # ONLY THE HTTP WAIT IS PARALLEL. ex.map preserves input order, so the answers
        # are processed in exactly the order a sequential pass would have seen them --
        # seen_pairs, the flush order and the commits all stay deterministic, and the
        # cursor is still touched by one thread.
        answers = []
        if todo:
            with ThreadPoolExecutor(max_workers=min(ENRICH_WORKERS, len(todo))) as ex:
                answers = list(ex.map(_ask_one, todo))
            calls += len(todo)

        for (did, pr), raw, err in answers:
            if err is not None:
                # NOT a refusal. The farm 502s and fails over mid-pass, and counting an
                # outage as "the model said no" hides it inside a quality number.
                errored += 1
                print("  %s: %s" % (did, err), flush=True)
                continue
            hay = ("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])).lower()
            name_hay = ("%s %s %s" % (pr["s"], pr["p"], pr["o"])).lower()
            got = parse_partnership(raw, hay, name_hay=name_hay)
            if got is None:
                refused += 1
                continue
            if got.get("downgraded"):
                downgraded += 1
            # NOT A PARTNERSHIP, and named as such rather than silently dropped.
            # Acquisitions belong to step_structure, which mines these same
            # propositions with an ownership prompt; a customer, an investor and a
            # programme award are not business partnerships at all.
            if got["rel"] in PART_NOT_A_TIE:
                not_tie[got["rel"]] = not_tie.get(got["rel"], 0) + 1
                if got["rel"] == "acquisition":
                    ownership.append("%s / %s" % (got["a"], got["b"]))
                continue
            # off_portfolio() USED TO GATE HERE, and it was the wrong question. It
            # refuses any text naming a product class KSSL has no line in -- radar,
            # sonar, EW, optics, satcom, C4I -- which is a rule about what KSSL sells.
            # This tab is about who a COMPETITOR works with, and "Rheinmetall and
            # Hensoldt sign a radar supply agreement" is precisely the intelligence it
            # exists to carry. The gate stays where it belongs, on cards and matchups.
            key = frozenset((slug(got["a"]), slug(got["b"])))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            by_type[got["rel"]] = by_type.get(got["rel"], 0) + 1
            got["url"] = docs[did]["url"]
            got["source"] = docs[did]["source"]
            # Every document that stated this same pair, so the source bar can see
            # more than one domain. `url` stays the ONE citation a reader opens.
            got["urls"] = [docs[did]["url"]] + [docs[d]["url"] for d in
                                                pr.get("alt_docs") or []
                                                if d in docs]
            found += 1

            # LAND IT ON EVERY SIDE THAT HAS A ROW, not only on this bucket's company:
            # a tie between two tracked rivals belongs under both, and the bucket only
            # decided which statement was worth asking about.
            landed = False
            for side, other in ((got["a"], got["b"]), (got["b"], got["a"])):
                # The document this tie was read from IS its evidence, and it was being
                # thrown away: five ties reached the tab with no source at all, on a
                # page whose rule is that every tie carries one a reader can check.
                conf, why = tie_confidence(got["urls"], side)
                entry = {"id": slug(other), "label": esc(other),
                         "ptype": REL_PTYPE[got["rel"]], "rel": got["rel"],
                         "note": esc(got["note"]), "country": got["country"],
                         "date": got["date"], "src": got["url"],
                         # honest either way: an uncorroborated single source says so
                         "srcnote": why,
                         # the verdict, not just the prose about it
                         "confidence": conf,
                         # a tie the source says is over renders as over, instead of
                         # being written into the type label as "(Ended 2013)"
                         "status": got["status"], "ended": got["ended"],
                         # THE ONLY HONEST THING A 2010 ARTICLE CAN SAY. `status` is
                         # "as of this document", and without the document's date an
                         # alliance that collapsed in 2024 reads as current because a
                         # 2023 article called it active.
                         "as_of": _as_of.get(did),
                         # the words the model says decided the type, so a reader can
                         # check the LABEL and not only the tie
                         "basis": got.get("basis") or None,
                         "origin": "enriched"}
                if is_client(side):
                    client_rows.append((other, got))
                    landed = True
                cid = slug(side)
                if cid in prof_ids:
                    pending.setdefault(cid, []).append(entry)
                    landed = True
                else:   # alias form ("Bharat Forge Limited") -> boundary match
                    for p, rxs in prof_rx:
                        if any(rx.search(side.lower()) for rx in rxs):
                            pending.setdefault(p["comp_id"], []).append(entry)
                            landed = True
                            break
            if not landed:
                # Neither side is a profiled company or the client: the tie is real but
                # has nowhere to be shown. Counted and named, never silently dropped --
                # 'N ties found' used to be printed over ties nothing stored.
                orphans.append("%s / %s" % (got["a"], got["b"]))
        written_to.update(k for k, v in pending.items() if v)
        flush(pending)
        if stop:
            break

    # THE SWEEP. Competitors this pass found nothing for still hold last pass's ties,
    # and a tie the corpus no longer supports must not live forever. Only on a COMPLETE
    # pass: a run that stopped at its --limit has not looked at them.
    if not stop:
        cur.execute(PART_RESET_REST_SQL, (sorted(reset_done),))
        con.commit()

    # THE CLIENT'S OWN ROSTER, deleted and re-inserted in ONE committed transaction.
    # The delete used to open the step; with the per-bucket commits above that would
    # leave serving.partner empty for the whole pass, and empty for good if the pass
    # died before reaching here.
    cur.execute("DELETE FROM serving.partner WHERE origin='pipeline' AND ord < %s",
                (REV_ORD0,))
    seen_c = set()
    for i, (other, g) in enumerate(client_rows, start=1):
        if slug(other) in seen_c or is_client(other):
            continue
        seen_c.add(slug(other))
        cur.execute("""INSERT INTO serving.partner
                         (id, ord, label, kind, rel, sig, ptype, note, date, country,
                          deal, insight, mean, origin)
                       VALUES (%s,%s,%s,NULL,%s,NULL,%s,%s,%s,%s,NULL,NULL,NULL,
                               'pipeline')
                       ON CONFLICT (id) DO NOTHING""",
                    ("plp_%02d" % i, ORD0 + i, esc(other), g["rel"],
                     REL_PTYPE[g["rel"]], esc(g["note"]), g["date"], g["country"]))
    con.commit()

    print("partnerships: %d tie(s) found from %d model call(s), %d refused, "
          "%d call(s) errored; %d competitor(s) updated, %d client partner row(s), "
          "%d tie(s) stored nowhere (both sides unprofiled)"
          % (found, calls, refused, errored, len(written_to), len(seen_c),
             len(orphans)), flush=True)
    for o in orphans[:10]:
        print("  not stored: %s" % o, flush=True)
    # SAY WHAT WAS REFUSED AND WHY, per kind. These were on the tab typed as
    # partnerships until 2026-09-06 and nobody noticed, because nothing counted them --
    # a filter that silently removes rows is indistinguishable from a quiet corpus.
    if not_tie:
        print("partnerships: %d statement(s) named a relationship that is not a "
              "partnership -- %s"
              % (sum(not_tie.values()),
                 ", ".join("%s %d (%s)" % (k, n, PART_NOT_A_TIE[k])
                           for k, n in sorted(not_tie.items(), key=lambda kv: -kv[1]))),
              flush=True)
    for o in ownership[:5]:
        print("  ownership, for step_structure: %s" % o, flush=True)
    # THE TYPE DISTRIBUTION, because a catch-all that eats everything looks exactly like
    # a corpus with nothing specific in it. Measured before the ordered prompt:
    # `strategic` was 61% and jv/licensing/rnd/distribution were never produced at all.
    if by_type:
        print("partnerships: types -- %s%s"
              % (", ".join("%s %d" % (k, n) for k, n in
                           sorted(by_type.items(), key=lambda kv: -kv[1])),
                 ("; %d downgraded to strategic (the model could not point at the "
                  "words for its own label)" % downgraded) if downgraded else ""),
              flush=True)
    if stop:
        print("partnerships: stopped at the --limit of %d call(s); what was found up "
              "to there is committed" % limit, flush=True)
    return {"written": found - len(orphans), "refused": refused, "errored": errored,
            "calls": calls, "by_type": by_type, "downgraded": downgraded,
            "not_a_tie": sum(not_tie.values()), "not_a_tie_by_kind": not_tie,
            "client_rows": len(seen_c), "competitors_updated": len(written_to),
            "dropped_unprofiled": len(orphans), "candidates": bstats["candidates"],
            "named": bstats["named"], "over_cap": bstats["over_cap"]}


# ----------------------------------------------------- step 2b: corporate structure

# Ownership language only. Deliberately NOT here: `partner`, `joint venture`, `alliance`
# and `agreement`, which PART_RX owns -- a joint venture between two firms is a tie, not
# a parent. `acquir*` IS here and also in PART_RX, because an acquisition is both: the
# two steps ask different questions of the same sentence and may both answer.
OWN_RX = re.compile(
    r"(?<!\w)(subsidiar\w*|parent (?:compan|firm|group)\w*|wholly[- ]owned|"
    r"majority[- ]owned|(?:majority|minority|controlling) (?:stake|shareholding)|"
    r"owns|owned by|acquir\w+|takeover|division of|unit of|arm of|"
    r"holding company|spun off|demerged|merged into)(?!\w)", re.I)
# `arm of` looks like a false-positive magnet and is not: of the 20 statements it selected
# from the real corpus, 14 are ownership ("U.S. arm of QinetiQ Group plc", "R&D arm of
# Electronic Systems") and the 2 physical arms ("the arm of the UAV") have no proper name
# on either side, so the prefilter below drops them before they cost a call.

OWN_PROMPT = """Below is ONE extracted statement from a defence-news article, with its
supporting quote. Decide: does it state that one NAMED organization OWNS or IS OWNED BY
another -- a parent, a subsidiary, a division, a controlling stake, an acquisition?

A partnership, joint venture, MoU, supply contract or teaming agreement is NOT ownership,
however close the firms are. A joint venture is jointly owned by its parents and is not a
subsidiary of either unless the statement says one holds a controlling stake. If the
statement does not assert ownership between two named organizations, reply exactly: NONE

Otherwise reply with ONLY this JSON, in ENGLISH:
{"owner": "<the OWNING organization -- ONE name, never 'X and Y'>",
 "owned": "<the OWNED organization -- ONE name, never 'X and Y'>",
 "rel":   "<exactly one of: subsidiary | division>",
 "pct":   <ownership percentage ONLY if the quote states a number, else null>,
 "note":  "<one line stating the ownership exactly as the quote says -- a stake is not
           full ownership, an agreed acquisition is not a completed one>"}

`owner` and `owned` are not interchangeable: put them the way round the quote states.
If the statement names three or more organizations, pick the one pair whose ownership the
quote actually asserts; if no single pair is asserted, reply NONE.

Article: %s
Statement: %s %s %s
Quote: "%s"
"""


# US11920999B2, JP7068126B2, EP3725676B1: patent records phrase their assignee as
# "<number> is owned by <company>", which OWN_RX cannot tell from corporate ownership.
# Five such statements in the real corpus -- few, and each one would put a patent number
# on the structure graph as though it were a subsidiary.
_PATENT_ID_RX = re.compile(r"^[A-Z]{2}\d{5,}[A-Z]?\d?\b")


def parse_structure(raw, hay=None):
    """-> {owner, owned, rel, pct, note} or None. The same bar as parse_partnership,
    because the same model answering the same corpus produces the same failures: two
    organizations joined by 'and' in one field, a government where a company was asked
    for, an untranslated label where a statement was asked for, and names that appear
    nowhere in the statement the model was given."""
    d = _json_reply(raw)
    if d is None:
        return None
    owner, owned = _s(d.get("owner"), 90), _s(d.get("owned"), 90)
    note = _s(d.get("note"), 300)
    rel = (_s(d.get("rel"), 12) or "").lower()
    if not owner or not owned or not note:
        return None
    if rel not in ("subsidiary", "division"):
        return None
    if not is_one_org(owner) or not is_one_org(owned):
        return None                       # 'X and Y' in one field is two orgs, refused
    if is_force(owner) or is_force(owned):
        return None                       # a state owns plenty of this industry, but
                                          # 'the Ministry of Defence' is not a parent co
    if not has_proper_name(owner) or not has_proper_name(owned):
        return None                       # NAMED organization -- the prompt's own rule
    if _PATENT_ID_RX.match(owner.strip()) or _PATENT_ID_RX.match(owned.strip()):
        return None                       # a patent's assignee is not a parent company
    if not is_english(note):
        return None
    # THE BOUNDARY BETWEEN THIS STEP AND step_partnerships, as code. The prompt says a
    # joint venture is not a subsidiary; the model agrees and then answers anyway,
    # because 'Saab and Patria agreed to establish a joint venture' is about as close as
    # two firms get. So: a note written in partnership language, with no ownership
    # language in it, is a tie -- step_partnerships already stores it, and storing it
    # here too would draw a parent on the graph that nobody claimed. A note carrying
    # BOTH ('acquired a controlling stake under the agreement') is ownership and stays.
    if PART_RX.search(note) and not OWN_RX.search(note):
        return None
    if hay is not None and not (_in_hay(owner, hay) and _in_hay(owned, hay)):
        return None                       # both sides must come from the statement
    owner, owned = canon_name(owner), canon_name(owned)
    if slug(owner) == slug(owned):
        return None                       # a company does not own itself
    pct = d.get("pct")
    try:
        pct = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct = None
    if pct is not None and not (0 < pct <= 100):
        pct = None                        # the column's CHECK, applied before the write
    # A percentage the quote does not carry is the model supplying a plausible number,
    # which on this dashboard is the failure that matters most.
    if pct is not None and hay is not None:
        shown = ("%.2f" % pct).rstrip("0").rstrip(".")
        if shown not in hay.replace(" ", ""):
            pct = None
    return {"owner": owner, "owned": owned, "rel": rel, "pct": pct, "note": note}


def step_structure(cur, con, docs, props_by_doc, limit=None):
    """Parent / subsidiary edges for the Profile page's structure graph.

    Mines the SAME extracted propositions step_partnerships reads, asking a different
    question of them. Every row keeps the article it was read from, and source_url is
    NOT NULL, so an ownership claim without a citation cannot be stored at all.
    """
    cur.execute("DELETE FROM serving.competitor_structure WHERE origin='pipeline'")
    profiles = load_profiles(cur)
    if not profiles:
        print("structure: no profiled companies -- run companies first", flush=True)
        return {"written": 0, "refused": 0, "orphans": 0}
    prof_rx = [(p, word_rx(p["name"])) for p in profiles]
    by_cid = {p["comp_id"]: p["name"] for p in profiles}

    def landing(name):
        """-> comp_id of the profiled company this name refers to, or None. The same
        identity layer as everything else: the slug first, then a boundary match on the
        display name so 'Bharat Forge Limited' reaches 'bharat-forge'."""
        cid = slug(name)
        if cid in by_cid:
            return cid
        low = name.lower()
        for p, rx in prof_rx:
            if rx.search(low):
                return p["comp_id"]
        return None

    def asks_a_question(pr):
        """Worth one LLM call? These are checks parse_structure makes anyway, moved to
        before the call that pays for them. Measured on the real corpus: 4,481 statements
        match OWN_RX and 403 of them cannot possibly yield an edge -- "the US Navy plans
        to acquire 1,800 missiles" is procurement, and "further research will allow us to
        gradually acquire vehicles" names nobody at all."""
        if is_force(pr["s"]):
            return False                  # a military buying equipment is not a takeover
        # The parser needs a NAMED organisation on both sides; a statement with no proper
        # name anywhere cannot supply one, whatever the model replies.
        return has_proper_name(pr["s"]) or has_proper_name(pr["o"])

    cands = [(did, pr) for did, prs in props_by_doc.items() for pr in prs
             if OWN_RX.search("%s %s" % (pr["p"], pr["o"])) and asks_a_question(pr)]
    rows, refused, orphans, calls, seen = {}, 0, [], 0, set()
    collapsed = 0
    for did, pr in cands:
        if limit and calls >= limit:
            break
        calls += 1
        hay = ("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])).lower()
        try:
            raw = _ask(OWN_PROMPT % (docs[did]["title"] or did, pr["s"], pr["p"],
                                     pr["o"], clip(pr["q"], 300)), npredict=300)
        except Exception as e:                                    # noqa: BLE001
            refused += 1
            print("  %s: %s" % (did, e), flush=True)
            continue
        got = parse_structure(raw, hay)
        if got is None:
            refused += 1
            continue
        key = (slug(got["owner"]), slug(got["owned"]))
        if key in seen:
            continue
        seen.add(key)
        url = docs[did]["url"]

        # Both directions, because both are true and each is the useful one on a
        # different company's page: on the subsidiary's profile the parent is the fact,
        # on the parent's profile the subsidiary is.
        landed = False
        for subject, other, rel in ((got["owned"], got["owner"], "parent"),
                                    (got["owner"], got["owned"], got["rel"])):
            cid = landing(subject)
            if cid is None:
                continue
            landed = True
            # A subsidiary usually carries its parent's name -- "American Rheinmetall
            # Vehicles", "Leonardo DRS" -- and landing() matches on a word boundary, so a
            # statement about the subsidiary is filed against the PARENT's roster row.
            # Then the other side of that edge is the parent itself, and the graph drew
            # "Rheinmetall - parent of - Rheinmetall": a node pointing at itself, out of a
            # statement that was perfectly true. parse_structure cannot catch it, because
            # it compares names and the names differ.
            #
            # The test is the identity of the node as DRAWN, not where landing() sends it.
            # slug(other) == cid means the node would carry the same identity as the row it
            # hangs off. Matching on landing(other) instead was too blunt and took the good
            # edges with it -- "Rheinmetall -> American Rheinmetall Vehicles" also lands on
            # rheinmetall, and is exactly the edge worth drawing.
            if slug(other) == cid:
                collapsed += 1
                continue
            # The document this edge was read from IS its evidence; publishable grades
            # the source the same way the partnership tiles are graded, so an
            # uncorroborated single source says so rather than looking equal to a filing.
            _ok, why, _t, _n = publishable([url], subject)
            rows[(cid, slug(other), rel)] = (
                cid, slug(other), esc(other), rel, got["pct"], esc(got["note"]),
                url, why)
        if not landed:
            # Real ownership between two companies we do not profile. Counted and named
            # rather than dropped in silence -- step_partnerships learned that lesson
            # when 'N ties found' printed over ties nothing stored.
            orphans.append("%s owns %s" % (got["owner"], got["owned"]))

    for r in rows.values():
        cur.execute("""INSERT INTO serving.competitor_structure
                         (comp_id, entity_id, entity_name, relationship_type,
                          ownership_pct, description, source_url, source_note, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pipeline')
                       ON CONFLICT (comp_id, entity_id, relationship_type)
                       DO UPDATE SET entity_name=EXCLUDED.entity_name,
                                     ownership_pct=EXCLUDED.ownership_pct,
                                     description=EXCLUDED.description,
                                     source_url=EXCLUDED.source_url,
                                     source_note=EXCLUDED.source_note,
                                     updated_at=now()""", r)
    con.commit()
    print("structure: %d edge(s) from %d candidate statement(s), %d refused, "
          "%d collapsed onto one roster row, %d ownership pair(s) with no profiled company"
          % (len(rows), len(cands), refused, collapsed, len(orphans)), flush=True)
    for o in orphans[:10]:
        print("  not profiled: %s" % o, flush=True)
    # ponytail: no 'sister' rows yet. No single statement asserts one -- a sister is two
    # companies sharing a stated parent, a self-join to add once there are parents to join.
    return {"written": len(rows), "refused": refused, "orphans": len(orphans)}


# ------------------------------------------------------- step 2c: corpus mention volume

# Whole days, because the corpus is day-granular: 23,657 of the 23,701 dated documents on
# VPS-B carry a midnight-padded timestamp. A rolling 24-hour window over day-stamped data
# drifts with the hour it is evaluated -- yesterday's 00:00 article falls out of the
# window at 00:01 today -- so the figure would track the clock as much as the news. Seven
# days is wide enough that one quiet Sunday is not a collapse.
METRIC_WINDOW_DAYS = 7

# How far behind publication the crawl is allowed to be before a day counts as settled.
# A floor, not the answer: corpus_window_end() measures the real lag each run. Measured
# 2026-09-04, the corpus held 322 documents for 1 Sep and 16, 19 and 1 for the three days
# after -- so a window ending today would have covered three days the crawler had barely
# reached, and every company on the roster read as collapsing by 25-88%.
METRIC_SETTLE_DAYS = 3


def corpus_dates(cur):
    """-> {document_id: datetime.date} for documents the crawler dated credibly.

    ONE query for the whole corpus. article_date() is the trustworthy ladder -- markup
    first, then the URL path -- but it fetches the stored HTML per document, and this
    step needs a date for all 35k of them rather than for the handful behind a card.
    So: the crawler's `published_at`, minus the ones is_fetch_fallback catches (the
    stamp the crawler writes when it found no publication date, measured wrong on 62 of
    63 documents where a URL date existed to check against).

    That is a weaker date than a card's, and it is used for a weaker claim. A count of
    documents in a window survives a few misdated ones; a date printed beside a headline
    does not, which is why the two do not share a source.
    """
    import datetime
    cur.execute("""SELECT document_id, meta->>'published_at', meta->>'fetched_at'
                     FROM extracted.document
                    WHERE meta->>'published_at' IS NOT NULL""")
    today = datetime.date.today()
    out = {}
    for did, pub, fetched in cur.fetchall():
        if is_fetch_fallback(pub, fetched):
            continue
        ymd = parse_date(str(pub).replace("T", " ")[:24])
        if not ymd or ymd[1] is None or ymd[2] is None:
            continue                      # a month with no day cannot land in a window
        try:
            d = datetime.date(ymd[0], ymd[1], ymd[2])
        except ValueError:
            continue
        if d > today:
            continue                      # a publication date in the future is not one
        out[did] = d
    return out


def corpus_window_end(cur):
    """-> the last day the corpus can honestly be said to cover.

    NOT today. The crawl runs behind publication, so the newest days in the corpus are
    thin and still filling. Counting them makes every company's coverage look like it is
    falling, which is a confident wrong number of exactly the kind this dashboard keeps
    deleting -- a reader would act on "BAE Systems -88%".

    The lag is measured rather than assumed: the most recent day holding at least half
    the trailing 30-day median is treated as settled. That self-corrects when the crawler
    stalls for a week or catches up, where a fixed offset would quietly go stale.
    METRIC_SETTLE_DAYS is only the floor for when the measurement finds nothing.
    """
    import datetime
    cur.execute("""WITH per AS (
                     SELECT (meta->>'published_at')::date AS dt, count(*) AS n
                       FROM extracted.document
                      WHERE meta->>'published_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                        AND (meta->>'published_at')::date <= current_date
                      GROUP BY 1),
                   med AS (SELECT percentile_disc(0.5) WITHIN GROUP (ORDER BY n) AS m
                             FROM per WHERE dt > current_date - 30)
                   SELECT max(per.dt) FROM per, med WHERE per.n >= med.m / 2""")
    row = cur.fetchone()
    floor_day = datetime.date.today() - datetime.timedelta(days=METRIC_SETTLE_DAYS)
    if not row or row[0] is None:
        return floor_day
    # Never claim to cover a day more recent than the floor allows, and never reach back
    # further than the corpus actually goes.
    return min(row[0], floor_day) if row[0] > floor_day else row[0]


def step_metrics(cur, con, docs, props_by_doc, limit=None):
    """How many corpus documents named each competitor, this window against the last.

    No LLM call and no new lookup: company_mentions() is the same alias matching every
    other step uses, and the dates come from one query. The whole step is arithmetic over
    what the pass already holds, which is why it can afford to run for every company
    rather than for a capped candidate list.

    What it is NOT: a measure of how much the world is talking about a company. It counts
    THIS corpus, roughly 35k crawled documents, and the UI has to say so -- "corpus
    mentions", never "mentions". The share-price columns the spec asks for are absent on
    purpose; see the table comment.
    """
    import datetime
    cur.execute("DELETE FROM serving.competitor_metrics WHERE origin='pipeline'")
    profiles = load_profiles(cur)
    if not profiles:
        print("metrics: no profiled companies -- run companies first", flush=True)
        return {"written": 0, "dated": 0}

    dated = corpus_dates(cur)
    window_end = corpus_window_end(cur)
    cur_from = window_end - datetime.timedelta(days=METRIC_WINDOW_DAYS - 1)
    prev_from = cur_from - datetime.timedelta(days=METRIC_WINDOW_DAYS)
    as_of = datetime.datetime.now(datetime.timezone.utc)

    # The comp_id comes from the ROW, never from slug(name). They agree for everything
    # step_companies writes, and that is exactly what makes re-deriving it look safe:
    # revive_partners owns its own id range, and one company whose id did not match its
    # slug would be silently skipped rather than counted wrong -- a missing tile nobody
    # would think to look for.
    merged = merge_candidates({p["name"] for p in profiles})
    by_name = {slug(n): a for n, a in merged.items()}
    # The denominators. A company's raw count rises when the crawler has a big week,
    # which is not the same as the company having one: measured 2026-09-04, the crawler
    # put 847 documents in the current window against 423 in the previous (547 vs 423
    # after the fetch-stamp filter, which is what these count), so every raw count rose
    # and the whole roster read as surging.
    corpus_now = sum(1 for d in dated.values() if cur_from <= d <= window_end)
    corpus_prev = sum(1 for d in dated.values() if prev_from <= d < cur_from)
    written, moved = 0, 0
    for p in sorted(profiles, key=lambda r: r["comp_id"]):
        cid = p["comp_id"]
        # A name the merge folded into another company's group is not in `merged` as a
        # key; count it under its own name rather than dropping it.
        aliases = by_name.get(slug(p["name"])) or {p["name"]}
        dids, _ = company_mentions(aliases, docs, props_by_doc)
        now_n = prev_n = 0
        for did in dids:
            d = dated.get(did)
            if d is None:
                continue
            if d > window_end:
                continue          # inside the crawl's unsettled tail; in neither window
            if d >= cur_from:
                now_n += 1
            elif d >= prev_from:
                prev_n += 1
        # SHARE of the corpus, not raw count. This is the only form of the number that
        # means "more of the conversation" rather than "the crawler had a bigger week".
        # No baseline, no percentage: "+100%" against zero is a division wearing a
        # trend's clothes, and this dashboard has printed one of those before.
        if prev_n and corpus_now and corpus_prev:
            share_now = now_n / float(corpus_now)
            share_prev = prev_n / float(corpus_prev)
            pct = round((share_now - share_prev) * 100.0 / share_prev, 1)
        else:
            pct = None
        if pct:
            moved += 1
        cur.execute("""INSERT INTO serving.competitor_metrics
                         (comp_id, mentions_window, mentions_previous,
                          corpus_window, corpus_previous,
                          mentions_change_pct, window_days, window_end, as_of, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pipeline')
                       ON CONFLICT (comp_id) DO UPDATE SET
                         mentions_window=EXCLUDED.mentions_window,
                         mentions_previous=EXCLUDED.mentions_previous,
                         corpus_window=EXCLUDED.corpus_window,
                         corpus_previous=EXCLUDED.corpus_previous,
                         mentions_change_pct=EXCLUDED.mentions_change_pct,
                         window_days=EXCLUDED.window_days,
                         window_end=EXCLUDED.window_end,
                         as_of=EXCLUDED.as_of, updated_at=now()""",
                    (cid, now_n, prev_n, corpus_now, corpus_prev, pct,
                     METRIC_WINDOW_DAYS, window_end, as_of))
        written += 1
    con.commit()
    print("metrics: %d compan(ies) over the %d days to %s (the corpus is %d day(s) "
          "behind today), %d dated document(s), %d moved against the previous window"
          % (written, METRIC_WINDOW_DAYS, window_end,
             (datetime.date.today() - window_end).days, len(dated), moved), flush=True)
    print("  corpus in window: %d document(s), previous window: %d -- shares, not raw "
          "counts, are what the percentage compares" % (corpus_now, corpus_prev),
          flush=True)
    # ponytail: one row per company, overwritten each pass -- no history, so no sparkline.
    # A (comp_id, as_of) history table is the upgrade, and it needs a reader first: the
    # last sparkline on this page was drawn from a hardcoded path.
    return {"written": written, "dated": len(dated)}


# ----------------------------------------------------------------------- step 3: geo

def build_countries():
    names = set(REF.get("geoCountries", [])) | set(REF.get("tpAllCountries", []))
    for comp in REF.get("geoData", {}).values():
        names |= set(comp.keys())
    names |= {
        "India", "Pakistan", "China", "USA", "United States", "UK", "United Kingdom",
        "France", "Germany", "Sweden", "Norway", "Finland", "Denmark", "Netherlands",
        "Belgium", "Poland", "Ukraine", "Russia", "Italy", "Spain", "Portugal",
        "Greece", "Turkey", "Israel", "Saudi Arabia", "UAE", "Qatar", "Kuwait",
        "Oman", "Egypt", "Morocco", "Algeria", "Nigeria", "Kenya", "South Africa",
        "Uganda", "Australia", "New Zealand", "Japan", "South Korea", "Taiwan",
        "Vietnam", "Thailand", "Malaysia", "Indonesia", "Singapore", "Philippines",
        "Myanmar", "Bangladesh", "Sri Lanka", "Nepal", "Afghanistan", "Iran", "Iraq",
        "Jordan", "Lebanon", "Armenia", "Azerbaijan", "Georgia", "Kazakhstan",
        "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Mexico", "Canada",
        "Czech Republic", "Slovakia", "Hungary", "Romania", "Bulgaria", "Serbia",
        "Croatia", "Slovenia", "Estonia", "Latvia", "Lithuania", "Switzerland",
        "Austria", "Ireland", "Brunei", "Ecuador",
    }
    names = {n for n in names if n and n not in ("Africa", "Europe")}
    syn = {"United States": "USA", "United Kingdom": "UK", "Britain": "UK",
           "Great Britain": "UK", "Holland": "Netherlands",
           "The Philippines": "Philippines"}
    pats = []
    for n in sorted(names, key=len, reverse=True):
        pats.append((word_rx(n), syn.get(n, n)))
    for v, canon in syn.items():
        pats.append((word_rx(v), canon))
    return pats


def find_countries(text, pats):
    hay = (text or "").lower()
    out = []
    for rx, canon in pats:
        if canon not in out and rx.search(hay):
            out.append(canon)
    return out


GEO_PROMPT = """Below are extracted statements (with quotes) linking the defence company
"%s" to %s. Summarise WHAT the company has or does THERE -- an order delivered, a plant,
a partnership, exports, service support.

If the statements do not actually place this company's BUSINESS in %s, reply exactly: NONE.
A headquarters address, an office, or an executive's job title alone is NOT a presence.
A discussion or exploratory talk is not an order -- describe it as what it is.

Otherwise reply with ONLY this JSON, in ENGLISH:
{"name": "<what is there, max 60 chars, e.g. 'Carl-Gustaf M4 order'>",
 "note": "<one line grounded in the quotes, stating no more than they state>",
 "act": "<exactly one of: production | partnership | export | service | unclear>",
 "since": "<4-digit year ONLY if stated, else null>"}

Statements:
%s"""

ACT_CODE = {"production": "lp", "partnership": "pt", "export": "ex", "service": "sv"}

# The activity code has to be visible in the statements, not merely asserted: a row
# reading "Denel procures ... from South African suppliers" was banded LOCAL
# PRODUCTION, which supplier procurement is not (audit M8).
ACT_EVIDENCE = {
    "lp": re.compile(r"produc|manufactur|assembl|plant|factory|facilit|"
                     r"localis|localiz|made in|built in|line for", re.I),
    "pt": re.compile(r"partner|joint venture|\bjv\b|\bmou\b|memorandum|alliance|"
                     r"agreement|team(?:ed|ing)|collaborat|tie-?up|licen[cs]", re.I),
    "ex": re.compile(r"export|deliver|suppl|sold|sale|order|contract|ship(?:ped|ment)",
                     re.I),
    "sv": re.compile(r"servic|maintenance|maintain|support|\bmro\b|repair|overhaul|"
                     r"sustain|training|upgrade", re.I),
}


def digits_stated(text, hay):
    """Every number in the text must appear in the statements. parse_tender already
    did this; geo did not, and "more than 50% of its inputs ... of which 75% are
    located in South Africa" was stored as "procures 75% of its inputs"."""
    flat = (hay or "").replace(",", "")
    return all(d.replace(",", "") in flat for d in re.findall(r"\d[\d,.]*", text or ""))


def parse_geo(raw, hay=None):
    d = _json_reply(raw)
    if d is None:
        return None
    name, note = _s(d.get("name"), 80), _s(d.get("note"), 300)
    if not name or not note:
        return None
    act = (_s(d.get("act"), 20) or "unclear").lower()
    if act not in ("production", "partnership", "export", "service"):
        return None      # 'unclear' proves nothing: a HQ address, an office, a bare
                         # "has presence in X" or a future intention is not a presence
    code = ACT_CODE[act]
    if hay is not None:
        if not ACT_EVIDENCE[code].search(hay):
            return None                  # the activity itself must be in the statements
        if not (digits_stated(name, hay) and digits_stated(note, hay)):
            return None                  # an invented/relocated number refuses the row
    since = _s(d.get("since"), 12)
    if since and not re.fullmatch(r"(19|20)\d\d", since):
        since = None
    return {"name": clip(name, 60), "note": note, "c": code, "since": since}


def pick_src(text, items):
    """-> the index of the statement a summary actually came from, by content-token
    overlap, or None when NOTHING in the group carries it.

    step_geo used to store items[0]'s document url whatever the summary said, so a
    Saab/India joint-venture row cited a 2016 howitzer article with no Saab in it, and
    five Patria rows all cited one Japanese press release (audit C4)."""
    want = set(_content_toks(text)) | _designators(text)
    best, best_n = None, 1
    for i, (_did, pr) in enumerate(items):
        blob = ("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])).lower()
        n = sum(1 for t in want if _has_word(t, blob))
        if n > best_n:
            best, best_n = i, n
    return best


def step_geo(cur, con, docs, props_by_doc, limit=None):
    # Scoped to THIS writer. revive_geo.py owns ord >= 2000; an unscoped delete
    # here would wipe its rows on the next enrichment run -- the third instance of
    # the two-writers-one-key-space fault in this schema (matchup, tender, geo).
    cur.execute("DELETE FROM serving.geo_presence WHERE origin='pipeline' AND ord < 2000")
    # Scoped like every other delete in this file. revive_geo.py owns ord >= 2000 and
    # writes the COMPANY rows its presence rows join to; an unscoped delete here
    # would strand 17 country blocks behind ids no company row answers to.
    cur.execute("DELETE FROM serving.geo_comp WHERE origin='pipeline' AND ord < %s",
                (2000,))
    profiles = load_profiles(cur)
    if not profiles:
        print("geo: no profiled companies -- run companies first", flush=True)
        return {"written": 0, "refused": 0, "skipped": 0}
    pats = build_countries()
    written, refused, calls, no_src, offp = 0, 0, 0, 0, 0
    for p in profiles:
        gid = p["comp_id"]
        _dids, cprops = company_mentions({p["name"]}, docs, props_by_doc)
        groups = {}
        for did, pr in cprops:
            cs = find_countries("%s %s" % (pr["o"], pr["pl"] or ""), pats)
            for c in cs:
                groups.setdefault(c, []).append((did, pr))
        country_ord = 0
        for country, items in sorted(groups.items(),
                                     key=lambda kv: -len(kv[1]))[:8]:
            if limit and calls >= limit:
                break
            calls += 1
            use = items[:8]
            lines = "\n".join(prop_line(pr) for _d, pr in use)
            hay = " ".join("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])
                           for _d, pr in use).lower()
            try:
                raw = _ask(GEO_PROMPT % (p["name"], country, country, lines),
                           npredict=250)
            except Exception as e:                                # noqa: BLE001
                refused += 1
                print("  %s/%s: %s" % (p["name"], country, e), flush=True)
                continue
            g = parse_geo(raw, hay)
            if g is None:
                refused += 1
                continue
            # A footprint row is intelligence only if it is about a KSSL line: audited
            # 2026-09-05, 36 of 275 served rows were helicopter plants, F-35 deliveries,
            # radar and satellite production. No category on this surface, so the
            # override is ANY KSSL line named ("Helicopters / naval guns" stays).
            if (off_portfolio("", g["note"], title=g["name"])
                    or category_conflict("", g["note"], title=g["name"])):
                offp += 1
                continue
            # cite the document the summary came FROM, not the group's first one
            hit = pick_src("%s %s" % (g["name"], g["note"]), use)
            if hit is None:
                no_src += 1
                continue
            country_ord += 1
            did0 = use[hit][0]
            cur.execute("""INSERT INTO serving.geo_presence
                             (comp_id, comp_ord, country, country_ord, ord, name, c,
                              val, since, qty, stage, note, src, srcnote, origin)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,%s,NULL,NULL,%s,%s,%s,
                                   'pipeline')
                           ON CONFLICT (comp_id, country, ord) DO NOTHING""",
                        (gid, p["ord"], country,
                         ORD0 + country_ord, ORD0, esc(g["name"]), g["c"],
                         g["since"], esc(g["note"]), docs[did0]["url"],
                         docs[did0]["source"]))
            written += 1
        # The client gets a geo_comp row like every other company. The old code
        # skipped it on a PK-collision assumption that was never true: reference ids
        # are uppercase codes ('KSSL'), pipeline ids are lowercase slugs, and the two
        # origins are served through different views (audit L11). Its presence rows
        # are keyed by the same comp_id, so the map can join them at all.
        cur.execute("""INSERT INTO serving.geo_comp
                         (id, ord, name, dir, hq, "isBf", origin)
                       VALUES (%s,%s,%s,%s,%s,%s,'pipeline')
                       ON CONFLICT (id) DO NOTHING""",
                    (p["comp_id"], p["ord"], esc(p["name"]),
                     {"rival": "threat", "client": "client"}.get(p["dir"], "watch"),
                     p["hq"], p["dir"] == "client"))
    con.commit()
    print("geo: %d presence row(s) written, %d refused, %d off-portfolio, %d with no "
          "statement to cite" % (written, refused, offp, no_src), flush=True)
    return {"written": written, "refused": refused, "off_portfolio": offp, "no_src": no_src}


# -------------------------------------------------------------------- step 4: tenders

TENDER_RX = re.compile(
    r"(tender|procure|acquisition|\brfp\b|\brfi\b|request for proposal|"
    r"contract|order)", re.I)

# A procurement has to be in the EVIDENCE, not only in the model's reading of it: a
# trade-show unveiling of the client's own howitzer was stored as an "Armenian MoD
# procurement" (audit H3). Matched against the quotes, not the predicates.
PROCURE_EV_RX = re.compile(
    r"(tender|solicitation|request for (?:proposal|information|quotation|bid)|"
    r"\brfp\b|\brfi\b|\brfq\b|procure|procurement|award|contract|"
    r"order(?:ed|s|ing)?\b|purchas|acquisition|acquir|framework agreement|"
    r"bid(?:der|ding)?\b|deal (?:for|worth)|to buy|bought)", re.I)

TENDER_PROMPT = """You screen defence-news articles for procurement events relevant to
KSSL (Kalyani Strategic Systems, Indian maker of artillery, ammunition, armoured
vehicles, small arms, drones, naval systems, missiles, forgings). Below are the
extracted statements of ONE article, with quotes.

Does the article describe ONE procurement event -- a tender, solicitation, government
order, or contract award for defence equipment? If not, reply exactly: NONE.
If the equipment fits NONE of the listed categories, also reply NONE -- never stretch
the nearest category. A stated intention or budget plan is not yet a tender.

Otherwise reply with ONLY this JSON, in ENGLISH:
{"title": "<the procurement in one factual line, max 90 chars -- announced is not awarded>",
 "issuer": "<the buying agency/ministry/armed force AS NAMED in the statements (not just
            the country), else null>",
 "country": "<the buying country, from the statements, else null>",
 "cat": "<exactly one of: %s>",
 "value": "<the monetary value VERBATIM with its currency ONLY if stated, else null>",
 "qty": "<the quantity ONLY if stated, else null>",
 "deadline": "<a bid/closing deadline ONLY if stated, else null>",
 "status": "<awarded or closed ONLY if the statements say the contract was awarded or
            the tender closed; open if it is an open solicitation; else null>"}

Rules: use ONLY the statements; no invented numbers; unstated fields are null.

Article: %s (%s)
Statements:
%s"""


def parse_tender(raw, cats, hay):
    d = _json_reply(raw)
    if d is None:
        return None
    title = _s(d.get("title"), 120)
    cat = _s(d.get("cat"), 60)
    if not title or cat not in cats:
        return None                      # category outside KSSL_CATS refuses the row
    status = (_s(d.get("status"), 12) or "").lower() or None
    if status and status not in ("open", "awarded", "closed"):
        return None
    out = {"title": title, "issuer": _s(d.get("issuer"), 120),
           "country": _s(d.get("country"), 60), "cat": cat, "status": status}
    for f in ("value", "qty", "deadline"):
        v = _s(d.get(f), 80)
        if v:
            digits = re.findall(r"\d[\d,.]*", v)
            if digits and not all(dg.replace(",", "") in hay.replace(",", "")
                                  for dg in digits):
                v = None                 # numbers must appear in the statements
        out[f] = v
    return out


def step_tenders(cur, con, docs, props_by_doc, limit=None):
    # Delete only THIS writer's rows. fetch_tenders.py owns the API-sourced rows
    # (ids prefixed sam_/ted_/gem_/cppp_); a blanket delete here wiped its 88-row
    # feed once -- two writers, one table, so each owns its own id space.
    cur.execute("DELETE FROM serving.tender WHERE origin='pipeline' AND id ~ '^[0-9]+$'")
    # News-derived tenders are RETIRED: the Market pillar is fed only by real
    # procurement-portal APIs (pipeline/fetch_tenders.py). This step no longer screens
    # defence news into tenders -- it now only purges any legacy news rows and writes
    # nothing, so a news "tender" can never reappear. (User: tenders from news sites out.)
    con.commit()
    print("tenders: news screener retired; %d legacy news row(s) purged, 0 written"
          % cur.rowcount, flush=True)
    return {"written": 0, "purged": cur.rowcount, "refused": 0, "stale": 0,
            "undated": 0, "offtopic": 0, "no_evidence": 0, "client_subject": 0}
    cur.execute("""SELECT id FROM serving.signal_card
                    WHERE origin='pipeline' AND lane='market'""")
    market_docs = {r[0][3:] for r in cur.fetchall()}   # strip 'pl_'
    cats = kssl_cats()
    patterns, _comp = load_terms()
    cutoff, cur_year = recent_cutoff()
    cand = set(market_docs)
    for did, prs in props_by_doc.items():
        if any(TENDER_RX.search(pr["p"]) or TENDER_RX.search(pr["o"]) for pr in prs):
            cand.add(did)
    written, refused, stale, undated, offtopic, calls = 0, 0, 0, 0, 0, 0
    no_evidence, client_subject, n = 0, 0, 0
    for did in sorted(cand):
        prs = props_by_doc.get(did)
        if not prs or did not in docs:
            continue
        ymd = article_date(cur, did)
        if ymd is None:
            undated += 1
            continue
        if not is_recent_ym(ymd[:2], cutoff, cur_year):
            stale += 1
            continue
        props_t = [(pr["s"], pr["p"], pr["o"]) for pr in prs]
        if not is_relevant(patterns, docs[did]["title"], props_t):
            offtopic += 1
            continue
        if limit and calls >= limit:
            break
        calls += 1
        use = prs[:14]
        quotes = " ".join(pr["q"] for pr in use)
        if not PROCURE_EV_RX.search(quotes):
            no_evidence += 1             # nothing in the quotes buys anything
            continue
        if sum(1 for pr in use if is_client(pr["s"])) * 2 >= len(use):
            client_subject += 1          # the article is ABOUT the client group; its
            continue                     # own launch is not a foreign procurement
        lines = "\n".join(prop_line(pr) for pr in use)
        hay = " ".join("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])
                       for pr in use).lower()
        try:
            raw = _ask(TENDER_PROMPT % (", ".join(cats), docs[did]["title"] or did,
                                        docs[did]["source"], lines), npredict=350)
        except Exception as e:                                    # noqa: BLE001
            refused += 1
            print("  %s: %s" % (did, e), flush=True)
            continue
        t = parse_tender(raw, cats, hay)
        if t is None:
            refused += 1
            continue
        if is_client(t["issuer"]) or is_client(t["country"]):
            client_subject += 1          # the client group is never the buyer here
            continue
        n += 1
        cur.execute("""INSERT INTO serving.tender
                         (id, ord, title, issuer, country, cat, "value", qty, deadline,
                          dl, "reqNote", req, matches, lean, "leanTxt", status, url,
                          "urlKind", srcs, stage, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,'[]','[]',NULL,
                               NULL,%s,%s,NULL,%s,NULL,'pipeline')
                       ON CONFLICT (id) DO NOTHING""",
                    (TENDER_ID0 + n, ORD0 + n, esc(t["title"]),
                     esc(t["issuer"]) or None, t["country"], t["cat"],
                     esc(t["value"]) or None, esc(t["qty"]) or None,
                     esc(t["deadline"]) or None, t["status"], docs[did]["url"],
                     json.dumps([{"label": docs[did]["source"],
                                  "url": docs[did]["url"]}])))
        written += 1
    con.commit()
    print("tenders: %d written, %d refused, %d stale, %d undated, %d off-portfolio, "
          "%d without a procurement in the quotes, %d about the client group "
          "(from %d candidate doc(s))"
          % (written, refused, stale, undated, offtopic, no_evidence, client_subject,
             len(cand)), flush=True)
    return {"written": written, "refused": refused, "stale": stale,
            "undated": undated, "offtopic": offtopic, "no_evidence": no_evidence,
            "client_subject": client_subject}


# ---------------------------------------------------------------- step 5: innovations

RD_RX = re.compile(
    r"(unveil|demonstrat|develop|test|trial|prototype|research|capabilit|"
    r"milestone|first flight|innovat)", re.I)

INNOV_PROMPT = """You screen defence-news articles for technology/R&D advances relevant
to KSSL (Kalyani Strategic Systems, the defence arm of Bharat Forge / Kalyani Group --
Indian maker of artillery, ammunition, armoured vehicles, small arms, drones, naval
systems, missiles, forgings). Below are the extracted statements of ONE article, with
quotes.

Does the article describe ONE concrete capability or R&D advance -- a system
demonstrated, a technical milestone, a new development? If not, reply exactly: NONE

Otherwise reply with ONLY this JSON, in ENGLISH:
{"area": "<exactly one of: %s>",
 "t": "<the advance in one factual line, max 90 chars -- demonstrated is not fielded,
       a concept is not a product>",
 "mat": "<exactly one of lab | dev | prod | fielded ONLY if the statements support it,
         else null>",
 "driver": "<the organization driving it, from the statements, else null>",
 "body": "<2 sentences, ENGLISH: what was demonstrated/developed, grounded in the
          statements>",
 "impact": "<1-2 sentences: the SPECIFIC significance the statements support -- no
            generic filler like 'could potentially set new standards'>",
 "horizon": "<a stated timeframe (year / decade) ONLY if stated, else null>"}

The area ids mean: %s. Pick the single closest; if none fits, reply NONE -- never
stretch the nearest area. Name the driver accurately even when it is
Kalyani/KSSL/Bharat Forge -- the client group's own advances are filtered out of this
feed afterwards, and mislabelling one as a rival is worse than dropping it.
Rules: use ONLY the statements; no invented facts; unstated fields are null.

Article: %s (%s)
Statements:
%s"""


# "demonstrated is not fielded" is in INNOV_PROMPT, but a prompt is not a gate: rows
# whose own body says "unveiled at IDEX 2025" / "showcased to gauge European interest"
# were stored mat='fielded' and rendered FIELDED / IN SERVICE (audit H6).
SHOWN_RX = re.compile(r"(unveil|showcas|demonstrat|display|reveal|exhibit|"
                      r"present(?:ed|ing)? at|on show|debut)", re.I)
MAT_CAP = {"prod": "dev", "fielded": "dev"}

# Language variants of one page are one story: brahmos.com/page/ru-brahmos-ng and
# /page/brahmos-ng produced two BrahMos NG rows.
_LANG = ("ru", "en", "de", "fr", "es", "it", "pt", "ja", "zh", "ko", "ar", "hi", "uk",
         "pl", "cs", "fi", "sv", "no", "da", "nl", "tr", "lt", "lv", "et", "hu", "ro",
         "bg", "el", "he", "id", "ms", "th", "vi", "sk", "sl", "hr", "sr")
_LANG_SEG = re.compile(r"^(%s)(?:-[a-z]{2})?$" % "|".join(_LANG))
_LANG_PFX = re.compile(r"^(%s)-(?=[a-z])" % "|".join(_LANG))


def url_key(url):
    """One story's identity, independent of the language its page is served in."""
    from urllib.parse import urlsplit
    u = urlsplit(str(url or "").lower())
    segs = [x for x in (u.path or "").strip("/").split("/") if x]
    segs = [x for x in segs if not _LANG_SEG.match(x)]
    if segs:
        segs[-1] = _LANG_PFX.sub("", segs[-1])
    return (u.netloc.replace("www.", ""), "/".join(segs))


def product_key(title):
    """The alphanumeric designators a headline names: 'Simha 4x4' -> {'4x4'},
    'MArG 39 ...' -> {'39'}, 'Developing heavy-lift airships' -> set(). Same driver +
    same designators = the same product advance, however the outlets worded it."""
    return frozenset(t for t in _designators(title) if any(c.isdigit() for c in t))


def parse_innov(raw, area_ids, hay):
    d = _json_reply(raw)
    if d is None:
        return None
    area = _s(d.get("area"), 30)
    if area:
        area = area.lower()
    t = _s(d.get("t"), 120)
    body = _s(d.get("body"), 600)
    impact = _s(d.get("impact"), 400)
    if area not in area_ids or not t or not body or not impact:
        return None                      # unknown area refuses the row (no 'other')
    mat = (_s(d.get("mat"), 10) or "").lower() or None
    if mat and mat not in ("lab", "dev", "prod", "fielded"):
        mat = None
    if mat and SHOWN_RX.search("%s %s" % (t, body)):
        mat = MAT_CAP.get(mat, mat)      # shown at a show is not in service
    driver = _s(d.get("driver"), 90)
    if driver and not _in_hay(driver, hay):
        driver = None
    if driver and not is_one_org(driver) and not is_client(driver):
        driver = None                    # 'X and Y' is two orgs; the client group's
                                         # own spellings already fold to one identity
    if driver:
        driver = canon_name(driver)      # ONE identity: 'KSSL' / 'Bharat Forge
                                         # Limited' / 'Kalyani Group' are one driver
    horizon = _s(d.get("horizon"), 40)
    if horizon and not _in_hay(horizon, hay, min_tok=3):
        horizon = None
    return {"area": area, "t": t, "mat": mat, "driver": driver, "body": body,
            "impact": impact, "horizon": horizon}


def step_innovations(cur, con, docs, props_by_doc, limit=None):
    cur.execute("DELETE FROM serving.innovation WHERE origin='pipeline'")
    cur.execute("""SELECT id FROM serving.signal_card
                    WHERE origin='pipeline' AND lane='tech'""")
    tech_docs = {r[0][3:] for r in cur.fetchall()}
    tech_cats = REF["techCats"]
    area_ids = [c["id"] for c in tech_cats]
    area_ord = {c["id"]: i for i, c in enumerate(tech_cats)}
    area_desc = "; ".join("%s = %s" % (c["id"], c["name"]) for c in tech_cats)
    patterns, _comp = load_terms()
    cand = set(tech_docs)
    for did, prs in props_by_doc.items():
        if sum(1 for pr in prs if RD_RX.search(pr["p"])) >= 1 and len(prs) >= 3:
            props_t = [(pr["s"], pr["p"], pr["o"]) for pr in prs]
            if is_relevant(patterns, docs.get(did, {}).get("title"), props_t):
                cand.add(did)
    written, refused, dup, calls, own, offp = 0, 0, 0, 0, 0, 0
    seen, per_area, seen_urls, seen_products = [], {}, set(), set()
    for did in sorted(cand):
        prs = props_by_doc.get(did)
        if not prs or did not in docs:
            continue
        if limit and calls >= limit:
            break
        calls += 1
        use = prs[:14]
        lines = "\n".join(prop_line(pr) for pr in use)
        hay = " ".join("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])
                       for pr in use).lower()
        try:
            raw = _ask(INNOV_PROMPT % (" | ".join(area_ids), area_desc,
                                       docs[did]["title"] or did,
                                       docs[did]["source"], lines), npredict=450)
        except Exception as e:                                    # noqa: BLE001
            refused += 1
            print("  %s: %s" % (did, e), flush=True)
            continue
        it = parse_innov(raw, area_ids, hay)
        if it is None:
            refused += 1
            continue
        # THE SUBJECT GATE, on this surface too. Audited 2026-09-05: 1,127 served
        # innovations, ~20% about a class KSSL has no line in (a Trailblazer CAMERA
        # system, a DEIMOS laser weapon, software for SPY-6 radars) -- and the card
        # gate applied naively refused a third of the wrong rows, because an innovation
        # names its accessories (the radar on a Skyranger, the SAL guidance on an
        # Excalibur). So: headline `t` is the subject, `body` is the accessories. The
        # tech area is joined to the serving tag through portfolio.TECH_AREA_TO_TAG --
        # an explicit map, never the label.
        tag = portfolio.TECH_AREA_TO_TAG.get(it["area"], "")
        if (category_conflict(tag, it["body"], title=it["t"])
                or off_portfolio(tag, it["body"], title=it["t"])):
            offp += 1
            continue
        # The Innovation Pipeline is rival intelligence. Half of it -- 13 of 26 rows,
        # 5 of the 8 under Artillery -- was the client's own product launches read
        # back to it, which tells KSSL nothing it does not already know.
        if is_client(it["driver"]) or client_led(it["t"]):
            own += 1
            continue
        ukey = url_key(docs[did]["url"])
        pkey = (fold_name(it["driver"] or it["area"]), product_key(it["t"]))
        if (is_dup(seen, it["driver"] or it["area"], it["t"])
                or ukey in seen_urls
                or (pkey[1] and pkey in seen_products)):
            dup += 1
            continue
        seen.append(((it["driver"] or it["area"]).casefold(), title_tokens(it["t"])))
        seen_urls.add(ukey)
        if pkey[1]:
            seen_products.add(pkey)
        per_area[it["area"]] = per_area.get(it["area"], 0) + 1
        cur.execute("""INSERT INTO serving.innovation
                         (area, area_ord, ord, t, mat, gap, driver, horizon, body,
                          impact, "whatsNew", "compNote", action, sources, url, origin)
                       VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,NULL,NULL,NULL,%s,%s,
                               'pipeline')
                       ON CONFLICT (area, ord) DO NOTHING""",
                    (it["area"], area_ord[it["area"]], ORD0 + per_area[it["area"]],
                     esc(it["t"]), it["mat"], esc(it["driver"]) or None,
                     esc(it["horizon"]) or None, esc(it["body"]), esc(it["impact"]),
                     docs[did]["source"], docs[did]["url"]))
        written += 1
    con.commit()
    print("innovations: %d written, %d refused, %d off-portfolio, %d duplicate(s), %d "
          "client-group advance(s) held back (from %d candidate doc(s))"
          % (written, refused, offp, dup, own, len(cand)), flush=True)
    return {"written": written, "refused": refused, "off_portfolio": offp, "dup": dup,
            "own": own}


# ------------------------------------------------------------------- step 6: sources

def step_sources(cur, con, docs, props_by_doc, limit=None):
    cur.execute("DELETE FROM serving.company_source WHERE origin='pipeline'")
    cur.execute("DELETE FROM serving.source_registry WHERE origin='pipeline'")
    profiles = load_profiles(cur)
    if not profiles:
        print("sources: no profiled companies -- run companies first", flush=True)
        return {"written": 0}
    n_cs, n_sr, sr_ord = 0, 0, 0
    for p in profiles:
        dids, _props = company_mentions({p["name"]}, docs, props_by_doc)
        dated = []
        for did in dids:
            ymd = article_date(cur, did)
            key = (ymd[0], ymd[1] or 0, ymd[2] or 0) if ymd else (0, 0, 0)
            dated.append((key, did))
        dated.sort(key=lambda x: x[0], reverse=True)   # date desc, undated last
        seen_u, i = set(), 0
        for _k, did in dated:
            u = docs[did]["url"]
            if not u or u in seen_u or i >= 10:
                continue
            seen_u.add(u)
            i += 1
            # company is the DISPLAY NAME here, not the slug: the UI joins these
            # rows to competitors by the name it shows (audit L11).
            cur.execute("""INSERT INTO serving.company_source
                             (company, comp_ord, ord, url, origin)
                           VALUES (%s,%s,%s,%s,'pipeline')
                           ON CONFLICT (company, ord) DO NOTHING""",
                        (esc(p["name"]), p["ord"], ORD0 + i, u))
            n_cs += 1
        seen_src = set()
        for _k, did in dated:
            s = docs[did]["source"]
            if not s or s in seen_src or len(seen_src) >= 5:
                continue
            seen_src.add(s)
            sr_ord += 1
            cur.execute("""INSERT INTO serving.source_registry
                             (ord, company, label, url, kind, origin)
                           VALUES (%s,%s,%s,%s,'news','pipeline')
                           ON CONFLICT (ord) DO NOTHING""",
                        (ORD0 + sr_ord, esc(p["name"]), s, docs[did]["url"]))
            n_sr += 1
    con.commit()
    print("sources: %d company_source row(s), %d source_registry row(s) for %d "
          "compan(ies)" % (n_cs, n_sr, len(profiles)), flush=True)
    return {"company_source": n_cs, "source_registry": n_sr}


# ------------------------------------------------------------------ step 7: matchups

SPEC_RX = re.compile(
    r"(range|calibre|caliber|weight|speed|rate of fire|endurance|payload|altitude)"
    r"\D{0,40}?(\d[\d,.]*)\s*(km/h|rds/min|km|mm|kg|tonnes|t\b|m\b|hp|kW)", re.I)
SPEC_LABEL = {"caliber": "Calibre"}


def is_product_name(product):
    """A comparison row has to NAME a thing. 'circuit cards', 'gunner hand stations',
    'logistics trucks' and 'air and missile defense systems' are generic nouns, and
    they were compared as though they were systems (audit H7). A real name carries a
    proper noun or an alphanumeric designator in its first two words -- or is an
    acronym -- and never jams two things together with 'and'."""
    txt = str(product or "").strip()
    if not txt or not is_one_org(txt):
        return False
    toks = re.findall(r"[^\W_]+(?:[-/'\u2019][^\W_]+)*", txt, re.UNICODE)
    for i, t in enumerate(toks):
        if any(c.isdigit() for c in t):
            return True
        if len(t) >= 2 and t.isupper():
            return True                  # 'ESS', 'MMR', 'AMPV'
        if i < 2 and t[:1].isupper():
            return True                  # 'Carl-Gustaf M4', 'Nimbrix', 'Simha'
    return False


def _band_rx(term):
    """word_rx, but tolerant of the plural a PRODUCT LIST is written in.

    Companies state product lines, not single items -- "missiles", "drones", "howitzers".
    word_rx ends in (?!\\w), which refuses every one of them, so categorise_product returned
    None for Adani Defence (products: ["helicopters", "missiles", ...]) and AeroVironment.
    That is not only a gate problem: rate_threat calls the same function, so any company
    whose products are listed in the plural has been recorded as falling in "no KSSL
    category" and rated a weaker threat than it is. Only a trailing s/es is allowed, so a
    longer unrelated word still cannot slip through.
    """
    return re.compile(r"(?<!\w)" + re.escape(term.lower()) + r"(?:e?s)?(?!\w)")


def categorise_product(product):
    """CAT_META keyword hit on the PRODUCT NAME -> catKey band, else None (no band ->
    no matchup). The surrounding article text is NOT consulted: that fallback banded
    'ESS for submarines' as Armoured Vehicle MRO, a Su-30MKI fighter as Missiles & Air
    Defence and an AirMaster S radar as UAVs & Drones, all by a keyword that belonged
    to a neighbouring sentence (audit H7). The docstring already refused it; the code
    did it anyway."""
    # NOT str(product): on a stored product object that stringifies the whole dict, and the
    # source_url inside it matches keywords -- "…/drone-…" banded AeroVironment as UAVs on
    # the strength of its citation link. A non-string is a caller bug, not a category.
    if not isinstance(product, str):
        return None
    hay = product.lower()
    # THE LONGEST MATCHING KEYWORD WINS, not the first band in dict order. Returning on the
    # first hit made the answer depend on where a band sits in the JSON, and `pav` sits above
    # `uav` and `msl` while carrying two very broad words -- "vehicle" and "tank". So an
    # "unmanned aerial vehicle" was filed as an Armoured Vehicle and an "anti-tank guided
    # missile" as a tank, on the dashboard, by keyword collision. Specificity is the tie-break
    # that fixes both without deleting the broad words that legitimately catch other products.
    best_kw, best_key = "", None
    for key, meta in REF.get("CAT_META", {}).items():
        for kw in meta.get("kw", []):
            if len(kw) >= 3 and len(kw) > len(best_kw) and _band_rx(kw).search(hay):
                best_kw, best_key = kw, key
    return best_key


def extract_specs(props_text):
    """Numeric specs STATED in the propositions -- keyword-adjacent number+unit only.
    KSSL side stays null: absent specs render as the honest no-comparison state."""
    out, seen = [], set()
    for m in SPEC_RX.finditer(props_text):
        label = m.group(1).strip().lower()
        label = SPEC_LABEL.get(label, label.capitalize())
        if label in seen:
            continue
        seen.add(label)
        try:
            num = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        out.append({"l": label, "cv": "%s %s" % (m.group(2), m.group(3).strip()),
                    "cn": num, "kv": None, "kn": None, "u": m.group(3).strip(),
                    "hi": None, "p": "s"})
        if len(out) >= 3:
            break
    return out


def step_matchups(cur, con, docs, props_by_doc, limit=None):
    # Scoped to THIS writer's id range. revive_matchups.py owns 20000+, and an
    # unscoped delete-first here wiped its 453 rows on the next run -- the same
    # two-writers-one-id-space fault that already cost us serving.tender.
    cur.execute("DELETE FROM serving.matchup WHERE origin='pipeline' AND matchup_id < 20000")
    profiles = load_profiles(cur)
    rivals = [p for p in profiles if p["dir"] == "rival" and p["products"]]
    if not rivals:
        print("matchups: no rival profiles with products -- nothing to do", flush=True)
        return {"written": 0, "skipped": 0}
    cat_label = {k: v for v, k in REF["CAT_KEY"].items()}   # catKey -> label
    counter = {r["band"]: r for r in REF.get("counterRules", [])}
    written, skipped, unnamed, dup, n = 0, 0, 0, 0, 0
    skipped_nospec = 0
    seen_quotes = set()
    for p in rivals:
        _dids, cprops = company_mentions({p["name"]}, docs, props_by_doc)
        for product in p["products"]:
            if not is_product_name(product):
                unnamed += 1
                continue
            prx = word_rx(product)
            hits = [(did, pr) for did, pr in cprops
                    if prx.search(("%s %s %s %s" % (pr["s"], pr["p"], pr["o"],
                                                    pr["q"])).lower())]
            if not hits:
                skipped += 1
                continue
            ptext = " ".join("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])
                             for _d, pr in hits[:10])
            band = categorise_product(product)
            if band is None or band not in cat_label:
                skipped += 1
                continue
            # three Elbit products were three matchups off ONE quote
            qkey = (p["comp_id"],
                    re.sub(r"\W+", " ", (hits[0][1]["q"] or "").lower()).strip()[:200])
            if qkey[1] and qkey in seen_quotes:
                dup += 1
                continue
            seen_quotes.add(qkey)
            anchor = (counter.get(band) or {}).get("product")
            det = [["Sourced statement",
                    "%s — <i>&ldquo;%s&rdquo;</i>" % (esc("%s %s %s" % (pr["s"],
                                                                        pr["p"],
                                                                        pr["o"])),
                                                      esc(clip(pr["q"], 220)))]
                   for _d, pr in hits[:4]]
            det.append(["Source", docs[hits[0][0]]["url"]])
            srcs, seen_u = [], set()
            for did, _pr in hits[:6]:
                u = docs[did]["url"]
                if u and u not in seen_u:
                    seen_u.add(u)
                    srcs.append({"label": docs[did]["source"], "url": u})
            # A matchup with no specification is an EMPTY PANEL: verdict box blank,
            # both advantage columns "none recorded", spec table empty -- a comparison
            # that compares nothing. Positioning exists to compare specifications, so
            # a row with none is archived rather than shown, the same rule
            # revive_matchups applies.
            specs = extract_specs(ptext)
            if not specs:
                skipped_nospec += 1
                continue
            n += 1
            # Reason is user-facing: state the comparison factually, never pipeline
            # self-narration ("keyword-matched", "appears in the corpus"). The sourced
            # evidence lives in `det`; the specs table carries the numbers.
            reason = ("<b>%s</b> (%s) is a %s-category system."
                      % (esc(product), esc(p["name"]), esc(cat_label[band]))
                      + ((" KSSL fields <b>%s</b> in this category." % esc(anchor))
                         if anchor else ""))
            cur.execute("""INSERT INTO serving.matchup
                             (matchup_id, cat, anchor, "global", dir, country, comp,
                              "compBy", bf, "bfBy", ks_thin, reason, edge, specs,
                              "advComp", "advBf", det, "verdictH", verdict, "catKey",
                              srcs, gen, origin)
                           VALUES (%s,%s,%s,false,NULL,NULL,%s,%s,%s,%s,true,%s,NULL,
                                   %s,'[]','[]',%s,NULL,NULL,%s,%s,true,'pipeline')
                           ON CONFLICT (matchup_id) DO NOTHING""",
                        (MATCHUP_ID0 + n, cat_label[band], anchor,
                         "%s · %s" % (esc(p["name"]), esc(product)), esc(p["name"]),
                         ("KSSL · %s" % esc(anchor)) if anchor else None,
                         "Kalyani Strategic Systems" if anchor else None,
                         reason, json.dumps(specs),
                         json.dumps(det), band, json.dumps(srcs)))
            written += 1
    con.commit()
    print("matchups: %d written, %d product(s) skipped (no corpus hits / no KSSL "
          "category), %d not a named product, %d sharing one evidence quote, "
          "%d archived with no specification (would render an empty panel)"
          % (written, skipped, unnamed, dup, skipped_nospec), flush=True)
    return {"written": written, "skipped": skipped, "unnamed": unnamed, "dup": dup,
            "nospec": skipped_nospec}


def step_news(cur, con, docs, props_by_doc, limit=None):
    """Refill serving.competitor_news, IN THE SAME PASS THAT EMPTIED IT.

    serving.competitor_news.comp_id is `REFERENCES serving.competitors(comp_id) ON
    DELETE CASCADE`, and step_companies above opens by deleting every origin='pipeline'
    competitor -- so the news table is cascaded away at the start of every pass.

    The refill already existed, wired into extraction/entrypoint.sh AFTER the whole
    enrich run. That is correct but far too late: a pass is nine steps and several
    hours (55 profile calls in step one alone), so the four news panels on every
    competitor profile sat empty for most of every two-hourly cycle. Measured on
    production 2026-09-05: the table read 0 rows for the entire time the pass was
    running, then filled with 268 rows across 29 companies when it finished.

    Running it here, immediately after the delete that causes the problem, shrinks
    the empty window from hours to seconds.

    It reads serving.signal_card, which the separate `signals` role writes, so it
    needs no model call and no proposition data -- hence the unused arguments, which
    the STEPS contract requires. It opens its own connection deliberately: this step
    must not join the caller's transaction, or a later step's rollback would take the
    news with it, which is the fault being fixed.

    The entrypoint call stays. It is no longer load-bearing, but it catches cards the
    `signals` role wrote WHILE this pass was running, which this call cannot see.
    """
    import fill_competitor_news
    return fill_competitor_news.run(apply=True)


def step_revenue(cur, con, docs, props_by_doc, limit=None):
    """Fill serving.competitors.sales -- the Profile panel's "Annual revenue / sales".

    Runs INSIDE the pass, on the caller's cursor, and that is the whole point. The
    column is rebuilt with the rest of the row, and any writer that opens its own
    connection has to queue behind this pass's own lock: step_companies deletes every
    origin='pipeline' competitor and then sits idle-in-transaction for the length of its
    profile calls, so an outside --apply blocks for the better part of an hour. Here the
    rows have just been re-inserted by step_companies and the lock is already ours.

    The source is `extracted.proposition` only -- never a company's own website. See
    signals/fill_revenue.py for what counts as an annual revenue and what does not.
    """
    import fill_revenue
    found = fill_revenue.collect(cur)
    n = 0
    for cid, rows in found.items():
        cur.execute("""UPDATE serving.competitors SET sales = %s::jsonb
                        WHERE comp_id = %s""",
                    (json.dumps(rows, ensure_ascii=False), cid))
        n += cur.rowcount
    con.commit()
    cur.execute("SELECT count(*) FROM serving.competitors")
    total = cur.fetchone()[0]
    print("revenue: %d of %d competitor(s) have an annual figure in the corpus"
          % (n, total), flush=True)
    return {"written": n, "companies": len(found), "total": total}


def step_founded(cur, con, docs, props_by_doc, limit=None):
    """Fill serving.competitors.starting_year -- the Profile panel's "Starting year".

    The column existed, was carried across rebuilds by roster.CARRIED_COLUMNS, and was
    empty on every one of the 44 shown competitors, because its only writer reads a
    hand-maintained workbook and is not a step. Same shape as step_revenue: runs on the
    caller's cursor inside the pass, after step_companies has re-inserted the rows.

    See signals/fill_founded.py for what counts as a founding and what does not -- the
    short version is that the founding verb must be passive, because "Lockheed created
    the Skunk Works division in 1943" is not Lockheed's founding year.
    """
    import fill_founded
    found = fill_founded.collect(cur)
    n = 0
    for cid, (year, _votes, _exact) in found.items():
        cur.execute("UPDATE serving.competitors SET starting_year = %s "
                    "WHERE comp_id = %s", (year, cid))
        n += cur.rowcount
    con.commit()
    print("founded: %d competitor(s) given a founding year" % n, flush=True)
    return {"written": n, "companies": len(found)}


# ----------------------------------------------------------------------------- driver

STEPS = [("companies", step_companies), ("news", step_news), ("revenue", step_revenue),
         ("founded", step_founded),
         ("partnerships", step_partnerships),
         ("structure", step_structure), ("metrics", step_metrics),
         ("geo", step_geo), ("tenders", step_tenders),
         ("innovations", step_innovations), ("sources", step_sources),
         ("matchups", step_matchups)]


def _open(dsn):
    """A fresh connection + cursor. Keepalives because this pass runs for hours and
    an idle socket through a tunnel is reaped silently."""
    import psycopg2
    con = psycopg2.connect(dsn, connect_timeout=10, keepalives=1,
                           keepalives_idle=30, keepalives_interval=10,
                           keepalives_count=3)
    return con, con.cursor()


def _live(con):
    """True if the connection can still answer. Cheap, and never raises."""
    try:
        c = con.cursor()
        c.execute("SELECT 1")
        c.fetchone()
        con.commit()
        return True
    except Exception:                                                # noqa: BLE001
        return False


def run(only=None, limit=None, dsn=DSN):
    con, cur = _open(dsn)
    docs = load_docs(cur)
    props_by_doc = load_props(cur)
    banned = suppressed_ids()
    n_sup = sum(1 for d in list(docs) if d in banned)
    for d in banned:                     # audit-suppressed docs feed NO step
        docs.pop(d, None)
        props_by_doc.pop(d, None)
    print("corpus: %d document(s), %d with propositions, %d suppressed by audit"
          % (len(docs), len(props_by_doc), n_sup), flush=True)

    # A pass is seven steps and several hours. It used to share ONE connection with no
    # handler, so anything that closed that socket -- a pg_terminate_backend during
    # unrelated maintenance, a Postgres restart, the tunnel dropping -- killed the pass
    # at whichever step it was on, and every LATER step's work went with it. In
    # production that meant step 1 of 7 died and six tables were never written at all.
    #
    # Each step now stands alone: a checked connection, one reconnect-retry, and its
    # failure recorded rather than raised. That is safe because every step does its own
    # DELETE ... origin='pipeline' and a single commit at the end -- a step that dies
    # before its commit rolls back its own delete, so the table keeps the rows from the
    # last good pass instead of being emptied.
    results, failed = {}, []
    for name, fn in STEPS:
        if only and name != only:
            continue
        print("== step: %s ==" % name, flush=True)
        for attempt in (1, 2):
            if not _live(con):
                try:
                    con.close()
                except Exception:                                    # noqa: BLE001
                    pass
                try:
                    con, cur = _open(dsn)
                    print("  reconnected before %s" % name, flush=True)
                except Exception as e:                               # noqa: BLE001
                    print("  reconnect failed: %s: %s" % (type(e).__name__, e),
                          flush=True)
                    results[name] = {"error": "reconnect: %s" % e}
                    failed.append(name)
                    break
            try:
                results[name] = fn(cur, con, docs, props_by_doc, limit=limit)
                break
            except Exception as e:                                   # noqa: BLE001
                print("  step %s failed (attempt %d/2): %s: %s"
                      % (name, attempt, type(e).__name__, e), flush=True)
                try:
                    con.rollback()
                except Exception:                                    # noqa: BLE001
                    pass
                if attempt == 2:
                    results[name] = {"error": "%s: %s" % (type(e).__name__, e)}
                    failed.append(name)
    try:
        con.close()
    except Exception:                                                # noqa: BLE001
        pass
    _v = via_counts()
    if _v:
        # WHERE THE ANSWERS CAME FROM, on the same line as what was written. A pass
        # that quietly ran on the CPU fallback looks identical to a good one in every
        # other number this prints.
        print("backends: " + ", ".join("%s=%d" % kv for kv in sorted(_v.items())) +
              ("" if set(_v) <= {"farm"} else
               "   <-- NOT all from the farm; these rows are not %s output" % MODEL),
              flush=True)
    print("done:", json.dumps(results), flush=True)
    if failed:
        # Loud, so the entrypoint's "(continuing)" is not the only trace of a skip.
        print("PASS INCOMPLETE: %d of %d step(s) failed: %s"
              % (len(failed), len(results), ", ".join(failed)), flush=True)
    else:
        print("PASS COMPLETE: all %d step(s) ran" % len(results), flush=True)
    return results


def _demo():
    # --- shared envelope ---
    assert _json_reply("NONE") is None and _json_reply("") is None
    assert _json_reply('junk {"a": 1} junk') == {"a": 1}
    assert _json_reply("{broken") is None
    assert _s("  x  ") == "x" and _s("") is None and _s("null") is None
    assert _s(3) is None and _s("N/A") is None
    assert slug("Bharat Forge Ltd.") == "bharat-forge-ltd"
    assert _in_hay("Nagpur, India", "the nagpur plant") is True
    assert _in_hay("Stockholm", "no such city here") is False
    # the strengthened guard (audit C3): one weak token is no longer enough
    assert _in_hay("artillery systems", "artillery and gun systems") is True, \
        "two content tokens the statements carry"
    assert _in_hay("naval systems", "the naval yard") is False, \
        "ONE generic content token no longer passes for grounding"
    assert _in_hay("Rheinmetall", "rheinmetall won the order") is True, \
        "a proper noun the statements carry passes on its own"
    assert _in_hay("arms", "armscor of south africa") is False, "word boundaries hold"
    assert _designators("F-22 Raptor") == {"f-22", "raptor"}, \
        "an alphanumeric designator stays whole -- a bare '22' matches any number"
    assert _designators("defence systems") == set(), "generic lowercase names nothing"
    # sentence-by-sentence grounding of free prose
    hay_lm = ("lockheed martin will modernize the f-22 raptor for the u.s. air force "
              "under a maintenance and modernization contract")
    two = ("Lockheed Martin modernizes the F-22 Raptor for the U.S. Air Force. "
           "It also builds the F-35 Lightning II for the Belgian Navy.")
    got = ground_text(two, hay_lm, "Lockheed Martin")
    assert got and "F-22" in got and "F-35" not in got, \
        "the sentence naming things the statements never mention is dropped"
    assert ground_text("It has significant contracts and a strong position.",
                       hay_lm, "Lockheed Martin") is None, \
        "generic filler with nothing to check on refuses"
    assert ground_text("The U.S. Air Force awarded the F-22 contract.", hay_lm) \
        is not None, "an abbreviation must not be split into a fragment"
    assert prompt_echo("Land defense systems, artillery, ammunition, armoured "
                       "vehicles, small arms, drones"), "the prompt's own list (H5)"
    assert not prompt_echo("armoured vehicles, artillery"), \
        "a genuine two-item sector is not an echo"
    # --- step 1: profile parser ---
    hay = ("saab delivered carl-gustaf m4 systems from sweden linkoping artillery "
           "saab won an order for carl-gustaf m4 launchers")
    A = '"assess":"Saab delivered Carl-Gustaf M4 systems from Linkoping."'
    ok = parse_profile('{"sector":"artillery systems","hq":"Linkoping, Sweden",'
                       + A + ',"threat":"high","products":["Carl-Gustaf M4",'
                       '"Ghost-9"],"dir":"rival"}', hay, "Saab")
    assert ok and ok["threat"] == "high" and ok["products"] == ["Carl-Gustaf M4"], \
        "unstated product must be dropped"
    assert ok["hq"] is not None
    ok2 = parse_profile('{' + A + ',"hq":"Paris, France","sector":null,'
                        '"threat":null,"products":[],"dir":"other"}', hay, "Saab")
    assert ok2 and ok2["hq"] is None, "hallucinated hq nulls, row survives"
    assert parse_profile('{' + A + ',"threat":"URGENT"}', hay, "Saab") is None, \
        "invented threat vocabulary refuses"
    assert parse_profile('{"sector":"x"}', hay) is None, "no assess refuses"
    assert parse_profile("NONE", hay) is None
    # audit C3: an assessment the statements cannot carry refuses the whole row
    assert parse_profile('{"assess":"Saab manufactures the F-22 Raptor for the '
                         'Royal Air Force.","dir":"rival"}', hay, "Saab") is None, \
        "an ungrounded assessment is not a half row, it is no row"
    # audit H5: the prompt's portfolio list, and hedging, never reach `sector`
    echo = parse_profile('{"sector":"Defence manufacturing, including artillery, '
                         'ammunition, armoured vehicles, small arms, and possibly '
                         'drones",' + A + ',"dir":"rival"}', hay, "Saab")
    assert echo and echo["sector"] is None, "the prompt's own words are not data"
    hedged = parse_profile('{"sector":"possibly artillery systems",' + A
                           + ',"dir":"rival"}', hay, "Saab")
    assert hedged and hedged["sector"] is None, "a hedged sector is not a fact"
    # audit M9: a country / ministry / armed force is not a competitor
    for nm in ("US Navy", "Indian Army", "Ministry of Defence", "Saab and Thales"):
        assert parse_profile('{' + A + ',"dir":"rival"}', hay, nm) is None, \
            "%s must never enter the competitor roster" % nm
    # audit M9: a measured rating with its measurement, not a constant 'high'
    t_hi, n_hi = rate_threat(["Archer howitzer", "Spike ATGM"], 5)
    t_lo, n_lo = rate_threat([], 1)
    assert t_hi == "high" and t_lo == "low" and t_hi != t_lo, "the rating varies"
    assert "corpus document" in n_hi and "no KSSL category" in n_lo, \
        "threatNote states what the rating was measured from"
    # audit M9: nav / careers / tag pages are not company updates
    pats, _c = load_terms()
    props_t = [("saab", "wins", "howitzer order")]
    assert usable_update("https://saab.com/newsroom/press-releases/2026/order",
                         "Saab receives howitzer order", pats, props_t)
    assert not usable_update("https://patria.com/careers", "Avoimet ty\u00f6paikat | Patria",
                             pats, props_t), "an open-positions page is not news"
    assert not usable_update("https://brahmos.com/brahmos-in-media", "BrahMos in Media",
                             pats, props_t), "a media index is not one story"
    assert not usable_update("https://defence-industry.eu/tag/rheinmetall",
                             "rheinmetall - Defence Industry Europe", pats, props_t)
    # --- merge (shared identity layer) ---
    m = merge_candidates({"Bharat Forge", "Bharat Forge Limited", "Kalyani", "Saab"})
    assert "Kalyani Strategic Systems" in m, "the client group is ONE canonical identity"
    assert m["Kalyani Strategic Systems"] >= {"Bharat Forge", "Bharat Forge Limited"}
    assert "Saab" in m and is_client("Bharat Forge Ltd") and not is_client("Saab")
    assert canon_name("Rafael") == canon_name("Rafael Advanced Defence Systems")
    # --- step 2: partnership parser ---
    ph = ("arquus and daimler truck signed a joint bid alliance joint venture "
          "to jointly modernise logistics trucks")
    pk = parse_partnership('{"a":"Arquus","b":"Daimler Truck","rel":"jv",'
                           '"basis":"joint venture",'
                           '"note":"agreed to jointly modernise logistics trucks","date":null,"country":null}', ph)
    assert pk and pk["rel"] == "jv", pk
    # A NARROW TYPE MUST POINT AT ITS OWN WORDS. Same answer with no basis: a label with
    # nothing behind it drops to the catch-all rather than being stored as a fact.
    pn = parse_partnership('{"a":"Arquus","b":"Daimler Truck","rel":"jv",'
                           '"note":"agreed to jointly modernise logistics trucks"}', ph)
    assert pn and pn["rel"] == "strategic" and pn["downgraded"], pn
    # ...and a basis the quote never carried is not evidence either.
    pf = parse_partnership('{"a":"Arquus","b":"Daimler Truck","rel":"jv",'
                           '"basis":"a jointly owned company nobody mentioned",'
                           '"note":"agreed to jointly modernise logistics trucks"}', ph)
    assert pf and pf["rel"] == "strategic", pf
    assert parse_partnership('{"a":"Arquus","b":"Boeing","rel":"jv","note":"agreed to jointly modernise logistics trucks"}',
                             ph) is None, "org not in statement refuses"
    assert parse_partnership('{"a":"A","b":"A","rel":"jv","note":"agreed to jointly modernise logistics trucks"}', None) is None
    assert parse_partnership('{"a":"Arquus","b":"Daimler Truck","rel":"BFF",'
                             '"note":"agreed to jointly modernise logistics trucks"}', ph) is None, "unknown rel refuses"
    assert parse_partnership('{"a":"Arquus and Daimler Truck","b":"Renault",'
                             '"rel":"jv","note":"agreed to jointly modernise logistics trucks"}', None) is None,         "two orgs jammed into one field refuse"
    bfh = "bharat forge ltd and paramount group agreed to produce and supply the mbombe 4"
    pc = parse_partnership('{"a":"Bharat Forge Ltd","b":"Paramount Group",'
                           '"rel":"supply","basis":"supply",'
                           '"note":"agreed to jointly modernise logistics trucks"}', bfh)
    assert pc and pc["a"] == "Kalyani Strategic Systems", \
        "the client side folds to the ONE client identity"
    # audit M10: a government noun phrase is not a named organization
    gh = "saab and den brasilianska regeringen signed an agreement"
    assert parse_partnership('{"a":"Saab","b":"den brasilianska regeringen",'
                             '"rel":"strategic","note":"agreed to build aircraft together"}',
                             gh) is None, "'the Brazilian government' is not a name"
    ah = "patria and aalto-yliopisto signed a research agreement together"
    assert parse_partnership('{"a":"Patria","b":"Aalto-yliopisto","rel":"rnd",'
                             '"note":"collaborates"}', ah) is None, \
        "a one-word note states nothing that was agreed"
    assert parse_partnership('{"a":"Patria","b":"Aalto-yliopisto","rel":"rnd",'
                             '"note":"a Rheinmetall \u00e9s a magyar korm\u00e1ny '
                             'k\u00f6z\u00fcl megállapod\u00e1s"}', ah) is None, \
        "an untranslated note belongs in the evidence, not in the label"
    assert is_english("agreed to co-produce the Simha 4x4 in India")
    assert not is_english("k\u00f6z\u00fctti meg\u00e1llapod\u00e1s alapj\u00e1n")
    # --- the ten types, and the four that are not partnerships -------------------
    # Every label must exist, or a real answer stores a KeyError instead of a tie.
    assert set(PART_TYPES) & set(PART_NOT_A_TIE) == set(), \
        "a kind cannot be both storable and refused"
    for _k in PART_TYPES:
        assert REL_PTYPE[_k], "every type prints a label"
    sh = ("rheinmetall and knds signed a joint venture to manufacture supply licence "
          "technology transfer research integrate distribute forged hulls under a "
          "subcontract")
    _BASIS = {"jv": "joint venture", "manufacturing": "manufacture", "supply": "supply",
              "licensing": "licence", "technology": "technology transfer",
              "rnd": "research", "integration": "integrate",
              "distribution": "distribute", "strategic": ""}
    for _rel in PART_TYPES:
        _g = parse_partnership('{"a":"Rheinmetall","b":"KNDS","rel":"%s","basis":"%s",'
                               '"note":"agreed to work together on forged hulls"}'
                               % (_rel, _BASIS[_rel]), sh)
        assert _g and _g["rel"] == _rel, "type %s must survive: %r" % (_rel, _g)
    # The excluded kinds come BACK, they are not None -- a silent refusal is why the
    # acquisitions on the tab went unnoticed for weeks.
    for _rel in PART_NOT_A_TIE:
        _g = parse_partnership('{"a":"Rheinmetall","b":"KNDS","rel":"%s",'
                               '"note":"agreed to work together on forged hulls"}'
                               % _rel, sh)
        assert _g and _g["rel"] == _rel, "%s must be named, not silently dropped" % _rel
    assert parse_partnership('{"a":"Rheinmetall","b":"KNDS","rel":"acq",'
                             '"note":"agreed to work together on forged hulls"}',
                             sh) is None, "the retired six-value keys are not accepted"
    # --- status and ended --------------------------------------------------------
    # "Historical Joint Venture (Ended 2013)" was a TYPE LABEL, because there was
    # nowhere else to say it, and the graph drew it as a live alliance.
    _st = parse_partnership('{"a":"Mahindra","b":"BAE Systems","rel":"jv",'
                            '"basis":"joint venture",'
                            '"note":"the joint venture was dissolved in 2013",'
                            '"status":"ended","ended":"2013"}',
                            "mahindra and bae systems dissolved their joint venture")
    assert _st and _st["status"] == "ended" and _st["ended"] == "2013"
    _st2 = parse_partnership('{"a":"Mahindra","b":"BAE Systems","rel":"jv",'
                             '"basis":"joint venture",'
                             '"note":"the joint venture was dissolved in 2013",'
                             '"status":"active","ended":"2013"}',
                             "mahindra and bae systems dissolved their joint venture")
    assert _st2["status"] == "ended", "a stated end date outranks a guessed status"
    _st3 = parse_partnership('{"a":"Mahindra","b":"BAE Systems","rel":"jv",'
                             '"basis":"joint venture",'
                             '"note":"the two companies agreed to build vehicles",'
                             '"status":"nonsense"}',
                             "mahindra and bae systems agreed a joint venture to build vehicles")
    assert _st3["status"] == "active", "an unusable status falls back, it does not crash"
    # --- confidence --------------------------------------------------------------
    # publishable()'s verdict was computed and thrown away; only its prose was kept.
    _c, _w = tie_confidence(["https://www.rheinmetall.com/x"], "Rheinmetall")
    assert _c == "official", "the maker's own page is official for its own tie"
    _c2, _ = tie_confidence(["https://idrw.org/a", "https://janes.com/b"], "Rheinmetall")
    assert _c2 == "corroborated", "two independent domains corroborate"
    _c3, _ = tie_confidence(["https://idrw.org/a"], "Rheinmetall")
    assert _c3 == "single_source", "one news domain is a single source, and says so"
    assert tie_confidence([], "Rheinmetall")[0] == "single_source", "no source is not official"
    # --- products as objects (the two boundaries) ---
    # Read: every Python consumer wants names, and the reference archive still holds the
    # bare-string form it was seeded with and is never rebuilt into.
    assert product_names(["Carl-Gustaf M4"]) == ["Carl-Gustaf M4"], "the archive's shape"
    assert product_names([{"id": "cg", "name": "Carl-Gustaf M4"}]) == ["Carl-Gustaf M4"]
    assert product_names([{"id": "x"}, {"name": "  "}, None, ""]) == [], \
        "a product with no name is not a product"
    assert product_names(None) == []
    # Write: id and name always; the rest only where there is something behind them.
    _use = [("d1", {"s": "Saab", "p": "delivers", "o": "the Carl-Gustaf M4",
                    "q": "Saab delivers the Carl-Gustaf M4 to Latvia"})]
    _docs = {"d1": {"url": "https://ex/a", "source": "example.com", "title": "t"}}
    _pr = product_rows(["Carl-Gustaf M4", "Carl-Gustaf M4", "Unmentioned Thing"],
                       _use, _docs)
    assert [x["id"] for x in _pr] == ["carl-gustaf-m4", "unmentioned-thing"], \
        "the same product named twice is one row, not two cards"
    assert _pr[0]["source_url"] == "https://ex/a" and _pr[0]["source"] == "example.com", \
        "the statement that named the product is its citation"
    assert "source_url" not in _pr[1], \
        "no statement named it, so there is no source to claim"
    assert not any("description" in x or "image" in x for x in _pr), \
        "the spec asks for both; this pipeline has neither, and absent beats invented"

    # --- step 2b: corporate structure ---
    ohay = ("nexter systems is a subsidiary of knds, which holds 51% of the company")
    o = parse_structure('{"owner":"KNDS","owned":"Nexter Systems","rel":"subsidiary",'
                        '"pct":51,"note":"KNDS holds 51% of Nexter Systems"}', ohay)
    assert o and o["rel"] == "subsidiary" and o["pct"] == 51
    assert o["owner"] == "KNDS" and o["owned"] == "Nexter Systems", \
        "owner and owned are not interchangeable"
    # A percentage nobody stated is the failure that matters most on this dashboard.
    assert parse_structure('{"owner":"KNDS","owned":"Nexter Systems",'
                           '"rel":"subsidiary","pct":74,'
                           '"note":"KNDS holds a stake in Nexter Systems"}',
                           ohay)["pct"] is None, \
        "a number the quote does not carry must not be stored"
    # The client group folds to ONE identity in aliases.canonical, so an article saying
    # Bharat Forge owns KSSL is not an ownership edge to draw -- it is the same company.
    assert parse_structure('{"owner":"Bharat Forge Limited","owned":"Kalyani Strategic '
                           'Systems","rel":"subsidiary","note":"Bharat Forge holds 51% '
                           'of Kalyani Strategic Systems"}',
                           "kalyani strategic systems is a subsidiary of bharat forge "
                           "limited") is None, "the client group is not its own parent"
    jhay = ("saab and patria agreed to establish a joint venture company in finland "
            "to manufacture the carl-gustaf")
    assert parse_structure('{"owner":"Saab","owned":"Patria","rel":"subsidiary",'
                           '"note":"Saab and Patria agreed to establish a joint venture '
                           'in Finland"}', jhay) is None, \
        "a joint venture is a tie, not a parent -- step_partnerships owns it"
    assert parse_structure('{"owner":"Bharat Forge and Kalyani Group","owned":"KSSL",'
                           '"rel":"subsidiary","note":"Bharat Forge owns KSSL outright"}',
                           None) is None, "'X and Y' in one field is two organisations"
    assert parse_structure('{"owner":"the Ministry of Defence","owned":"Denel",'
                           '"rel":"subsidiary","note":"the Ministry of Defence owns '
                           'Denel outright"}', None) is None, \
        "a state owns plenty of this industry; a ministry is not a parent company"
    assert parse_structure('{"owner":"Leonardo","owned":"Leonardo","rel":"subsidiary",'
                           '"note":"Leonardo is a subsidiary of Leonardo SpA"}',
                           None) is None, "a company does not own itself"
    assert parse_structure('{"owner":"Leonardo","owned":"Hensoldt","rel":"partner",'
                           '"note":"Leonardo owns a majority stake in Hensoldt"}',
                           None) is None, "rel outside the closed vocabulary refuses"
    assert parse_structure('{"owner":"Leonardo","owned":"Hensoldt","rel":"subsidiary",'
                           '"note":"owns"}', None) is None, \
        "a one-word note states nothing that can be shown"
    # A subsidiary carrying its parent's name must not become a node pointing at itself.
    # Found by running the real farm model over the real corpus: "Leonardo DRS is a wholly
    # owned subsidiary of Leonardo S.p.A." is true, both names are distinct, and both land
    # on the one roster row called Leonardo. Three of the first eight edges were self-loops.
    _land = {"leonardo": ["Leonardo", "Leonardo S.p.A.", "Leonardo DRS"],
             "rheinmetall": ["Rheinmetall", "American Rheinmetall Vehicles"]}
    for _cid, _names in _land.items():
        for _a in _names:
            for _b in _names:
                assert slug(_a).startswith(_cid[:6]) or _cid[:6] in slug(_a), \
                    "%s must resolve toward %s" % (_a, _cid)
    # parse_structure cannot catch it -- it compares NAMES, and these differ:
    assert parse_structure('{"owner":"Leonardo S.p.A.","owned":"Leonardo DRS",'
                           '"rel":"subsidiary","note":"Leonardo DRS is a wholly owned '
                           'subsidiary of Leonardo S.p.A."}',
                           "leonardo drs is a wholly owned subsidiary of leonardo s.p.a.") \
        is not None, "the statement is true and the parser must accept it"
    # ...so step_structure refuses it at the write, where the roster row is known.

    # A patent's assignee is not a parent company. Real corpus: five statements phrase it
    # as "<patent number> is owned by <company>", and each would have put a patent number
    # on the structure graph as a subsidiary.
    assert parse_structure('{"owner":"Toyota","owned":"JP7068126B2","rel":"subsidiary",'
                           '"note":"JP7068126B2 is owned by Toyota Motor Corporation"}',
                           None) is None, "a patent number is not a company"
    # the regexes that decide which statements are even asked about
    assert OWN_RX.search("is a wholly-owned subsidiary of")
    assert OWN_RX.search("acquired a controlling stake in")
    assert not OWN_RX.search("signed a memorandum of understanding with"), \
        "a partnership must not be asked an ownership question"
    assert not OWN_RX.search("agreed to establish a joint venture"), \
        "PART_RX owns joint ventures; OWN_RX must not claim them too"
    # `arm of` stays: 14 of the 20 statements it selects from the real corpus are real
    # ownership, and the physical arms it also catches carry no proper name to survive on.
    assert OWN_RX.search("operates as the U.S. arm of QinetiQ Group plc")

    # --- step 2c: corpus mention volume ---
    # The window arithmetic, which is the whole step: a document lands in exactly one
    # bucket or in neither, and the boundaries are inclusive at the near end.
    import datetime as _dt
    _today = _dt.date(2026, 9, 4)
    _cur_from = _today - _dt.timedelta(days=METRIC_WINDOW_DAYS - 1)
    _prev_from = _cur_from - _dt.timedelta(days=METRIC_WINDOW_DAYS)

    def _bucket(d, end=_today):
        if d > end:
            return None                   # the crawl's unsettled tail counts nowhere
        return "now" if d >= _cur_from else ("prev" if d >= _prev_from else None)

    assert _bucket(_today) == "now", "the window's last day counts in it"
    assert _bucket(_today + _dt.timedelta(days=1)) is None, \
        "a day past the window end is in neither bucket"
    assert _bucket(_cur_from) == "now", "the window is inclusive at its near edge"
    assert _bucket(_cur_from - _dt.timedelta(days=1)) == "prev"
    assert _bucket(_prev_from) == "prev"
    assert _bucket(_prev_from - _dt.timedelta(days=1)) is None, \
        "older than two windows is in neither bucket, not silently in the previous one"
    assert (_cur_from - _prev_from).days == METRIC_WINDOW_DAYS, \
        "the two windows must be the same width or the percentage is meaningless"
    # The window ends where the CORPUS ends, not where the calendar does. Measured on
    # real data 2026-09-04: the crawl was three days behind, so a calendar-anchored
    # window covered three near-empty days and every company read as down 25-88%.
    assert METRIC_SETTLE_DAYS > 0, \
        "a window ending today counts days the crawler has not reached yet"

    def _pct(now_n, prev_n, corpus_now=100, corpus_prev=100):
        if not (prev_n and corpus_now and corpus_prev):
            return None
        return round(((now_n / float(corpus_now)) - (prev_n / float(corpus_prev)))
                     * 100.0 / (prev_n / float(corpus_prev)), 1)

    assert _pct(12, 8) == 50.0            # equal corpora -> the raw ratio
    assert _pct(8, 12) == -33.3
    assert _pct(0, 4) == -100.0
    assert _pct(7, 0) is None, \
        "no baseline, no percentage -- '+100%' against zero is a division, not a trend"
    assert _pct(0, 0) is None
    # THE ONE REAL DATA FOUND, kept with its real numbers. Measured 2026-09-04 the crawler
    # put 847 documents in the current window against 423 in the previous, and Boeing
    # went 25 -> 51. On raw counts that is +104% and the whole roster read as an
    # industry-wide surge. Against the corpus it is a company roughly holding its share.
    assert _pct(51, 25, 847, 423) == 1.9, \
        "the percentage must survive the crawl doubling, or it measures the crawler"
    assert _pct(50, 25, 850, 425) == 0.0, \
        "double the mentions in double the corpus is no change in share"
    assert _pct(7, 4, 0, 100) is None, "an empty corpus window has no share to compare"
    # The columns that must NOT exist. This dashboard printed a share price of 1,428.50
    # INR for every company on the roster, private firms and state arsenals included,
    # and check_no_fabrication.mjs fails the build on its marker strings. The table is
    # the other half of that guard.
    _sql = (Path(__file__).resolve().parents[2] / "db" / "02_serving.sql")
    if _sql.exists():
        _tbl = _sql.read_text().split("CREATE TABLE serving.competitor_metrics")[1]
        _tbl = _tbl.split(");")[0]
        for _banned in ("share_price", "currency", "price_change"):
            assert _banned not in _tbl, \
                "%s has no source in this system; it must not exist as a column" % _banned

    # --- step 3: geo ---
    pats = build_countries()
    assert find_countries("an order from Lithuania", pats) == ["Lithuania"]
    assert find_countries("the United States army", pats) == ["USA"]
    assert find_countries("nothing here", pats) == []
    g = parse_geo('{"name":"Carl-Gustaf M4 order","note":"Saab delivered the order",'
                  '"act":"export","since":"2026"}')
    assert g and g["c"] == "ex" and g["since"] == "2026"
    note_ok = '"note":"BAE Systems is located in Cumbria, UK"'
    assert parse_geo('{"name":"X",' + note_ok + ',"act":"unclear","since":"soon"}') \
        is None, "audit M8: 'unclear' is not a presence -- a HQ address, an office, " \
        "a bare 'has presence in X' and a future intention all came back unclear"
    assert parse_geo('{"name":"X",' + note_ok + ',"act":"headquartered"}') is None, \
        "activity outside the closed vocabulary refuses"
    assert parse_geo('{"name":"",' + note_ok + '}') is None
    # audit M8: the activity code must be visible in the statements
    ghay = ("denel procures 75% of its inputs from suppliers, of which 75% are "
            "located in south africa")
    assert parse_geo('{"name":"local supplier network","note":"Denel procures 75% of '
                     'its inputs from South African suppliers","act":"production"}',
                     ghay) is None, "supplier procurement is not local production"
    phay = "saab and kssl agreed to establish a joint venture company in india"
    assert parse_geo('{"name":"joint venture","note":"Saab and KSSL to establish a '
                     'joint venture in India","act":"partnership"}', phay), \
        "a partnership the quotes state survives"
    assert parse_geo('{"name":"plant","note":"Saab invested 40 million in India",'
                     '"act":"partnership"}', phay) is None, \
        "a number the statements do not carry refuses the row"
    # audit C4: the row must cite the statement it was summarised FROM
    items = [("d_howitzer", {"s": "India", "p": "buys", "o": "M777 howitzers",
                             "q": "India clears ultra-light howitzers buy from US"}),
             ("d_saab", {"s": "Saab", "p": "to establish", "o": "joint venture in India",
                         "q": "Saab and KSSL to establish a joint venture company"})]
    hit = pick_src("joint venture company Saab KSSL India", items)
    assert hit is not None and items[hit][0] == "d_saab", \
        "the summary cites the Saab statement, not the group's first statement"
    assert pick_src("hypersonic missile in Norway", items) is None, \
        "a summary no statement carries has no source, so no row"
    # --- step 4: tender ---
    cats = kssl_cats()
    th = "poland orders 155mm ammunition worth $120 million, 50,000 rounds"
    tk = parse_tender('{"title":"T","issuer":"MoD","country":"Poland",'
                      '"cat":"Ammunition","value":"$120 million","qty":"50,000",'
                      '"deadline":null,"status":"awarded"}', cats, th)
    assert tk and tk["value"] == "$120 million" and tk["status"] == "awarded"
    tj = parse_tender('{"title":"T","cat":"Ammunition","value":"$999 million"}',
                      cats, th)
    assert tj and tj["value"] is None, "invented number nulls the field"
    assert parse_tender('{"title":"T","cat":"Lasers"}', cats, th) is None, \
        "category outside KSSL_CATS refuses"
    assert parse_tender('{"title":"T","cat":"Ammunition","status":"pending"}',
                        cats, th) is None, "unknown status refuses"
    # audit H3: a procurement has to be IN the quotes, and the client is not a buyer
    assert PROCURE_EV_RX.search("Poland ordered 155mm ammunition worth $120 million")
    assert not PROCURE_EV_RX.search("KSSL unveiled the MArG 39 howitzer at Eurosatory")
    assert is_client("Kalyani Strategic Systems"), \
        "the client-group check the tender step refuses an 'issuer' on"
    # --- step 5: innovation ---
    ids = [c["id"] for c in REF["techCats"]]
    ih = "rheinmetall demonstrated the fv-014 loitering munition by 2027"
    ik = parse_innov('{"area":"uav","t":"T","mat":"dev","driver":"Rheinmetall",'
                     '"body":"B","impact":"I","horizon":"2027"}', ids, ih)
    assert ik and ik["area"] == "uav" and ik["driver"] == "Rheinmetall"
    assert parse_innov('{"area":"lasers","t":"T","body":"B","impact":"I"}',
                       ids, ih) is None, "unknown area refuses, never 'other'"
    ik2 = parse_innov('{"area":"uav","t":"T","mat":"soon","driver":"Boeing",'
                      '"body":"B","impact":"I","horizon":null}', ids, ih)
    assert ik2 and ik2["mat"] is None and ik2["driver"] is None
    # audit H6: shown at a show is not in service
    sh = ("kssl kalyani strategic systems unveiled the simha 4x4 at eurosatory 2026 "
          "bharat forge and paramount showcased the vehicle")
    cap = parse_innov('{"area":"armoured","t":"Simha 4x4 unveiled at Eurosatory",'
                      '"mat":"fielded","driver":"KSSL","body":"KSSL unveiled the '
                      'Simha 4x4 at Eurosatory 2026.","impact":"I"}', ids, sh)
    assert cap and cap["mat"] == "dev", "an unveiling caps maturity at development"
    assert parse_innov('{"area":"armoured","t":"Simha 4x4 inducted","mat":"fielded",'
                       '"driver":"KSSL","body":"The Indian Army inducted the Simha '
                       '4x4.","impact":"I"}', ids, sh)["mat"] == "fielded", \
        "an induction still reads as fielded"
    # audit H4: ONE identity per driver, and never two organizations in one field
    for spelling in ("KSSL", "Bharat Forge Limited", "Kalyani Group",
                     "Kalyani and Paramount"):
        got = parse_innov('{"area":"armoured","t":"T","driver":"%s","body":"B",'
                          '"impact":"I"}' % spelling, ids, sh)
        assert got and got["driver"] == "Kalyani Strategic Systems", \
            "%s is the client group, one driver identity" % spelling
    two = parse_innov('{"area":"uav","t":"T","driver":"Rheinmetall and Leonardo",'
                      '"body":"B","impact":"I"}', ids,
                      "rheinmetall and leonardo demonstrated the drone")
    assert two and two["driver"] is None, "two orgs in one driver field refuse"
    # audit H6/H4: language variants of one page, and one product story, dedupe
    assert url_key("https://brahmos.com/page/ru-brahmos-ng") == \
        url_key("https://brahmos.com/page/brahmos-ng"), "one story, two languages"
    assert url_key("https://brahmos.com/page/brahmos-ii") != \
        url_key("https://brahmos.com/page/brahmos-ng"), "different pages stay apart"
    assert product_key("KSSL and Paramount unveiled Simha 4x4 LAMV") == \
        product_key("KSSL unveiled Simha 4x4 armoured vehicle") == frozenset({"4x4"})
    assert product_key("KSSL unveiled MArG 45") != product_key("KSSL unveiled MArG 39")
    assert product_key("Developing heavy-lift airships") == frozenset(), \
        "no designator, no product-level dedupe (the title rule still applies)"
    # --- step 7: matchup helpers ---
    band = categorise_product("Carl-Gustaf M4")
    assert band is None or band in REF["CAT_KEY"].values()
    assert categorise_product("Hero-120 loitering munition") == "uav", \
        "the product NAME decides the band -- there is no context fallback left"
    # audit H7: the article's other sentences can no longer stretch a band
    assert categorise_product("ESS for submarines") != "mro"
    # SPECIFICITY BEATS DICT ORDER. `pav` sits above `uav` and `msl` in CAT_META and carries
    # "vehicle" and "tank", so first-match-wins filed a drone as an Armoured Vehicle and an
    # ATGM as a tank -- visible on the dashboard, since step_matchups files a matchup by this.
    assert categorise_product("unmanned aerial vehicle") == "uav", "a drone is not a truck"
    assert categorise_product("anti-tank guided missile") == "msl", "an ATGM is not a tank"
    # ...without deleting the broad words, which still catch what they are for.
    assert categorise_product("armoured vehicle") == "pav"
    assert categorise_product("main battle tank") == "pav"
    # COLLISIONS, found by banding the live table rather than by reading the list. Both
    # keywords were there for real artillery and both caught something else entirely:
    #   "rocket" -> "GMLRS rocket motor", "rocket motors"          propulsion components
    #   "towed"  -> "towed low-frequency variable-depth sonar"     a sonar
    # A rocket-motor maker was counting toward an artillery threat rating and being filed as
    # an artillery matchup. Narrowed to phrases, which keeps what they were for.
    for term in ("GMLRS rocket motor", "rocket motors",
                 "towed low-frequency variable-depth sonar"):
        assert categorise_product(term) is None, \
            "%r must not band as artillery: %s" % (term, categorise_product(term))
    for term in ("rocket launcher", "towed howitzer", "155mm towed gun", "Pinaka MLRS"):
        assert categorise_product(term) == "art", "%r is artillery" % term

    # Vocabulary that was simply absent, including KSSL's OWN core business: the pc band knew
    # "forging" but not "forged", "gun barrel" or "crankshaft", and mro knew "overhaul" but
    # not "powertrain" or "running gear" -- the two phrases counterRules uses to describe it.
    for term, band in (("warhead", "ammo"), ("projectile", "ammo"), ("mortar", "art"),
                       ("turret", "pav"), ("chassis", "pav"), ("gun barrel", "pc"),
                       ("crankshaft", "pc"), ("powertrain", "mro"), ("running gear", "mro")):
        assert categorise_product(term) == band, \
            "%r should band as %s, got %s" % (term, band, categorise_product(term))
    # A radar and a fighter jet must STILL band as nothing -- the additions must not have
    # widened the vocabulary into businesses KSSL is not in.
    assert categorise_product("Su-30MKI") is None and \
        categorise_product("AirMaster S radar") is None, \
        "a fighter and a radar are not KSSL categories, and no neighbouring "         "keyword may make them one"
    for generic in ("circuit cards", "gunner hand stations", "commander hand stations",
                    "logistics trucks", "air and missile defense systems",
                    "strategic equipment", "new long-range air-to-air missile"):
        assert not is_product_name(generic), "'%s' names no thing" % generic
    for named in ("Carl-Gustaf M4", "Nimbrix", "TPS-77 MMR radars", "Simha 4x4",
                  "ESS for submarines", "Panther main battle tank"):
        assert is_product_name(named), "'%s' is a named system" % named
    sp = extract_specs("the gun has a range of 40 km and weight of 17,700 kg")
    assert sp and sp[0]["l"] == "Range" and sp[0]["cn"] == 40.0
    assert sp[0]["kv"] is None and sp[0]["hi"] is None, "KSSL side stays undisclosed"
    assert extract_specs("no numbers stated here") == []
    # ---------------------------------------------------- the competitor test (audit 2026-09)
    # Every profile below is a REAL row from serving.competitors, quoted from the live table,
    # so these assert what the pipeline actually produced -- not what it might produce.
    def _p(dir_, products, assess, sector=""):
        return {"dir": dir_, "products": products, "assess": assess, "sector": sector}

    # 1. PORTFOLIO OVERLAP. Every case below is a row that is in serving.competitors today.
    #    Doodle Labs makes jam-resistant mesh radios for drones -- a defence manufacturer that
    #    competes with KSSL in nothing.
    doodle = _p("rival", ["radio systems"],
                "Doodle Labs specializes in radio systems for unmanned systems operating in "
                "contested environments, particularly jam-resistant drones.",
                "Unmanned Systems, Radio Communications")
    ok, why = competes_with_kssl(doodle)
    assert not ok and "not KSSL's business" in why, "a radio maker is not a gun rival: %s" % why
    assert not competes_with_kssl(_p("rival", ["demonstration satellite"], "space", "Space"))[0]
    assert not competes_with_kssl(_p("rival", ["advanced sonar and optical sensors"],
                                     "marine", "marine technology"))[0]
    # ...and the SECTOR must not rescue it. Doodle Labs' sector says "Unmanned Systems"
    # because that is the market it SELLS INTO, which is exactly not the same as competing.
    assert not competes_with_kssl(doodle)[0], "sector text must not readmit a supplier"

    # A MIXED product list must survive. One stray entry is not evidence about the company:
    # `products` is whatever the recent corpus mentioned, not a catalogue. Leonardo -- which
    # builds 76mm naval guns -- is in the table on "TacSAR" and "SPC Cloud e Sicurezza",
    # neither of which bands anywhere. The NAME is what saves it, through the client's own
    # matchup archive; the same profile without a name is correctly refused, because then
    # there is no evidence of a KSSL product anywhere in the row.
    leo = _p("rival", ["TacSAR", "SPC Cloud e Sicurezza"], "defence")
    ok, why = competes_with_kssl(leo, "Leonardo")
    assert ok and "naval" in why, "the archive matches Leonardo on 76mm naval guns: %s" % why
    assert not competes_with_kssl(leo)[0], \
        "with no name and no banding product there is nothing to admit on"
    assert competes_with_kssl(_p("rival", ["NASAMS", "PROTECTOR Remote Weapon Stations",
                                           "surveillance radars"], "defence"))[0]
    # Brand-named products carry no category word and must NOT be read as out of portfolio.
    assert competes_with_kssl(_p("rival", ["Switchblade", "Shrike", "Puma"], "defence"))[0], \
        "AeroVironment is a real UAV rival, brand names and all"
    # A company that plainly makes a KSSL product is admitted even beside a denied one.
    assert competes_with_kssl(_p("rival", ["155mm ammunition", "radar"], "defence"))[0]

    # THE PLURAL BUG behind all of this: a product LIST is written in the plural, and the
    # band matcher refused every one of them -- so Adani Defence ("missiles") was recorded as
    # falling in "no KSSL category", which also under-rated its threat.
    assert categorise_product("missiles") == categorise_product("missile") == "msl"
    assert categorise_product("drones") == categorise_product("drone") == "uav"
    assert categorise_product("howitzers") == "art"
    assert competes_with_kssl(_p("rival", ["helicopters", "missiles"], "defence"))[0], \
        "Adani Defence makes missiles; the plural must not hide that"

    # 1b. SUPPLIERS ARE NOT RIVALS. All four sat as dir='rival'. A rival meets KSSL across a
    #     tender; these meet it across a purchase order -- SSAB literally sells KSSL its plate.
    assert not competes_with_kssl(_p("rival", ["metallic airframe assembly"],
        "PTC Industries is an Indian partner casting the saddle, cradle and lower carriage "
        "for the M777.", "defense manufacturing"), "PTC Industries")[0]
    assert not competes_with_kssl(_p("rival", ["drive systems for armored vehicles and ships"],
        "RENK produces drive systems.", "Defence, Marine and Industry"), "RENK Group")[0]
    assert not competes_with_kssl(_p("rival", ["turbomotor", "turboshaft engines"],
        "Safran focuses on propulsion.", "helicopter engines"), "Safran Helicopter Engines")[0]
    assert not competes_with_kssl(_p("rival", ["Armox 500 AM Powder"],
        "military armour.", "Defence materials"), "SSAB")[0]

    #     ...but a BRAND NAME must not be eaten by a material word. "Insta Steel Eagle drone
    #     solution" is a drone; a bare "steel" in the vocabulary deleted it.
    assert competes_with_kssl(_p("rival", ["Insta Steel Eagle drone solution"],
                                 "", "defence"), "Insta")[0], "a Steel Eagle is a drone"
    #     ...and one component beside a real system must never delete the system's maker.
    #     NOTE the product: a remote weapon station bands in NO KSSL category, so this used to
    #     assert the wrong thing -- it passed only because the all-products rule could not
    #     fire. The system has to be one KSSL actually sells for the case to mean anything.
    assert competes_with_kssl(_p("rival", ["155mm artillery shells", "gearboxes"],
                                 "", "defence"), "Nammo")[0], \
        "a gearbox beside artillery shells is a rival, not a supplier"

    # 1c. THE PRODUCTS MUST BE ITS OWN. Palladyne AI is stored holding IAI's loitering
    #     munitions, which it partnered to market -- a software company wearing a rival's
    #     catalogue, and passing every other test on it.
    pal = _p("rival", ["HARPY", "HAROP", "Mini HARPY"],
             "Palladyne AI has formed a strategic partnership with Israel Aerospace "
             "Industries (IAI) to manufacture, integrate, and market IAI\u2019s HARPY, HAROP, "
             "and Mini HARPY loitering munition systems to the U.S. Department of War.")
    ok, why = competes_with_kssl(pal, "Palladyne AI")
    assert not ok and "another company" in why, "IAI's weapons are not Palladyne's: %s" % why
    #     A company's OWN possessive must not condemn it -- which is why the name is passed in.
    kong = _p("rival", ["PROTECTOR remote weapon station"],
              "Kongsberg\u2019s PROTECTOR remote weapon station is fielded widely.", "defence")
    assert not borrowed_products(kong, "Kongsberg Gruppen"), \
        "its own possessive must not read as borrowed"
    assert competes_with_kssl(kong, "Kongsberg Gruppen")[0]

    # 1d. THE CLAUSES THAT THE LIVE TABLE PROVED WERE NEEDED. Every name below was admitted
    #     as dir='rival' in production, and each is a distinct failure mode.
    #     RENK: the client named it a non-competitor and it was STILL admitted, because the
    #     all-products rule needed every one of its eight products to be a component and
    #     "gear units"/"power-packs" were not in the vocabulary.
    renk = _p("rival", ["gear units", "transmissions", "power-packs",
                        "hybrid propulsion systems", "suspension systems", "slide bearings"],
              "", "Defence, Marine and Industry")
    ok, why = competes_with_kssl(renk, "RENK Group")
    assert not ok and "supplies parts" in why, "RENK is a gearbox house: %s" % why
    #     X-Bow: one product that SOUNDS like a system rescued a rocket-motor maker. An
    #     interceptor bands in no KSSL category, so it is not evidence of competing here.
    assert not competes_with_kssl(_p("rival", ["low-cost interceptor (LCI)",
                                               "GMLRS rocket motor"], "", ""),
                                  "X-Bow Systems")[0]
    #     A shipyard is a CUSTOMER for a naval gun, not a rival to one.
    assert not competes_with_kssl(_p("rival", ["Arleigh Burke-class destroyer"], "",
                                     "naval shipbuilding"), "Ingalls Shipbuilding")[0]
    #     None of the nine bands is an aircraft.
    assert not competes_with_kssl(_p("rival", ["Tejas Mk.1A light combat aircraft"], "",
                                     "aerospace"), "Hindustan Aeronautics")[0]
    #     An export agency manufactures nothing; it sells other companies' catalogues.
    ok, why = competes_with_kssl(_p("rival", ["assault rifles"], "", "defense equipment export"),
                                 "ROSOBORONEXPORT")
    assert not ok and "trading house" in why, why

    # 1e. THE ARCHIVE PIN. The client's own reference lists are ground truth, and without
    #     consulting them every tightening eventually deletes a real rival on thin evidence:
    #     L&T builds K9 Vajra but the corpus currently shows only patrol vessels, and Leonardo
    #     builds naval guns but is evidenced by a cloud product.
    assert competes_with_kssl(_p("rival", ["offshore patrol vessel"], "", "shipbuilding"),
                              "Larsen & Toubro")[0], "the archive names L&T a rival"
    #     ...but the pin must come from the lists that ASSERT rivalry, not from every name in
    #     the archive. Sourcing it from reference_names() shielded an aircraft OEM for being
    #     on a country map.
    assert not archive_bands("Hindustan Aeronautics"), \
        "an aircraft OEM on a country map is not a matchup rival"
    assert "naval" in archive_bands("Leonardo"), "Leonardo is matched on 76mm naval guns"
    assert "naval" in archive_bands("Kongsberg"), "Kongsberg is matched on the HUGIN AUV"
    #     ...and the key must survive the legal suffix the archive writes and the corpus
    #     does not. slug() matched neither of these; fold(canonical()) matches both.
    assert archive_bands("Bharat Heavy Electricals") == \
        archive_bands("Bharat Heavy Electricals Limited") != set()

    # 1f. THE BAND IS THE DECISION. 35 of 98 admitted rows made nothing in any of the nine
    #     categories; the old clause needed a second condition that held for exactly one of
    #     them, so it never fired. No band, no row.
    for prods, who in ((["H225M helicopter", "Eurofighter"], "Airbus"),
                       (["Rafale", "Falcon 2000 Albatros"], "Dassault Aviation"),
                       (["corvettes", "submarines"], "Fincantieri"),
                       (["Saildrone Explorer"], "Saildrone"),
                       (["PROTEC3D", "ballistic vests"], "Mehler Protection"),
                       (["demonstration satellite"], "a space startup")):
        assert not competes_with_kssl(_p("rival", prods, "", ""), who)[0], \
            "%s competes with KSSL in none of the nine" % who

    #     The stripper is what makes the client's own broad words safe. `vehicle` must not be
    #     reachable through "unmanned surface vehicle" and `drone` must not be reachable
    #     through "counter-drone": a system built to DEFEAT an X is not an X. Both were live
    #     -- L3Harris's "drone detection system" and Zone 5's "drone-defeat systems" banded
    #     as UAVs, and Destinus's "counter-rocket artillery" banded as artillery.
    for text in ("unmanned surface vehicle", "counter-drone system", "drone detection system",
                 "drone-defeat systems", "counter-rocket artillery", "naval shipbuilding",
                 "software-defined vehicle platform"):
        assert gate_band(text) is None, "%r must not band" % text
    #     ...but the stripping must not eat the keywords themselves. A bare `aircraft` in the
    #     strip list deletes the uav keyword "unmanned aircraft system", which is TEKEVER's
    #     AR5 -- a real UAV rival refused by a rule aimed at Rafale.
    assert gate_band("AR5 unmanned aircraft system") == "uav", "an unmanned aircraft is a UAV"
    assert gate_band("R400 RWS") == "pav" and gate_band("Negev LMG") == "sa"

    # 1g. THE ARCHIVE AS A BAND SOURCE, NOT A BYPASS. It used to skip every clause for 41 of
    #     107 rows. A matchup carries `cat`, so it says WHICH category -- which carries the
    #     rows whose products are pure model designations without excusing anything else.
    assert competes_with_kssl(_p("rival", ["Offshore Patrol Vessel (OPV)"], "", ""),
                              "Larsen & Toubro")[0], "the archive matches L&T on K9 Vajra"
    assert not competes_with_kssl(_p("rival", ["Tejas Mk.1A light combat aircraft"], "",
                                     "aerospace"), "Hindustan Aeronautics")[0], \
        "an aircraft OEM the archive never matched is not carried by it"

    # 1h. SECTOR MAY CONFIRM A BAND, NEVER CARRY THE ROW. Measured, sector-only admits were
    #     four rows and three were wrong: Firestorm Labs' only product is a 3D-printing
    #     factory, and its sector says "Unmanned Aerial Systems".
    assert not competes_with_kssl(_p("rival", ["xCell"], "",
                                     "Unmanned Aerial Systems, 3D Printing"),
                                  "Firestorm Labs")[0], "a sector is a market, not a product"

    # 1i. THE pc/mro TENSION. Two of the nine categories ARE component businesses, so "sells
    #     parts" cannot disqualify on its own -- a forging house competes with KSSL for
    #     exactly the forging tender. The client settled the gearbox case by naming RENK.
    assert competes_with_kssl(_p("rival", ["155mm shell forgings", "gun barrel forgings"],
                                 "", ""), "a forging house")[0], "forgings ARE a KSSL line"
    ok, why = competes_with_kssl(_p("rival", ["titanium castings",
                                              "metallic airframe assembly"], "", ""),
                                 "PTC Industries")
    assert not ok and "supplies parts" in why, "PTC casts for BAE; BAE is the rival: %s" % why

    # 1j. THE ROLE. The model's own judgement produced 103 of 110 refusals in a full rebuild
    #     and all six regexes together produced 3 -- so ask it directly. A supplier, a trader
    #     and a consumer brand are things no regex reliably separates.
    for role in NOT_RIVAL_ROLES:
        ok, why = competes_with_kssl({"dir": "rival", "role": role, "products": ["155mm shell"],
                                      "assess": "", "sector": ""}, "Someone")
        assert not ok and role in why, "role=%s is not a prime: %s" % (role, why)
    assert competes_with_kssl({"dir": "rival", "role": "prime", "products": ["155mm shell"],
                               "assess": "", "sector": ""}, "Someone")[0]
    #     An unknown or absent role decides nothing; the clauses still run.
    assert competes_with_kssl({"dir": "rival", "role": None, "products": ["155mm shell"],
                               "assess": "", "sector": ""}, "Someone")[0]

    # 2. THE NAMED CASE. Accenture sat in serving.competitors with dir='other', threat NULL
    #    and no products at all. The model had answered correctly; step_companies wrote the
    #    row regardless, because nothing ever asked whether a competitor is what this is.
    ok, why = competes_with_kssl(_p("other", [], "Accenture is involved in delivering digital "
        "enablement and integrated decision support capabilities for defense logistics and "
        "information systems.", "defense services and solutions"))
    assert not ok and "not a rival" in why, "Accenture is not a competitor: %s" % why

    # 3. SERVICES BUSINESSES THE MODEL CALLED 'rival'. A tightened prompt should stop these
    #    at the source; the guard is what makes that not merely a hope.
    saic = _p("rival", ["Mobile Protected Firepower (MPF) light tank"],
              "SAIC is a technology integrator that collaborates with other defense "
              "companies to offer advanced solutions for military vehicles and systems.")
    ok, why = competes_with_kssl(saic)
    assert not ok and "services" in why, "an integrator is not a manufacturer: %s" % why
    amentum = _p("rival", ["Unmanned Aerial Systems (UAS)"],
                 "Amentum provides a wide range of services including research and "
                 "development, test and evaluation, and supply chain management.")
    assert not competes_with_kssl(amentum)[0], "a services provider is not a rival"
    appint = _p("rival", ["Warship OS"], "Applied Intuition is bringing commercial autonomy "
                "and software-defined vehicle capabilities to the defense sector.")
    assert not competes_with_kssl(appint)[0], "an autonomy-software vendor is not a rival"

    # 4. NO COMPETING CAPABILITY. A company the corpus never credits with a product of its
    #    own has shown nothing to compete with, however defence-related it plainly is.
    #    Denel and EUROSAM are both real defence firms and both stored with zero products.
    ok, why = competes_with_kssl(_p("rival", [], "EUROSAM is involved in missile defence."))
    assert not ok and "no product" in why, "no stated product is no evidence: %s" % why

    # 5. REAL COMPETITORS ARE PRESERVED -- including ones whose evidence mentions services.
    knds = _p("rival", ["CAESAR", "Boxer", "155mm ammunition"],
              "KNDS produces artillery systems, armoured vehicles and ammunition for "
              "European armies.", "ammunition, artillery, armoured vehicles")
    assert competes_with_kssl(knds)[0], "KNDS must stay a competitor"
    for prof in (_p("rival", ["K9 Thunder"], "Hanwha manufactures self-propelled howitzers."),
                 _p("rival", ["Archer"], "BAE Systems builds artillery systems."),
                 _p("rival", ["Hermes 900"], "Elbit Systems produces unmanned systems.")):
        assert competes_with_kssl(prof)[0], "a plain manufacturer must pass: %s" % prof
    # A manufacturer that ALSO sells integration work is still a manufacturer: the services
    # rule only bites when there is no making anywhere in the evidence.
    #     The product here used to be a frigate. That is no longer a KSSL category -- a yard
    #     BUYS the naval gun KSSL sells -- so the fixture was testing the services rule with a
    #     company the portfolio rule now refuses for an unrelated and correct reason.
    both = _p("rival", ["155mm towed howitzer"], "Babcock is a systems integrator that also "
              "builds artillery at its own factory.")
    assert competes_with_kssl(both)[0], "manufacturing evidence must outrank a services word"
    # Technology areas are not services. Bharat Electronics carries cybersecurity as a
    # product line and must not be disqualified for the word.
    bel = _p("rival", ["Akash weapon system"], "Bharat Electronics supplies radar and "
             "electronic warfare systems.", "Electronics, Cybersecurity, Defence Systems")
    assert competes_with_kssl(bel)[0], "a technology area is not a services business"

    # 6. THE CLIENT IS NOT A RIVAL, and passes through as it always did.
    assert competes_with_kssl(_p("client", [], "KSSL is the client group."))[0]

    # 7. AMBIGUOUS OUTPUT IS REFUSED, never coerced. parse_profile already maps an invented
    #    dir to 'other'; the gate must then keep it out rather than let 'other' mean rival.
    assert not competes_with_kssl(_p("other", ["Something"], "A defence-related firm."))[0]
    assert not competes_with_kssl({})[0] and not competes_with_kssl(None)[0]

    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--only", choices=[s for s, _ in STEPS])
    ap.add_argument("--limit", type=int, default=None,
                    help="cap LLM calls per step (smoke run)")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        run(only=a.only, limit=a.limit, dsn=a.dsn)
