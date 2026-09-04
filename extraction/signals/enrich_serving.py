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
    DSN, MODEL, article_date, ask, clip, date_label, esc, is_dup,
    is_listing, is_recent_ym, is_relevant, kssl_cats, load_terms, parse_date,
    recent_cutoff, suppressed_ids, title_tokens,
)
from llmapi import client as llm_client  # noqa: E402  (every model call goes through the API)
# `publishable` (the tier-graded source bar) lives in the ENGINE's source_tiers; the pipeline's
# own source_tiers.py is a different module (tier_of/LABEL), so load the engine copy by path
# rather than colliding the module name on sys.path.
import importlib.util as _ilu  # noqa: E402
_st_spec = _ilu.spec_from_file_location(
    "engine_source_tiers", str(HERE.parent / "engine" / "source_tiers.py"))
_st = _ilu.module_from_spec(_st_spec); _st_spec.loader.exec_module(_st)  # type: ignore
publishable = _st.publishable  # noqa: E402  (ONE source bar, shared)
from aliases import (  # noqa: E402  (ONE identity layer, shared with serving_fill)
    canonical as canon_name, client_led, fold as fold_name, has_proper_name,
    is_client,
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
ENRICH_WORKERS = max(1, int(os.environ.get("KSSL_ENRICH_WORKERS", "6")))


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
        return text


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

PROFILE_PROMPT = """You profile companies for a defence-intelligence dashboard for KSSL
(Kalyani Strategic Systems, the defence arm of the Kalyani Group / Bharat Forge -- Indian
maker of artillery, ammunition, armoured vehicles, small arms, drones). Below are extracted
statements about "%s", each with its supporting quote.

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
 "dir": "<client if it IS Kalyani/KSSL/Bharat Forge (one group);
         rival ONLY if the statements show this company DESIGNS, MANUFACTURES or SUPPLIES
           physical defence products of its own that compete in KSSL's categories
           (artillery, ammunition, armoured/protected vehicles, small arms, drones and
           loitering munitions, missiles and air defence, naval platforms, forgings);
         otherwise other -- and 'other' is the RIGHT answer for a consultancy, an IT,
           software, cyber or digital-forensics firm, a systems integrator, a logistics,
           staffing or test-and-evaluation services provider, a materials or component
           supplier, a research organisation, a government procurement agency, and for any
           company whose only connection to a product is a partnership to market or
           integrate somebody else's>"}

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
            "products": products, "dir": direction}


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


def rate_threat(products, n_docs):
    """A MEASURED threat rating with the measurement attached, replacing a constant:
    every rival used to be stored 'high', which is not a rating. Inputs are countable
    -- how many KSSL portfolio bands the company's STATED products fall into, and how
    much corpus stands behind it. Returns (threat, threatNote)."""
    key_label = {k: v for v, k in REF["CAT_KEY"].items()}
    bands = sorted({b for b in (categorise_product(p) for p in (products or [])) if b})
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


def competes_with_kssl(prof):
    """-> (admit, reason). Is this profile a DIRECT DEFENCE COMPETITOR, or merely a company
    the corpus mentions near defence?

    This gate exists because there was none. `step_companies` wrote every profile it managed
    to parse straight into serving.competitors, so the table answered the question "who did
    the corpus talk about?" when the dashboard asks "who do we compete against?". Accenture
    sat in it with dir='other', threat NULL and an empty product list -- the model had
    already answered correctly and the code inserted the row anyway.

    Three pieces of evidence are required, which is the definition of a competitor spelled
    out as code:

      manufacturer  -- the model, asked properly, judged it a maker of defence products
                       competing in KSSL's categories (dir == 'rival')
      capability    -- the statements name at least one product of its OWN; a company the
                       corpus never credits with a product has shown no competing capability
      not services  -- its own description is not a services business with no making in it

    A refusal is not a deletion: the profile is still built and still counted, it simply does
    not become a competitor row. `client` is passed through untouched -- KSSL is not its own
    rival, and step_companies has always handled that separately.
    """
    d = (prof or {}).get("dir")
    if d == "client":
        return True, "client"
    if d != "rival":
        return False, "not a rival (dir=%s)" % (d or "none")
    if not (prof.get("products") or []):
        return False, "no product of its own in the statements"
    hay = "%s %s" % (prof.get("assess") or "", prof.get("sector") or "")
    if _SERVICES_RX.search(hay) and not _MAKES_RX.search(hay):
        return False, "services business, no manufacturing evidence"
    return True, "rival"


def load_profiles(cur):
    """Profiled pipeline companies, from the DB (so --only steps stay independent)."""
    cur.execute("""SELECT comp_id, ord, name, dir, hq, products
                     FROM serving.competitors WHERE origin='pipeline' ORDER BY ord""")
    return [{"comp_id": r[0], "ord": r[1], "name": r[2], "dir": r[3], "hq": r[4],
             "products": r[5] or []} for r in cur.fetchall()]


def step_companies(cur, con, docs, props_by_doc, limit=None):
    # Carry interim OSINT columns (agent-populated leadership/facilities, and hq where
    # the corpus has none) across the rebuild. This step DELETEs+re-INSERTs pipeline
    # competitors from the corpus and its INSERT does not carry those columns, so
    # without this snapshot every enrich pass silently wipes them (the Adani-empty bug).
    cur.execute("""SELECT comp_id, leadership, facilities, hq FROM serving.competitors
                     WHERE origin='pipeline'
                       AND (leadership IS NOT NULL OR facilities IS NOT NULL)""")
    _carry = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    # Own range only: revive_partners writes companies the crawl never profiled at
    # ord >= REV_ORD0. A blanket delete took them, and their ties, with it.
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
        use = cprops[:25]
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
        admit, why = competes_with_kssl(prof)
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
                     "srcs": srcs[:8], "site": site})

    rows.sort(key=lambda r: (0 if r["prof"]["dir"] == "rival" else 1,
                             r["name"].lower()))
    for i, r in enumerate(rows, start=1):
        p = r["prof"]
        cid = slug(r["name"])
        cur.execute("""INSERT INTO serving.competitors
                         (comp_id, ord, name, dir, sector, hq, threat, assess, updates,
                          center, partners, site, srcs, products, "threatNote", origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'[]',%s,%s,%s,%s,
                               'pipeline')
                       ON CONFLICT (comp_id) DO NOTHING""",
                    (cid, ORD0 + i, esc(r["name"]), p["dir"], esc(p["sector"]) or None,
                     esc(p["hq"]) or None, p["threat"], esc(p["assess"]),
                     json.dumps(r["upd_html"] if r["updates"] else []),
                     json.dumps({"id": cid, "label": r["name"]}),
                     r["site"], json.dumps(r["srcs"]),
                     json.dumps([esc(x) for x in p["products"]]),
                     p.get("threat_note")))
    # Restore the snapshotted interim columns onto the freshly-rebuilt rows.
    for cid, (ld, fac, hq0) in _carry.items():
        cur.execute("""UPDATE serving.competitors
                         SET leadership = COALESCE(%s::jsonb, leadership),
                             facilities = COALESCE(%s::jsonb, facilities),
                             hq         = COALESCE(NULLIF(hq,''), %s)
                       WHERE comp_id=%s AND origin='pipeline'""",
                    (json.dumps(ld) if ld is not None else None,
                     json.dumps(fac) if fac is not None else None,
                     hq0, cid))
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

PART_RX = re.compile(
    r"(partner|joint venture|\bjv\b|\bmou\b|memorandum|alliance|agreement|"
    r"team(?:ed|ing|s)? up|collaborat|tie-?up|joint bid|licen[cs])", re.I)

PART_PROMPT = """Below is ONE extracted statement from a defence-news article, with its
supporting quote. Decide: does it state a partnership, joint venture, MoU, alliance,
licence or teaming agreement between two NAMED organizations (companies or agencies)?

If not -- or if either side is not a named organization, or the tie is merely announced
intent with no named counterpart -- reply exactly: NONE

Otherwise reply with ONLY this JSON, in ENGLISH:
{"a": "<organization 1 -- ONE name, never 'X and Y'>",
 "b": "<organization 2 -- ONE name, never 'X and Y'>",
 "rel": "<exactly one of: jv | tech | supply | mou | acq | other>",
 "note": "<one line stating what was agreed, exactly as the quote says -- an MoU is not a
          contract, a plan is not a delivery>",
 "date": "<date of the agreement ONLY if stated, else null>",
 "country": "<country of organization b ONLY if stated, else null>"}

If the statement ties THREE or more organizations, pick the one pair the quote actually
binds; if no single pair is asserted, reply NONE.

Article: %s
Statement: %s %s %s
Quote: "%s"
"""


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


def parse_partnership(raw, hay=None):
    d = _json_reply(raw)
    if d is None:
        return None
    a, b = _s(d.get("a"), 90), _s(d.get("b"), 90)
    note = _s(d.get("note"), 300)
    rel = (_s(d.get("rel"), 12) or "").lower()
    if not a or not b or not note:
        return None
    if not is_one_org(a) or not is_one_org(b):
        return None                       # 'X and Y' in one field is two orgs, refused
    if is_force(a) or is_force(b):
        return None                       # 'den brasilianska regeringen' is not a
    if not has_proper_name(a) or not has_proper_name(b):
        return None                       # NAMED organization -- the prompt's own rule
    if not is_english(note):
        return None                       # one-word / untranslated notes are labels
    if hay is not None and not (_in_hay(a, hay) and _in_hay(b, hay)):
        return None                       # both orgs must come from the statement
    a, b = canon_name(a), canon_name(b)   # one identity per side (client group folds)
    if slug(a) == slug(b):
        return None
    if rel not in ("jv", "tech", "supply", "mou", "acq", "other"):
        return None
    return {"a": a, "b": b, "rel": rel, "note": note,
            "date": _s(d.get("date"), 40), "country": _s(d.get("country"), 60)}


REL_PTYPE = {"jv": "Joint venture", "tech": "Technology / ToT",
             "supply": "Supply / customer", "mou": "MoU / strategic",
             "acq": "Acquisition / stake", "other": "Partnership"}


def step_partnerships(cur, con, docs, props_by_doc, limit=None):
    cur.execute("DELETE FROM serving.partner WHERE origin='pipeline' AND ord < %s",
                (REV_ORD0,))
    # Blank only what THIS writer put there. The reset used to empty the column
    # outright, which silently deleted every revived tie on the next run.
    cur.execute("""UPDATE serving.competitors
                      SET partners = coalesce((SELECT jsonb_agg(p) FROM
                            jsonb_array_elements(partners) p
                            WHERE p ? 'origin'), '[]'::jsonb)
                    WHERE origin='pipeline'""")
    profiles = load_profiles(cur)
    if not profiles:
        print("partnerships: no profiled companies -- run companies first", flush=True)
        return {"written": 0, "refused": 0, "skipped": 0}
    prof_rx = [(p, [word_rx(p["name"])]) for p in profiles]

    cands = []
    for did, prs in props_by_doc.items():
        for pr in prs:
            if PART_RX.search(pr["p"]):
                cands.append((did, pr))
    found, refused, seen_pairs, calls = [], 0, set(), 0
    for did, pr in cands:
        if limit and calls >= limit:
            break
        calls += 1
        hay = ("%s %s %s %s" % (pr["s"], pr["p"], pr["o"], pr["q"])).lower()
        try:
            raw = _ask(PART_PROMPT % (docs[did]["title"] or did, pr["s"], pr["p"],
                                      pr["o"], clip(pr["q"], 300)), npredict=300)
        except Exception as e:                                    # noqa: BLE001
            refused += 1
            print("  %s: %s" % (did, e), flush=True)
            continue
        got = parse_partnership(raw, hay)
        if got is None:
            refused += 1
            continue
        key = frozenset((slug(got["a"]), slug(got["b"])))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        got["url"] = docs[did]["url"]
        got["source"] = docs[did]["source"]
        found.append(got)

    comp_partners = {p["comp_id"]: [] for p in profiles}
    client_rows, orphans = [], []
    for g in found:
        landed = False
        for side, other in ((g["a"], g["b"]), (g["b"], g["a"])):
            # The document this tie was read from IS its evidence, and it was being
            # thrown away: five ties reached the tab with no source at all, on a
            # page whose rule is that every tie carries one a reader can check.
            ok, why, _t, _n = publishable([g["url"]], side)
            entry = {"id": slug(other), "label": esc(other),
                     "ptype": REL_PTYPE[g["rel"]], "rel": g["rel"],
                     "note": esc(g["note"]), "country": g["country"],
                     "date": g["date"], "src": g["url"],
                     # honest either way: an uncorroborated single source says so
                     "srcnote": why, "origin": "enriched"}
            if is_client(side):
                client_rows.append((other, g))
                landed = True
            cid = slug(side)
            if cid in comp_partners:
                comp_partners[cid].append(entry)
                landed = True
            else:   # alias form ("Bharat Forge Limited") -> boundary match
                for p, rxs in prof_rx:
                    if any(rx.search(side.lower()) for rx in rxs):
                        comp_partners[p["comp_id"]].append(entry)
                        landed = True
                        break
        if not landed:
            # Neither side is a profiled company or the client: the tie is real but
            # has nowhere to be shown. Counted and named, never silently dropped --
            # 'N ties found' used to be printed over ties nothing stored.
            orphans.append("%s / %s" % (g["a"], g["b"]))
    n_upd = 0
    for cid, plist in comp_partners.items():
        if plist:
            # keep the revived ties this writer did not find -- setting the column
            # outright is how the archive revival got erased the first time
            cur.execute("""UPDATE serving.competitors
                              SET partners = %s::jsonb || coalesce((
                                    SELECT jsonb_agg(p) FROM jsonb_array_elements(partners) p
                                     WHERE p ? 'origin'), '[]'::jsonb),
                                  updated_at = now()
                            WHERE comp_id=%s AND origin='pipeline'""",
                        (json.dumps(plist), cid))
            n_upd += 1
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
    print("partnerships: %d tie(s) found from %d candidate props, %d refused; "
          "%d competitor(s) updated, %d client partner row(s), %d tie(s) stored nowhere "
          "(both sides unprofiled)"
          % (len(found), len(cands), refused, n_upd, len(seen_c), len(orphans)),
          flush=True)
    for o in orphans[:10]:
        print("  not stored: %s" % o, flush=True)
    return {"written": len(found) - len(orphans), "refused": refused,
            "client_rows": len(seen_c), "competitors_updated": n_upd,
            "dropped_unprofiled": len(orphans)}


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
    written, refused, calls, no_src = 0, 0, 0, 0
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
    print("geo: %d presence row(s) written, %d refused, %d with no statement to cite"
          % (written, refused, no_src), flush=True)
    return {"written": written, "refused": refused, "no_src": no_src}


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
    written, refused, dup, calls, own = 0, 0, 0, 0, 0
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
    print("innovations: %d written, %d refused, %d duplicate(s), %d client-group "
          "advance(s) held back (from %d candidate doc(s))"
          % (written, refused, dup, own, len(cand)), flush=True)
    return {"written": written, "refused": refused, "dup": dup, "own": own}


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


def categorise_product(product):
    """CAT_META keyword hit on the PRODUCT NAME -> catKey band, else None (no band ->
    no matchup). The surrounding article text is NOT consulted: that fallback banded
    'ESS for submarines' as Armoured Vehicle MRO, a Su-30MKI fighter as Missiles & Air
    Defence and an AirMaster S radar as UAVs & Drones, all by a keyword that belonged
    to a neighbouring sentence (audit H7). The docstring already refused it; the code
    did it anyway."""
    hay = str(product or "").lower()
    for key, meta in REF.get("CAT_META", {}).items():
        for kw in meta.get("kw", []):
            if len(kw) >= 3 and word_rx(kw).search(hay):
                return key
    return None


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


# ----------------------------------------------------------------------------- driver

STEPS = [("companies", step_companies), ("partnerships", step_partnerships),
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
    ph = "arquus and daimler truck signed a joint bid alliance"
    pk = parse_partnership('{"a":"Arquus","b":"Daimler Truck","rel":"jv",'
                           '"note":"agreed to jointly modernise logistics trucks","date":null,"country":null}', ph)
    assert pk and pk["rel"] == "jv"
    assert parse_partnership('{"a":"Arquus","b":"Boeing","rel":"jv","note":"agreed to jointly modernise logistics trucks"}',
                             ph) is None, "org not in statement refuses"
    assert parse_partnership('{"a":"A","b":"A","rel":"jv","note":"agreed to jointly modernise logistics trucks"}', None) is None
    assert parse_partnership('{"a":"Arquus","b":"Daimler Truck","rel":"BFF",'
                             '"note":"agreed to jointly modernise logistics trucks"}', ph) is None, "unknown rel refuses"
    assert parse_partnership('{"a":"Arquus and Daimler Truck","b":"Renault",'
                             '"rel":"jv","note":"agreed to jointly modernise logistics trucks"}', None) is None,         "two orgs jammed into one field refuse"
    bfh = "bharat forge ltd and paramount group agreed to produce the mbombe 4"
    pc = parse_partnership('{"a":"Bharat Forge Ltd","b":"Paramount Group",'
                           '"rel":"supply","note":"agreed to jointly modernise logistics trucks"}', bfh)
    assert pc and pc["a"] == "Kalyani Strategic Systems", \
        "the client side folds to the ONE client identity"
    # audit M10: a government noun phrase is not a named organization
    gh = "saab and den brasilianska regeringen signed an agreement"
    assert parse_partnership('{"a":"Saab","b":"den brasilianska regeringen",'
                             '"rel":"mou","note":"agreed to build aircraft together"}',
                             gh) is None, "'the Brazilian government' is not a name"
    ah = "patria and aalto-yliopisto signed a research agreement together"
    assert parse_partnership('{"a":"Patria","b":"Aalto-yliopisto","rel":"tech",'
                             '"note":"collaborates"}', ah) is None, \
        "a one-word note states nothing that was agreed"
    assert parse_partnership('{"a":"Patria","b":"Aalto-yliopisto","rel":"tech",'
                             '"note":"a Rheinmetall \u00e9s a magyar korm\u00e1ny '
                             'k\u00f6z\u00fcl megállapod\u00e1s"}', ah) is None, \
        "an untranslated note belongs in the evidence, not in the label"
    assert is_english("agreed to co-produce the Simha 4x4 in India")
    assert not is_english("k\u00f6z\u00fctti meg\u00e1llapod\u00e1s alapj\u00e1n")
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

    # 1. THE NAMED CASE. Accenture sat in serving.competitors with dir='other', threat NULL
    #    and no products at all. The model had answered correctly; step_companies wrote the
    #    row regardless, because nothing ever asked whether a competitor is what this is.
    ok, why = competes_with_kssl(_p("other", [], "Accenture is involved in delivering digital "
        "enablement and integrated decision support capabilities for defense logistics and "
        "information systems.", "defense services and solutions"))
    assert not ok and "not a rival" in why, "Accenture is not a competitor: %s" % why

    # 2. SERVICES BUSINESSES THE MODEL CALLED 'rival'. A tightened prompt should stop these
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

    # 3. NO COMPETING CAPABILITY. A company the corpus never credits with a product of its
    #    own has shown nothing to compete with, however defence-related it plainly is.
    #    Denel and EUROSAM are both real defence firms and both stored with zero products.
    ok, why = competes_with_kssl(_p("rival", [], "EUROSAM is involved in missile defence."))
    assert not ok and "no product" in why, "no stated product is no evidence: %s" % why

    # 4. REAL COMPETITORS ARE PRESERVED -- including ones whose evidence mentions services.
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
    both = _p("rival", ["Type 26 frigate"], "Babcock is a systems integrator that also "
              "builds warships at its own shipyard.")
    assert competes_with_kssl(both)[0], "manufacturing evidence must outrank a services word"
    # Technology areas are not services. Bharat Electronics carries cybersecurity as a
    # product line and must not be disqualified for the word.
    bel = _p("rival", ["Akash weapon system"], "Bharat Electronics supplies radar and "
             "electronic warfare systems.", "Electronics, Cybersecurity, Defence Systems")
    assert competes_with_kssl(bel)[0], "a technology area is not a services business"

    # 5. THE CLIENT IS NOT A RIVAL, and passes through as it always did.
    assert competes_with_kssl(_p("client", [], "KSSL is the client group."))[0]

    # 6. AMBIGUOUS OUTPUT IS REFUSED, never coerced. parse_profile already maps an invented
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
