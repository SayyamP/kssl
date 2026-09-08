"""Is this URL the company's OWN website, or just a page that mentions it?

    python company_sites.py --demo

THE FAULT THIS REPLACES. enrich_serving picked a competitor's `site` like this:

    tok = first token of the name that is >= 4 characters
    for each document about the company:
        if tok in host: site = host; break

One token, tested as a SUBSTRING of the host. That is a language-shaped rule applied to
domain names, and it published four news publishers as companies' official websites:

    Bharat Dynamics             'bharat'  -> bharatshakti.in        (a news portal)
    General Dynamics            'general' -> amgeneral.com          (A DIFFERENT COMPANY)
    Israel Aerospace Industries 'israel'  -> israeldefense.co.il    (a news portal)
    SSS Defence                 'defence' -> livefistdefence.com    (a news blog)

The General Dynamics one is the worst of the four: AM General is a real, separate
manufacturer, so the profile did not merely link somewhere unhelpful, it attributed one
company's website to another. This is the same failure class the corpus keeps producing
-- a short substring matching inside a longer word -- and the fix is the same shape:
compare whole names, not fragments of them.

THE RULE. The domain and the company name must be PREFIXES OF ONE ANOTHER once both are
folded to bare letters. That keeps every genuine site in the roster:

    saab.com            saab            <- saab                          equal
    mbda-systems.com    mbdasystems     <- mbda                          domain extends
    patriagroup.com     patriagroup     <- patria                        domain extends
    rafael.co.il        rafael          <- rafaeladvanceddefensesystems  name extends
    brahmos.com         brahmos         <- brahmosaerospace              name extends

and refuses all four publishers, because neither string is a prefix of the other:

    bharatshakti    vs bharatdynamics
    amgeneral       vs generaldynamics
    israeldefense   vs israelaerospaceindustries
    livefistdefence vs sssdefence

THE AMPERSAND. aliases.fold rewrites '&' to 'and', which is right for company identity
and wrong here: "Larsen & Toubro" folds to 'larsenandtoubro' and its real site is
larsentoubro.com, so a single folding refused a correct value. Both readings are tried.
An ampersand has broken an identity rule in this repo before; it gets a test here.
"""
import re
import sys

# Verified official sites the RULE CANNOT REACH, because the company's domain shares no
# prefix with its name. Each was fetched and confirmed to be the company's own site --
# a domain is only listed here after something on it said whose it is.
#
#   gd.com          "General Dynamics | Home"                          (fetched 2026-09-06)
#   iai.co.il       resolves inside Israel Aerospace Industries' own domain  (2026-09-06)
#   bdl-india.in    "Official Website of Bharat Dynamics Limited (BDL)
#                    under the Ministry of Defence, Government of India"     (2026-09-06)
#   uvisionuav.com  UVision's own domain; the site is behind Cloudflare and refuses us,
#                   so it is carried on the domain name rather than on page content --
#                   which is why it is HERE, stated, and not silently derived.
#   sssdefence.com  "SSS DEFENCE | Indigenous Defence Platforms"        (fetched 2026-09-06)
#                   The RULE would accept this domain; it is listed so the profile links
#                   to it whether or not the corpus happens to hold a page from it.
OFFICIAL = {
    "sss-defence": "https://www.sssdefence.com/",
    "general-dynamics": "https://www.gd.com/",
    "israel-aerospace-industries": "https://www.iai.co.il/",
    "bharat-dynamics": "https://bdl-india.in/",
    "uvision-air": "https://uvisionuav.com/",
}

_SUFFIX = {"ltd", "limited", "inc", "plc", "llc", "gmbh", "ag", "sa", "as", "asa",
           "oyj", "ab", "nv", "bv", "spa", "srl", "pvt", "private", "corp",
           "corporation", "company", "co", "group", "holdings", "industries"}


def domain_label(url):
    """https://www.mbda-systems.com/x -> 'mbdasystems'. '' when there is no host."""
    m = re.match(r"https?://([^/]+)", str(url or "").strip())
    if not m:
        return ""
    host = m.group(1).lower().split(":")[0]
    parts = [p for p in host.split(".") if p and p != "www"]
    # Drop the public suffix. Two-letter and three-letter tails only, so a real name
    # like 'knds' or 'saab' is never mistaken for one.
    while len(parts) > 1 and len(parts[-1]) <= 3:
        parts.pop()
    return re.sub(r"[^a-z0-9]", "", parts[-1]) if parts else ""


def _foldings(name):
    """The company name as bare letters, with '&' read BOTH ways -- see the docstring."""
    s = re.sub(r"&amp;", "&", str(name or "").strip(), flags=re.I)
    out = []
    for amp in (" and ", " "):
        t = s.replace("&", amp).lower()
        t = re.sub(r"[^a-z0-9]+", " ", t).strip()
        toks = [w for w in t.split() if w]
        while toks and toks[-1] in _SUFFIX:
            toks.pop()
        if toks:
            out.append("".join(toks))
    return out


def is_own_site(name, url):
    """True when `url`'s domain and `name` are prefixes of one another."""
    lab = domain_label(url)
    if not lab:
        return False
    for fn in _foldings(name):
        if fn and (fn.startswith(lab) or lab.startswith(fn)):
            return True
    return False


def pick_site(cid, name, urls):
    """The company's own site from the URLs of its own documents, or None.

    Order: a verified official site first (it is a stated fact and outranks anything
    derived), then the first document URL whose domain passes the rule. Returns None
    rather than a best guess -- a profile with no website link is honest; a profile
    linking to a different company is not.
    """
    if cid in OFFICIAL:
        return OFFICIAL[cid]
    for u in urls or []:
        if is_own_site(name, u):
            m = re.match(r"https?://([^/]+)", str(u).strip())
            if m:
                return "https://" + m.group(1)
    return None


def _demo():
    ok = True

    def ck(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  %-64s %s" % (label, "ok" if good else "FAIL got=%r want=%r" % (got, want)))

    print("the four publishers that were served as companies' own sites:")
    ck("Bharat Dynamics is not bharatshakti.in",
       is_own_site("Bharat Dynamics", "https://bharatshakti.in"), False)
    ck("General Dynamics is not AM General",
       is_own_site("General Dynamics", "https://www.amgeneral.com"), False)
    ck("Israel Aerospace Industries is not israeldefense.co.il",
       is_own_site("Israel Aerospace Industries", "https://www.israeldefense.co.il"), False)
    ck("SSS Defence is not livefistdefence.com",
       is_own_site("SSS Defence", "https://www.livefistdefence.com"), False)

    print("real sites in the roster still pass:")
    for nm, u in [("Saab", "https://www.saab.com"),
                  ("MBDA", "https://www.mbda-systems.com"),
                  ("Patria", "https://www.patriagroup.com"),
                  ("Rafael Advanced Defense Systems", "https://www.rafael.co.il"),
                  ("BrahMos Aerospace", "https://brahmos.com"),
                  ("KNDS", "https://knds.com"),
                  ("Otokar", "https://www.otokar.com.tr"),
                  ("Adani Defence", "https://www.adanidefence.com/")]:
        ck("%s -> %s" % (nm, u), is_own_site(nm, u), True)

    print("the ampersand, which has broken an identity rule here before:")
    ck("Larsen & Toubro keeps larsentoubro.com",
       is_own_site("Larsen & Toubro", "https://www.larsentoubro.com"), True)
    ck("...and the HTML-escaped spelling too",
       is_own_site("Larsen &amp; Toubro", "https://www.larsentoubro.com"), True)

    print("a legal suffix in the name is not part of the domain:")
    ck("Roshel Inc. -> roshel.com", is_own_site("Roshel Inc.", "https://roshel.com"), True)

    print("picking:")
    ck("a verified site outranks the documents",
       pick_site("general-dynamics", "General Dynamics",
                 ["https://www.amgeneral.com/x"]), "https://www.gd.com/")
    # Deliberately a company with NO verified override, so this asserts the RULE and
    # not the override table. (It used to name sss-defence, and started passing for the
    # wrong reason the moment that company gained a verified site.)
    ck("nothing matching means NO site, not a guess",
       pick_site("kalashnikov", "Kalashnikov",
                 ["https://www.livefistdefence.com/a", "https://idrw.org/b"]), None)
    ck("a verified override is still returned when nothing else matches",
       pick_site("sss-defence", "SSS Defence", ["https://www.livefistdefence.com/a"]),
       "https://www.sssdefence.com/")
    ck("an own-domain document is used when there is no override",
       pick_site("saab", "Saab", ["https://news.example.com/x", "https://www.saab.com/y"]),
       "https://www.saab.com")

    print("\n%s" % ("all checks passed" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_demo() if "--demo" in sys.argv else _demo())
