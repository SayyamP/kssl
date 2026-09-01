"""Which domains may be cited as evidence on the dashboard.

One place, so a rule cannot hold in the crawler and quietly not hold in the
serving layer. `is_blocked(url)` is the gate; everything that stores a source
URL should ask it first.

WIKIPEDIA IS BLOCKED, and this is a policy decision rather than a quality
measurement: a client-facing competitive dossier cannot cite an
anyone-can-edit encyclopaedia as the provenance for a specification. It had
been on the fetch allowlist (`EXTRA_OK` in pipeline/fetch_for_products.py)
because it carries convenient spec tables, and it reached serving: 43 of the
126 matchups the UI showed cited it, 29 of them cited NOTHING ELSE, and 49 of
the 92 spec sets carried a Wikipedia link on individual values.

The mirrors are listed too. Blocking `wikipedia.org` alone leaves
`wikiwand.com` and `dbpedia.org` -- the same text, one hop away -- which is how
a blocklist usually fails.

A value whose ONLY source is blocked is not merely uncited: it is unsourced,
and it must be dropped rather than shown with the citation quietly removed.
Keeping the number while dropping the link is the worse of the two failures --
it presents an unsourced claim as a sourced one.
"""
from urllib.parse import urlsplit

__all__ = ["is_blocked", "BLOCKED_DOMAINS", "filter_sources", "sole_source_blocked"]

BLOCKED_DOMAINS = frozenset((
    # Wikipedia and its mirrors / derivatives.
    "wikipedia.org", "wikimedia.org", "wikidata.org", "wiktionary.org",
    "wikiwand.com", "dbpedia.org", "everipedia.org", "wikizero.com",
    "alchetron.com", "wiki2.org", "en-academic.com", "wikishia.net",
))


def _host(url):
    try:
        h = urlsplit(url or "").netloc.lower()
    except Exception:                                                # noqa: BLE001
        return ""
    if "@" in h:                       # strip any userinfo
        h = h.rsplit("@", 1)[-1]
    return h.split(":", 1)[0].lstrip(".")


def is_blocked(url):
    """True when this URL may not be cited as evidence.

    Matched on the registrable domain and any subdomain, so en.wikipedia.org,
    simple.wikipedia.org and m.wikipedia.org are all covered by one entry.
    """
    h = _host(url)
    if not h:
        return False
    h = h[4:] if h.startswith("www.") else h
    return any(h == d or h.endswith("." + d) for d in BLOCKED_DOMAINS)


def filter_sources(urls):
    """Drop blocked URLs, preserving order and removing duplicates."""
    out, seen = [], set()
    for u in urls or ():
        if not u or is_blocked(u):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def sole_source_blocked(urls):
    """True when the ONLY sources given are blocked ones.

    The caller should then drop the claim, not just the citation.
    """
    urls = [u for u in (urls or ()) if u]
    return bool(urls) and not filter_sources(urls)
