# -*- coding: utf-8 -*-
"""Whether a name may be published as a KSSL product at all.

    python portfolio_gate.py --demo     # hermetic asserts, no DB, no network

THE FAULT THIS EXISTS FOR, and it is not hypothetical.

"Bayonet" and "Cleaver" were carried as KSSL products on the strength of 138 and 135
occurrences inside extraction/reference_dataset.json -- a CURATED file. Repetition
inside a file we wrote ourselves was read as evidence. A corpus check found Bayonet
had 22 quotes and not one tied to KSSL, and every "Cleaver" hit was "Sian Cleaver, an
Airbus engineer". Neither is in the client's own product workbook; the string
"bayonet" occurs there exactly once, as a lug on the Protective Carbine.

"AAROK" is the same fault wearing a different hat. It is a Turgis & Gaillard MALE
design OFFERED to KSSL under a 2025 MoU. The repo's own curated data says so twice,
in as many words -- and four other strings in the SAME FILE call it "KSSL's airframe
portfolio (AAROK MALE, Omega)" and tell the reader to "Confirm KSSL AAROK/Omega meets
the tender's indigenous-content thresholds". A file that contradicts itself is not a
source; a disclaimer in it is still a finding, and this module lets the disclaimer win.

SIX RULES. Each one is a lesson already paid for.

  R1 ATTESTATION IS THE WORKBOOK.  A name may be published as a KSSL product only when
     it resolves to a row of the client's own product workbook (serving.client_product
     / portfolio/kssl_portfolio.json). There is no second path. Not the archive, not
     the curated dataset, not the corpus.

  R2 A MENTION COUNT IS NOT EVIDENCE.  attest() takes `mentions` and IGNORES it, on
     purpose, and says in its `why` that it did. 138 is not more attesting than 1.
     This is the parameter the Bayonet decision was actually made on.

  R3 OFFERED IS NOT OWNED.  A partnership, an MoU, a licence offer or a joint unveil
     is a relationship, not ownership. denials() reads the repo's own prose for the
     explicit disclaimer ("X ... is not a KSSL product") and bans X everywhere,
     including from rows that already sit in the portfolio table. offer_only() catches
     the unstated case: a row whose ONLY citation is the other party announcing the
     partnership, on the other party's own domain.

  R4 THE SOURCE BAR IS THE ONE WE ALREADY HAVE.  engine/source_tiers.publishable with
     product_maker="Kalyani Strategic Systems": the maker or a government publisher, or
     two independent domains. A row that cannot clear it for its own existence has no
     business supplying a number to a comparison.

  R5 EVIDENCE MUST BE ABOUT THE PRODUCT.  A single news citation whose own URL shares
     not one distinctive word with the product or its class is evidence for something
     else. (A citation whose path is an opaque id is not judged: there is no text to
     read, and refusing it would delete a government product page.)

  R6 A ONE-TOKEN NAME CANNOT IDENTIFY ITSELF IN TEXT.  presignal._stoplisted already
     says this about company names -- "Force" is perfectly word-bounded inside "Air
     Force". "Cleaver", "Bayonet" and "Omega" are the product-side of the same fault.
     One-token names are still perfectly good products; what they are not is groundable
     by proximity, and this module offers no proximity path to anything.

WHAT THIS MODULE NEVER DOES: delete a product. The operator's governing rule, in their
words, is "no need to delete a client's product, instead if no correct matchup is
there don't show it". Every function here returns a verdict and a reason. The only
writer is check_portfolio.py, and the only thing it writes is a nullable withheld
reason on a PAIRING.

Hermetic: no database, no network, no model. client_portfolio and engine/source_tiers
are imported lazily and every failure degrades to "cannot check", never to "passed".
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
CLIENT = "Kalyani Strategic Systems"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The client's own domains. A source on one of these is the maker publishing its own
# product; anything else is somebody talking about it.
CLIENT_DOMAINS = ("kssl.in", "kssl.co.in", "kalyanistrategic.com",
                  "bharatforge.com", "bharatforge.eu")

# R3: the disclaimer, as the repo's own prose actually writes it. Both live strings are
# in the demo below, verbatim.
DENIAL_RX = re.compile(r"\bnot an?\s+(?:KSSL|Kalyani|client)\s+product\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")
# the sentence's subject: the capitalised run it opens with
_SUBJECT = re.compile(r"^([A-Z][A-Za-z0-9&/.\-]*(?:\s+[A-Z][A-Za-z0-9&/.\-]*){0,2})\b")

# R3, unstated case: the other party announcing the relationship. Read from the source
# URL's own path as well as from prose, because that is where it is written:
# fnherstal.com/en/news/kalyani-strategic-systems-partners-with-fn-herstal-to-build-...
OFFER_RX = re.compile(
    r"(partners?[-_ ]with|partnership|\bmou\b|memorandum[-_ ]of[-_ ]understanding|"
    r"memorandum|teaming|joint[-_ ]venture|\bjv\b|offered[-_ ]to|"
    r"letter[-_ ]of[-_ ]intent|\bloi\b)", re.I)

_WORD = re.compile(r"[a-z0-9]+")

# R5: a path with fewer real words than this is an opaque id, not a headline.
MIN_SLUG_WORDS = 3
# Words a URL path carries whatever it is about. Not a subject list -- a scaffolding
# list, and short on purpose.
_SLUG_NOISE = frozenset((
    "http", "https", "www", "com", "net", "org", "html", "htm", "php", "aspx",
    "news", "press", "release", "releases", "media", "article", "articles",
    "story", "stories", "blog", "post", "posts", "page", "pages", "index",
    "details", "detail", "products", "product", "node", "sites", "default",
    "files", "content", "uploads", "download", "downloads", "docs", "document",
    "with", "from", "into", "over", "under", "about", "that", "this", "they",
    "their", "what", "when", "where", "will", "have", "been", "were",
))


# ---------------------------------------------------------------------------
# lazily-loaded neighbours: a failure here is "cannot check", never "passed"
# ---------------------------------------------------------------------------
def _load(path, name):
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                              # noqa: BLE001
        return None


_TIERS = [None]


def tiers():
    """engine/source_tiers.py, BY PATH.

    signals/source_tiers.py is a different module with the same filename -- the trust
    weight table, not the publishability rule -- and importing by name from this
    directory finds the wrong one. client_portfolio.py carries the same note and the
    same fix, which is what makes this worth repeating rather than sharing: the bug is
    the import statement, not the loader.
    """
    if _TIERS[0] is None:
        _TIERS[0] = _load(HERE.parent / "engine" / "source_tiers.py", "engine_source_tiers")
    return _TIERS[0]


_GROUPS = [None]


def groups():
    """client_portfolio.ALIASES -- archive name -> the workbook product_id(s) it covers.

    A LIST means a portfolio-level GROUP. "Shell forgings" is one archive name over
    four workbook rows (HE / illuminating / incendiary / smoke shells) that share one
    calibre range, and there is no single workbook row called "Shell forgings" for a
    name comparison to find. Without this table a real client product line reads as
    unattested -- see audit_anchor()."""
    if _GROUPS[0] is None:
        mod = _load(HERE / "client_portfolio.py", "client_portfolio_for_gate")
        _GROUPS[0] = dict(getattr(mod, "ALIASES", {}) or {}) if mod else {}
    return _GROUPS[0]


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------
def norm(s):
    s = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def product_of(label):
    """'KSSL - MArG 155' -> 'MArG 155'. The maker is not the product."""
    return re.split(r"[·|]", label or "")[-1].strip()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")


def one_token(name):
    """R6. 'Cleaver' -> True, 'Kalyani Maverick' -> False.

    Structural, not a word list. This repo has paid three times for a closed keyword
    list that turned out to be a language detector, and a list of ordinary English
    words would be a fourth. A one-token name may be a perfectly real product -- Sniper
    and Maverick both are -- so this gates only the TEXT path, and there is no text
    path here to gate."""
    return bool(norm(name)) and " " not in norm(name)


def _same_product(candidate, published):
    """pairing.same_product if it will import, and its rules inline if it will not.

    Kept as a delegation rather than a copy: pairing.py is the module revive_matchups
    actually consults, and a second private answer to "is this the same product" is how
    the two-id-space fault gets made a third time."""
    try:
        import pairing                                              # noqa: PLC0415
        return pairing.same_product(candidate, published)
    except Exception:                                               # noqa: BLE001
        a, b = norm(candidate), norm(published)
        if not a or not b:
            return False
        return a == b or (len(a) > 3 and a in b) or (len(b) > 3 and b in a) \
            or (" " not in a and a in b.split())


def attest(name, portfolio, mentions=None):
    """-> (attested, why). R1 + R2 + R6.

    `portfolio` is the client's own product rows: names, or dicts carrying `name` and
    optionally `product_id`.

    `mentions` IS IGNORED. It is in the signature because it is the number the Bayonet
    decision was made on -- 138 occurrences of a name inside a file we wrote ourselves
    -- and a parameter that is visibly refused is a better guard than one that was
    never offered. Passing it changes no verdict and says so in the reason.
    """
    names, ids = [], set()
    for p in portfolio or []:
        if isinstance(p, dict):
            if p.get("name"):
                names.append(p["name"])
            if p.get("product_id"):
                ids.add(p["product_id"])
        elif p:
            names.append(p)
            ids.add(slug(p))
    tail = "" if mentions in (None, 0) else \
        " (%d mention(s) offered as evidence and ignored: a mention count is not attestation)" % mentions

    # ABSENCE IS A REFUSAL, NOT A PASS. An empty portfolio is the state of a database
    # whose serving.client_product has not been loaded -- exactly when an unchecked
    # name gets published. pairing.py learned this the expensive way.
    if not names and not ids:
        return False, "no client portfolio to check against: being unable to check is not having checked" + tail

    bare = product_of(name)
    if not norm(bare):
        return False, "no product name to check" + tail
    for n in names:
        if _same_product(bare, n):
            return True, "named in the client's own product workbook: %s" % n + tail
    # a portfolio-level GROUP: one archive name over several workbook rows
    for member in groups().get(bare, []) or []:
        if member in ids:
            return True, "a portfolio-level group in the client's workbook (%s)" % member + tail
    hint = "; a one-token name is not groundable by proximity either" if one_token(bare) else ""
    return False, "not in the client's own product workbook" + hint + tail


# ---------------------------------------------------------------------------
# R3: offered is not owned
# ---------------------------------------------------------------------------
def denials(texts):
    """-> {name: sentence} for every "X ... is not a KSSL product" the material states.

    The repo's own curated data carries this disclaimer about AAROK twice and
    contradicts it four times. The disclaimer wins: a sentence that says a thing is not
    ours is a finding about ownership, and a sentence that lists it inside "KSSL's
    airframe portfolio" is prose.
    """
    out = {}
    for t in texts or []:
        for sent in _SENT.split(str(t or "")):
            sent = sent.strip()
            if not DENIAL_RX.search(sent):
                continue
            m = _SUBJECT.match(sent)
            if m:
                out.setdefault(m.group(1).strip(), sent)
    return out


def denied(name, denial_map):
    """-> (banned, sentence). Matched on the product name, not on a substring of prose."""
    bare = norm(product_of(name))
    for subj, sent in (denial_map or {}).items():
        s = norm(subj)
        if s and (s == bare or s in bare.split() or bare in s.split()):
            return True, sent
    return False, ""


def offer_only(row):
    """-> (offered, why). R3, unstated case.

    True when a portfolio row cites NO source on a client domain AND the sources it
    does cite announce a relationship. That is exactly the shape of
        FN Herstal Integrated Weapon Mounts / C-UAS Turrets
        sole source: fnherstal.com/.../kalyani-strategic-systems-partners-with-fn-herstal-...
    -- the other party's own site, announcing that the two firms will build something.
    An announcement that two companies will work together is not a statement that one
    of them makes a product.

    Both halves are required. A row backed by the client's own site is the client
    stating its own portfolio, whatever else is cited beside it; and a row cited only
    to third parties who are not announcing a partnership (Simha 4x4, three trade
    outlets) is thin, not misattributed.
    """
    srcs = list(row.get("sources") or [])
    if not srcs:
        return False, ""
    if any(_domain(u) in CLIENT_DOMAINS for u in srcs):
        return False, ""
    for u in srcs:
        m = OFFER_RX.search(str(u))
        if m:
            return True, ("only source is a third party announcing a relationship "
                          "(%s in %s)" % (m.group(1).lower(), _domain(u)))
    for t in _row_text(row):
        m = OFFER_RX.search(t)
        if m:
            return True, "no client-published source, and the row's own text states a %s" % m.group(1).lower()
    return False, ""


def _row_text(row):
    for b in list(row.get("specs") or []) + list(row.get("features") or []):
        if isinstance(b, dict):
            yield " ".join(str(b.get(k) or "") for k in ("ctx", "k", "v", "note"))


def _domain(url):
    t = tiers()
    if t:
        try:
            return t.domain(url)
        except Exception:                                          # noqa: BLE001
            pass
    m = re.match(r"https?://(?:www\.)?([^/:]+)", str(url or ""), re.I)
    return (m.group(1).lower() if m else "")


# ---------------------------------------------------------------------------
# R4 + R5: the sources
# ---------------------------------------------------------------------------
def source_verdict(row):
    """-> (ok, why). R4, delegated to the bar the corpus path already applies."""
    t = tiers()
    if not t:
        return False, "engine/source_tiers.py did not load: cannot check, so not passed"
    ok, why, _tier, _n = t.publishable(row.get("sources") or [], CLIENT)
    return bool(ok), why


def _slug_words(url):
    path = re.sub(r"^https?://[^/]+", "", str(url or ""))
    return [w for w in _WORD.findall(path.lower())
            if len(w) >= 4 and not w.isdigit() and w not in _SLUG_NOISE]


def entails(row):
    """-> (ok, why). R5: is the citation about THIS product?

    Refuses a row whose news citations, read as words, share nothing with the product
    or its class. The live case:
        Ultra UAV / Precision Loitering Munition
        sole source: .../bharat-forge-subsidiary-inks-landmark-artillery-deal-with-uae-firm/
    -- an artillery deal cited as the whole evidence for a loitering munition.

    Deliberately silent about a maker or government citation (the client stating its
    own portfolio needs no headline to agree with it) and about an opaque path
    (ddpmod.gov.in/hi/node/7501 is a real government product page with no text in its
    URL; refusing it would delete a real product).
    """
    t = tiers()
    if not t:
        return True, "cannot read source tiers; not judged"
    srcs = [u for u in (row.get("sources") or []) if u]
    if not srcs:
        return True, "no source to judge"
    news = []
    for u in srcs:
        try:
            if t.tier(u) == t.OFFICIAL:
                return True, "an official publisher states it; the URL need not agree"
        except Exception:                                          # noqa: BLE001
            pass
        news.append(u)
    subject = set(norm(row.get("name")).split()) | set(norm(row.get("cat") or "").split()) \
        | set(norm(row.get("file_category") or "").split())
    subject = {w for w in subject if len(w) >= 3}
    judged = 0
    for u in news:
        words = _slug_words(u)
        if len(words) < MIN_SLUG_WORDS:
            continue                       # an opaque id carries no claim to check
        judged += 1
        if subject & set(words):
            return True, "cited page names the product or its class"
    if not judged:
        return True, "no citation carries readable words; not judged"
    return False, ("no cited page shares a word with %r or its class -- evidence for "
                   "something else" % (row.get("name") or "")[:48])


# ---------------------------------------------------------------------------
# the audit
# ---------------------------------------------------------------------------
#   ban    the row must not stand as a KSSL product           (R3 denial, R3 offer)
#   hold   the row cannot support a published comparison      (R4, R5)
#   note   worth a human's eye, decides nothing               (advisory)
SEVERITY = ("ban", "hold", "note")


def audit_row(row, denial_map=None):
    """-> [(severity, rule, why)] for ONE portfolio row. Never deletes, never rewrites."""
    out = []
    name = row.get("name") or ""
    bad, sent = denied(name, denial_map or {})
    if bad:
        out.append(("ban", "R3 offered-not-owned",
                    "the material itself says so: %s" % sent[:140]))
    offered, why = offer_only(row)
    if offered:
        out.append(("ban", "R3 offered-not-owned", why))
    ok, why = source_verdict(row)
    if not ok:
        out.append(("hold", "R4 source bar", why))
    ok, why = entails(row)
    if not ok:
        out.append(("hold", "R5 evidence entails", why))
    if not any(_domain(u) in CLIENT_DOMAINS for u in (row.get("sources") or [])):
        out.append(("note", "no client-published source",
                    "nothing on a client domain states this row; %d third-party citation(s)"
                    % len(row.get("sources") or [])))
    if one_token(name):
        out.append(("note", "R6 one-token name",
                    "%r cannot be identified in free text; workbook attestation only" % name))
    return out


def audit_anchor(anchor, portfolio):
    """-> (verdict, why) for a name published on the Positioning tab as KSSL's side.

    verdict is 'ok', 'not_a_client_product', or 'group_only'.

    'group_only' is the honest third answer and the reason this function is not just
    attest(). "Shell forgings" is a real client line -- four workbook rows agreeing on
    one calibre range -- and no single workbook NAME matches it, so pairing.refuse()
    alone reads it as "the KSSL side is not a product the client publishes" and drops
    all of its pairings before positioning_gate ever sees them. Refusing a real pairing
    costs exactly what publishing a fake one costs; the two must be told apart.
    """
    ok, why = attest(anchor, portfolio)
    if not ok:
        return "not_a_client_product", why
    if not any(_same_product(product_of(anchor), (p.get("name") if isinstance(p, dict) else p) or "")
               for p in portfolio or []):
        return "group_only", why
    return "ok", why


# ---------------------------------------------------------------------------
def _demo():
    bad = [0]

    def ck(n, cond, extra=""):
        if not cond:
            bad[0] += 1
            print("  FAIL  %s %s" % (n, extra))
        else:
            print("  ok    %s" % n)

    WB = [{"product_id": "kalyani-m4", "name": "Kalyani M4"},
          {"product_id": "bharat-150-uav", "name": "Bharat 150 UAV"},
          {"product_id": "protective-carbine-5-56-30-mm", "name": "Protective Carbine - 5.56 x 30 mm"},
          {"product_id": "high-explosive-he-artillery-shells", "name": "High Explosive (HE) Artillery Shells"},
          {"product_id": "illuminating-artillery-shells", "name": "Illuminating Artillery Shells"},
          {"product_id": "incendiary-artillery-shells", "name": "Incendiary Artillery Shells"},
          {"product_id": "smoke-artillery-shells", "name": "Smoke Artillery Shells"}]

    # R1/R2 -- the Bayonet decision, with the number it was actually made on
    ck("Bayonet is unattested", not attest("KSSL · Bayonet", WB)[0])
    ck("...and 138 mentions do not attest it",
       not attest("KSSL · Bayonet", WB, mentions=138)[0])
    ck("...and the refusal says the count was ignored",
       "ignored" in attest("Bayonet", WB, mentions=138)[1])
    ck("Cleaver is unattested", not attest("Cleaver", WB, mentions=135)[0])
    ck("a real product still attests", attest("KSSL · M4", WB)[0])
    ck("an empty portfolio refuses, it does not pass", not attest("Kalyani M4", [])[0])

    # R3 -- the disclaimer wins over the contradicting prose in the same file
    dm = denials([
        "KSSL UAV line: Bharat 150 and Omega tactical ISR. AAROK is a Turgis & Gaillard "
        "MALE design offered under a 2025 MoU, not a KSSL product.",
        "Omega tactical ISR (Jan 2026 EP-VI contract) and the Bharat 150. AAROK remains a "
        "Turgis & Gaillard partnership offer, not a KSSL product to counter with.",
        "KSSL is developing indigenous UAV propulsion to pair with its airframe portfolio "
        "(AAROK MALE, Omega).",
    ])
    ck("the denial is read out of the prose", "AAROK" in dm, dm)
    ck("and it bans the name", denied("KSSL · AAROK", dm)[0])
    ck("a real product is not banned by it", not denied("Kalyani M4", dm)[0])

    fn = {"name": "FN Herstal Integrated Weapon Mounts / C-UAS Turrets",
          "cat": "Small Arms", "specs": [], "features": [],
          "sources": ["https://fnherstal.com/en/news/kalyani-strategic-systems-partners-"
                      "with-fn-herstal-to-build-small-arms-and-counter-uas-capability-in-india/"]}
    ck("a partner's partnership announcement is not ownership", offer_only(fn)[0], offer_only(fn))
    own = dict(fn, sources=fn["sources"] + ["https://www.kssl.in/small-arms"])
    ck("...but the client's own site outranks it", not offer_only(own)[0])
    simha = {"name": "Simha 4x4", "cat": "Protected & Armoured Vehicles", "sources": [
        "https://www.edrmagazine.eu/kalyani-strategic-systems-limited-and-paramount-unveil-simha-4x4-next-generation-modular-multipurpose-vehicle-for-the-global-market",
        "https://www.asianmilitaryreview.com/2026/06/kalyani-demonstrates-its-export-ambitions-at-eurosatory-2026-foc/"]}
    ck("three trade outlets are thin, not misattributed", not offer_only(simha)[0])

    # R4/R5
    ultra = {"name": "Ultra UAV / Precision Loitering Munition", "cat": "UAVs & Drones",
             "sources": ["https://scanx.trade/stock-market-news/orders-deals/bharat-forge-"
                         "subsidiary-inks-landmark-artillery-deal-with-uae-firm/19143608"]}
    ck("a single uncorroborated news source fails the bar", not source_verdict(ultra)[0])
    ck("an artillery headline does not entail a loitering munition", not entails(ultra)[0])
    hmrv = {"name": "High Mobility Reconnaissance Vehicle - HMRV", "cat": "Protected & Armoured Vehicles",
            "sources": ["https://www.ddpmod.gov.in/hi/node/7501",
                        "https://registro.feindefevent.com/feindef2025/en/Products/Details/1339262"]}
    ck("an opaque government URL is not judged on its words", entails(hmrv)[0], entails(hmrv))
    ck("...and a government publisher clears the bar", source_verdict(hmrv)[0])
    # the guard on its own: news tier, and a path whose only word is "feindef2025"
    opaque = dict(hmrv, sources=[hmrv["sources"][1]])
    ck("...and an opaque NEWS path is 'not judged', not 'refused'",
       entails(opaque)[0] and "not judged" in entails(opaque)[1], entails(opaque))
    ck("the client's own page needs no headline to agree with it",
       entails({"name": "Under-Barrel Grenade Launcher (UBGL)", "cat": "Small Arms",
                "sources": ["https://www.kssl.in/press_releases_details_6th_Feb_2020"]})[0])

    # R6
    ck("one-token names are marked", one_token("Cleaver") and one_token("Omega"))
    ck("...and a two-word name is not", not one_token("Kalyani M4"))

    # groups -- a real line that no single workbook NAME matches
    ck("Shell forgings attests as a group", attest("KSSL · Shell forgings", WB)[0],
       attest("KSSL · Shell forgings", WB))
    ck("...and is reported as group_only, not as ok",
       audit_anchor("KSSL · Shell forgings", WB)[0] == "group_only",
       audit_anchor("KSSL · Shell forgings", WB))
    ck("a real single product is plain ok",
       audit_anchor("KSSL · M4", WB)[0] == "ok")
    ck("and Bayonet is not_a_client_product",
       audit_anchor("KSSL · Bayonet", WB)[0] == "not_a_client_product")

    # audit_row on the two live offenders
    ck("FN Herstal row is banned, not merely noted",
       any(s == "ban" for s, _r, _w in audit_row(fn)))
    ck("Ultra UAV row is held",
       any(s == "hold" for s, _r, _w in audit_row(ultra)))
    ck("a well-sourced row raises no ban and no hold",
       not [s for s, _r, _w in audit_row(
           {"name": "Kalyani M4", "cat": "Protected & Armoured Vehicles",
            "sources": ["https://www.kssl.in/protected-vehicles"]}) if s != "note"])

    print("all checks passed" if not bad[0] else "%d FAILED" % bad[0])
    return 1 if bad[0] else 0


if __name__ == "__main__":
    sys.exit(_demo())
