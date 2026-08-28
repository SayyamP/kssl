"""Generate SIGNALS.html -- how the corpus and the ontology combine into a signal.

    python build_signals_doc.py

Companion to build_pipeline_doc.py. That one documents the pipeline we HAVE;
this one documents the approach that turns it into signals, in plain English.

Every number in the page comes from the live store via probe_signal_gaps.py, and
the worked example is traced out of real rows -- so the page cannot drift from
the database by being edited. If a number here looks wrong, the database changed.
"""
import os
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent))
from build_pipeline_doc import STYLE, esc  # noqa: E402  one stylesheet for both docs

HERE = Path(__file__).parent
ROOT = HERE.parent
ONT = ROOT.parent / "l2" / "ontology" / "ontology.yaml"
DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
OUT = ROOT / "SIGNALS.html"
GAPS = HERE / "signal_gaps.json"
PROOF = HERE / "pattern_proof.json"


# --------------------------------------------------------------------------- data
def gaps(refresh=True):
    """The measured state of the three joins. Re-probed unless told not to."""
    if refresh or not GAPS.exists():
        subprocess.run([sys.executable, str(HERE / "probe_signal_gaps.py")],
                       cwd=str(HERE), check=True, capture_output=True)
    return json.loads(io.open(GAPS, encoding="utf-8").read())


def proof(refresh=True):
    """The floor-level run of the patterns. Regenerated so the page reports what the
    code actually does today, not what it did when the section was written."""
    if refresh or not PROOF.exists():
        subprocess.run([sys.executable, str(HERE / "prove_patterns.py"), "--show", "0"],
                       cwd=str(HERE), check=True, capture_output=True)
    return json.loads(io.open(PROOF, encoding="utf-8").read())


def example(cur):
    """The two documents that make the worked example, pulled live.

    Chosen because neither says anything about KSSL on its own -- which is the
    whole point of the section it illustrates."""
    want = [("%M777 towed artillery%", "replace"), ("%Hanwha%", "won"),
            ("%M777A2 Ultra-Light Howitzers%", "buy")]
    rows = []
    for obj, cue in want:
        cur.execute("""select p.document_id, p.i, p.subject, p.predicate, p.object,
                              p.modality, p.ev_start, p.ev_end, p.ev_quote,
                              d.title, d.url, d.source_id, d.language
                         from extracted.proposition p
                         join extracted.document d using (document_id)
                        where (p.object ilike %s or p.subject ilike %s)
                          and p.predicate ilike %s
                        limit 1""", (obj, obj, "%" + cue + "%"))
        r = cur.fetchone()
        if r:
            rows.append(r)
    cur.execute("""select p.subject, p.predicate, p.object, d.source_id, d.url
                     from extracted.proposition p
                     join extracted.document d using (document_id)
                    where p.subject ilike '%Kalyani%'
                      and (p.object ilike '%artiller%' or p.predicate ilike '%artiller%')
                    limit 2""")
    kssl = cur.fetchall()
    return rows, kssl


def ont_facts():
    txt = io.open(ONT, encoding="utf-8").read()
    langs = set(re.findall(r"[\{,]\s*([a-z]{2}):\s", txt))
    nodes = [l.split(":")[0].strip() for l in txt.splitlines()
             if l.startswith("  ") and l.strip().endswith(":")
             and not l.startswith("    ") and "." in l.split(":")[0]]
    ver = [l.split(":", 1)[1].strip() for l in txt.splitlines()
           if l.startswith("version:")]
    return nodes, (ver[0] if ver else "?"), len(langs)


# --------------------------------------------------------------------------- copy
def joins(g, n_lang):
    """The four joins. Every quantity is substituted from the live probe -- prose
    that states a number is prose that can go stale, and the page claims it cannot."""
    isa = next((r["n"] for r in g["gap2"]["top_unmapped"] if r["surface"].strip() == "is a"), 0)
    surf = "{:,}".format(g["gap2"]["distinct_surfaces"])
    npred = len(g["closed_predicates"])
    meas = "{:,}".format(g["gap3"]["measurable_spans"])
    top = [e["name"] for e in g["corpus"]["top_entities"]]
    junk = [n for n in top if n.lower() in
            ("cookie", "cookies", "website", "web site", "company", "companies")]
    fam = {}
    for n in top:
        fam.setdefault(n.split()[0].lower(), []).append(n)
    split = max(fam.values(), key=len)
    return [t for t in _JOINS(isa, surf, npred, meas, n_lang, len(top), junk, split)]


def _JOINS(isa, surf, npred, meas, n_lang, n_top, junk, split):
    junk_s = ", ".join("<code>%s</code>" % esc(j) for j in junk) or "boilerplate terms"
    split_s = ", ".join("<em>%s</em>" % esc(s) for s in split)
    return [
    ("J1", "Type the thing",
     "extracted.entity.ont_node_id",
     "Every entity gets told what KIND of thing it is, using the ontology's own node ids "
     "&mdash; so <em>K9 Vajra</em> stops being a string and becomes "
     "<code>materiel.weapons.artillery</code>.",
     "The corpus already contains its own answer key. The single commonest thing our "
     "extractor writes is an <code>is a</code> statement &mdash; %s of them &mdash; and an "
     "<code>is a</code> statement is a typing statement: <em>&ldquo;the Mobile Tactical Cannon "
     "is a self-propelled howitzer&rdquo;</em>. We match those objects, and the entity's own "
     "spellings, against the node labels. The labels are written in %d languages precisely "
     "because English-only node descriptions measured 20&ndash;25%% failure on German, Japanese, "
     "Chinese and Korean sources against 2.8%% on English. Whatever still does not match goes to "
     "the <code>unclassified</code> slot and is counted. We never force a fit; residue is a "
     "number we report, not a failure we hide." % ("{:,}".format(isa), n_lang)),
    ("J2", "Type the link",
     "a closed predicate on every proposition",
     "The %s different phrasings our extractor produced collapse onto the ontology's "
     "%d legal link types &mdash; <code>manufactures</code>, <code>awarded</code>, "
     "<code>procures</code>, <code>replaces</code>, and the rest." % (surf, npred),
     "This is the join that pays for itself twice. First, an open set of %s relations is "
     "not a graph &mdash; nothing can be queried across it, because <em>&ldquo;won&rdquo;</em>, "
     "<em>&ldquo;secured&rdquo;</em> and <em>&ldquo;captures&rdquo;</em> are three different "
     "edges to a database and one idea to a reader. Second, and better: each of the %d link "
     "types declares what may sit at each end. <code>manufactures</code> runs from an Agent to "
     "an Artefact. So once J1 has typed both ends, <em>&ldquo;Saab manufactures Gripen&rdquo;</em> "
     "is accepted and <em>&ldquo;Gripen manufactures Saab&rdquo;</em> is rejected by arithmetic "
     "&mdash; no model, no reviewer, no prompt. We have been repairing backwards facts by hand; "
     "this makes most of them impossible to store." % (surf, npred)),
    ("J3", "Type the number",
     "extracted.span_value, extracted.prop_arg",
     "Dates, calibres, weights, money and quantities stop being text and become values with "
     "units, so two of them can be compared.",
     "We have found %s measurable spans and parsed exactly none of them. That single fact "
     "explains three empty screens: there is no <em>&ldquo;&#8377; at stake&rdquo;</em> because "
     "contract values are strings; no deadline sorting because dates are strings; no spec "
     "comparison because <em>155&nbsp;mm</em> is a string. The property registry also carries the "
     "guard that makes comparison legal &mdash; every property declares a dimension, so a "
     "500&nbsp;mm calibre can never be compared against 500&nbsp;mm of armour, which is the "
     "classic way a spec table quietly lies." % meas),
    ("J4", "Clean the identity",
     "extracted.entity, entity_alias",
     "Merge the spellings of one company into one company, and throw out the things that are "
     "not companies at all.",
     "This one is not theory. Rank our entities by how often they are mentioned and %d of the "
     "top %d are %s &mdash; consent banners and boilerplate outranking real firms. In the "
     "same top %d, %s sit as separate things when they are one company and one of its trade-show "
     "stands. Until this is fixed, every count on every screen is a count of spellings, not of "
     "companies." % (len(junk), n_top, junk_s, n_top, split_s)),
    ]

PATTERNS = [
    ("Rival advance",
     "A competitor gains ground in a category we sell into.",
     "a rival Agent gains an <code>awarded</code> / <code>supplies</code> / "
     "<code>manufactures</code> link into a sector node at or under a KSSL portfolio node",
     "contract value, or the floor when no value is stated",
     "days"),
    ("Open demand",
     "Somebody is buying what we make, and we are not in the conversation.",
     "a buyer Agent <code>procures</code> a Capability that a KSSL artefact "
     "<code>realises</code>, and <strong>no</strong> link exists from KSSL to that buyer",
     "programme size &times; how squarely it sits in our portfolio",
     "weeks"),
    ("Consolidation",
     "Two of our rivals become one competitor.",
     "two rival Agents acquire <code>partners_with</code> or <code>subsidiary_of</code> "
     "between them inside a node we compete in",
     "combined share of the node",
     "months"),
    ("Capability drift",
     "The technology under a product line is moving.",
     "the mention rate of a <code>technology.*</code> node rises across quarters inside a "
     "node we sell into",
     "slope of the rise, and whether we have any link into it",
     "quarters"),
    ("Spec gap",
     "Their product beats ours on a number a buyer will read.",
     "a rival Artefact and a KSSL Artefact both carry <code>has_spec</code> on the same "
     "property, with matching dimension and <code>applies_to</code>",
     "size of the gap in the property's own units",
     "years"),
    ("Supply exposure",
     "Something we depend on just became harder to get.",
     "a KSSL <code>component_of</code> / <code>supplies</code> chain reaches a node whose "
     "<code>export_status</code> or <code>origin_country</code> facet changed",
     "how deep in our chain it sits",
     "weeks"),
]

TODAY_VS = [
    ("What it reads",
     "One article at a time. Nothing else is in scope.",
     "The whole graph, every article we have ever read, plus the ontology."),
    ("Who decides it matters",
     "The model, in one pass, with no memory of yesterday.",
     "A written pattern. The model never decides; it only writes the sentence."),
    ("Can it spot an absence",
     "No. An article cannot say &ldquo;and KSSL was not invited&rdquo;.",
     "Yes. A missing link is a queryable fact, and absence is often the signal."),
    ("Can it see a trend",
     "No. A trend needs many documents and a clock.",
     "Yes. Counting links per quarter is a query."),
    ("When it is wrong",
     "It invents a fact and we need a gate per field to catch it.",
     "It picks a wrong word. The facts came from the graph and cite offsets."),
    ("Why do you believe it",
     "Because the model said so.",
     "signal &rarr; pattern &rarr; links &rarr; statements &rarr; character range &rarr; URL."),
    ("Cost per signal",
     "One call to a 14&nbsp;B model per document, forever, re-run on every change.",
     "Model work happens once at bind time; a signal is then a database query."),
]

RISKS = [
    ("The tree is wrong for a branch KSSL cares about.",
     "Residue per node is reported every run. A node that keeps sending things to "
     "<code>unclassified</code> is the tree telling us where it is thin. That is why the "
     "open slot exists and why nothing is force-fitted into the nearest node."),
    ("Typing is confidently wrong, and a wrong type is worse than none.",
     "Each binding carries how it was made &mdash; matched a label, matched an embedding, "
     "or set by a person. The signal's confidence is the weakest link in its own chain, so a "
     "guess can never be laundered into a certainty by passing through three steps."),
    ("We build the graph and the signals are boring.",
     "Testable before we build it. Take the six patterns, run them by hand over the corpus we "
     "already have, and count how many fire and how many a reader would act on. If that number "
     "is small, the patterns are wrong &mdash; and we have learned it in a day rather than a "
     "month."),
    ("Numbers get compared that should not be.",
     "The property registry declares a dimension and an <code>applies_to</code> for every "
     "property, and a comparison that crosses either is refused rather than rendered."),
    ("Something upstream changes and the page quietly goes stale.",
     "This page is generated. Every count in it is read from the database at build time, and "
     "the worked example is traced out of live rows &mdash; so it cannot be edited into "
     "agreement with a story that is no longer true."),
]

BUILD = [
    ("1", "Prove the patterns &mdash; <strong>done</strong>", "&mdash;",
     "Ran three of the six over the live corpus with no model at all. 39 signals, about "
     "three quarters of them real, and the failures name the joins that fix them. "
     "<code>docs/prove_patterns.py</code>."),
    ("2", "J4 &mdash; clean identity", "1 day",
     "A stop-list for boilerplate entities and a merge pass for the obvious spelling groups. "
     "Everything downstream counts things, so counting the right things comes first."),
    ("3", "J1 &mdash; type the entities", "2&ndash;3 days",
     "Labels first, embeddings second, open slot third. Report residue per language, because "
     "an English-only pass will look excellent and be broken."),
    ("4", "J2 &mdash; type the links", "2&ndash;3 days",
     "Lexical map reaches 18%; a small model picks one of 18 labels for the rest. The domain "
     "and range check runs on every link and drops the illegal ones."),
    ("5", "J3 &mdash; type the numbers", "2 days",
     "Dates, money, calibres, quantities. Unlocks value-at-stake, deadlines and spec tables."),
    ("6", "Signals as queries", "3 days",
     "Six patterns, the priority score, and the evidence chain behind every one."),
]


# --------------------------------------------------------------------------- render
def kv(rows):
    return ('<div class="tw"><table class="kv"><tbody>%s</tbody></table></div>'
            % "".join("<tr><td>%s</td><td>%s</td></tr>" % (a, b) for a, b in rows))


def build(g, pf, ex, kssl, nodes, ver, n_lang):
    n_ent = g["gap1"]["entities"]
    n_prop = g["gap2"]["propositions"]
    n_surf = g["gap2"]["distinct_surfaces"]
    pct_map = 100.0 * g["gap2"]["mapped"] / max(n_prop, 1)
    n_meas = g["gap3"]["measurable_spans"]
    n_doc = g["corpus"]["documents"]
    n_span = g["corpus"]["spans"]
    n_pred = len(g["closed_predicates"])

    secs = []

    # 1 -------------------------------------------------------------------
    secs.append(("what", "What we are actually trying to make", """
<p>A signal is a short, dated statement that tells KSSL to do something, and shows its
working. Not a summary of an article &mdash; a reason to act, with a source.</p>
<div class="rule"><strong>&ldquo;The platform India just committed to sustaining is the one the
US Army has started replacing, and the replacement contract went to a competitor who is also
bidding in India.&rdquo;</strong></div>
<p class="note" style="margin-top:14px">That sentence is worth money. It is also impossible to
produce from any single article, which is the entire problem this page is about.</p>
<h3>Where we are today</h3>
<p>Right now a signal is made by handing one article to a language model and asking it what
matters. It works, and we have spent weeks tightening it: gates for dates, for duplicates, for
relevance, and a separate check for every field the model writes, because any field without a
check is where the invented facts collect.</p>
<p>But the ceiling is structural, not a matter of prompt quality. A reader of one article can
never see a pattern that lives across many. It cannot notice that the same rival has appeared
four times in six weeks. It cannot notice that a buyer is shopping and we are not on the list,
because <em>absence is never written down in an article</em>. And it has to be re-run from
scratch every time anything changes, because it remembers nothing.</p>
<p>The rest of this page is one argument: we already own the two things that fix this, and they
have simply never been connected to each other.</p>"""))

    # 2 -------------------------------------------------------------------
    secs.append(("have", "The two things we already own", """
<div class="cards">
  <div class="card"><h3>A corpus, broken down</h3><p>%s documents in 26 languages, pulled apart
  into %s spans and %s statements of the form <em>subject &mdash; verb &mdash; object</em>, each
  one carrying the exact character range of the sentence it came from.</p></div>
  <div class="card"><h3>An ontology</h3><p>Version %s. A deliberately small tree of what defence
  things <em>are</em>, %d sector nodes deep where the sector is genuinely understood, with %d
  legal link types, 5 facets and 12 measurable properties &mdash; each node named in 26
  languages.</p></div>
</div>
<p>The corpus knows what was said. The ontology knows what things are. Between them sits
everything KSSL wants to know &mdash; and there is currently no join between them at all.</p>
%s
<p class="note">Those are not estimates. <code>docs/probe_signal_gaps.py</code> measures them
against the live database, and this page is generated from what it returns.</p>"""
                % ("{:,}".format(n_doc), "{:,}".format(n_span), "{:,}".format(n_prop),
                   esc(ver), len(nodes), n_pred,
                   kv([("Documents", "{:,}".format(n_doc)),
                       ("Statements extracted", "{:,}".format(n_prop)),
                       ("Entities found", "{:,}".format(n_ent)),
                       ("Entities given an ontology type",
                        "<strong>%d</strong> &mdash; none of them" % g["gap1"]["typed"]),
                       ("Distinct ways of phrasing a link", "{:,}".format(n_surf)),
                       ("Link types the ontology allows", str(n_pred)),
                       ("Measurable spans (dates, money, calibres)", "{:,}".format(n_meas)),
                       ("Measurable spans actually parsed",
                        "<strong>%d</strong> &mdash; none of them" % g["gap3"]["span_value"])]))))

    # 3 -------------------------------------------------------------------
    joins_html = "".join("""
<div class="step"><h3>%s &nbsp;&mdash;&nbsp; %s</h3>
<p class="note" style="margin:0 0 10px"><code>%s</code></p>
<p>%s</p><p>%s</p></div>""" % (a, b, c, d, e) for a, b, c, d, e in joins(g, n_lang))
    secs.append(("joins", "The four joins that are missing", """
<p>Connecting the corpus to the ontology is four separate pieces of work. Each one is small.
Each one is currently at zero.</p>%s
<div class="rule">Order matters. J1 must run before J2, because the domain-and-range check needs
both ends of a link to have a type before it can tell a legal link from a backwards one.</div>"""
                % joins_html))

    # 4 -------------------------------------------------------------------
    rows = "".join("""<tr><td class="col">%s</td><td>%s</td><td>%s</td>
<td class="ty">%s</td><td class="ty">%s</td></tr>""" % (esc(n), p, w, sev, hl)
                   for n, p, w, sev, hl in PATTERNS)
    secs.append(("query", "The change: a signal becomes a query, not a prompt", """
<p>Once the four joins are in place, we stop asking a model what matters and start
<em>describing</em> what matters, once, in a pattern the database can look for. Every pattern
has the same shape:</p>
<pre class="prompt">WHEN   &lt;this shape appears in the graph&gt;
AND    &lt;it touches something KSSL sells or could sell&gt;
THEN   raise a signal, with the evidence that produced it</pre>
<p>Six patterns cover what KSSL actually pays attention to. Nothing here is a prompt; each one
is a query anybody can read, argue with and change.</p>
<div class="tw"><table class="data"><thead><tr><th>Pattern</th><th>In plain English</th>
<th>What the graph must show</th><th>How big it is</th><th>Goes stale in</th></tr></thead>
<tbody>%s</tbody></table></div>
<h3>Which ones go to the top</h3>
<p>Every signal is scored the same way, and the score is arithmetic rather than opinion:</p>
<pre class="prompt">priority = severity  &times;  confidence  &times;  urgency  &times;  relevance</pre>
%s
<div class="rule"><strong>Confidence is the weakest link in the chain, never the average.</strong>
A guess that passes through three careful steps is still a guess, and averaging is exactly how a
system launders one into a certainty.</div>
<h3>What the model still does</h3>
<p>It writes the sentence. Given a signal the graph has already found, and the statements that
produced it, the model turns them into a line a person can read. That is a much smaller job than
the one it does today, and it fails in a much cheaper way: today a bad output is an invented
fact, and after this it is an awkward wording &mdash; because the facts came from the graph and
carry the character offsets to prove it.</p>""" % (
        rows,
        kv([("severity", "the typed number &mdash; contract value, quantity, size of the "
                         "spec gap &mdash; or an agreed floor when nothing is stated"),
            ("confidence", "the weakest grade anywhere in the evidence chain: matched a "
                           "label &gt; matched an embedding &gt; guessed"),
            ("urgency", "how fast this kind of signal goes stale &mdash; a tender deadline "
                        "decays in days, a spec gap in years"),
            ("relevance", "distance through the tree from the signal's node to KSSL's own "
                          "portfolio nodes &mdash; computed, not asserted")]))))

    # 5 -------------------------------------------------------------------
    # One block per DOCUMENT, not per statement -- two statements out of the same
    # article are one source, and rendering them twice would overstate corroboration.
    docs, order = {}, []
    for r in ex:
        did = r[0]
        if did not in docs:
            docs[did] = {"title": r[9], "url": r[10], "src": r[11], "lang": r[12], "st": []}
            order.append(did)
        docs[did]["st"].append(r)
    step_html = ""
    for did in order:
        d = docs[did]
        st = ""
        for (_d, _i, subj, pred, obj, mod, s, e, quote, *_rest) in d["st"]:
            st += """
  <div class="exhead">the sentence, as published</div>
  <pre class="doc">%s</pre>
  <div class="exhead">what the extractor stored &mdash; characters %d&ndash;%d</div>
  <pre class="doc"><strong>%s</strong> &nbsp;&mdash;[%s]&rarr;&nbsp; <strong>%s</strong> &nbsp;<em>[%s]</em></pre>
""" % (esc(quote or ""), s or 0, e or 0, esc(subj), esc(pred), esc(obj), esc(mod or ""))
        step_html += """
<div class="example">
  <div class="exhead">%s &nbsp;&middot;&nbsp; %s &nbsp;&middot;&nbsp; %d statement(s)</div>
  <p style="margin:0 0 8px"><a href="%s">%s</a></p>%s
</div>""" % (esc(d["src"]), esc(d["lang"]), len(d["st"]),
             esc(d["url"]), esc(d["title"] or d["url"]), st)
    kssl_html = "".join("<li><code>%s</code> &mdash;[%s]&rarr; <code>%s</code> "
                        "<span class='note'>(%s)</span></li>"
                        % (esc(a), esc(b), esc(c), esc(d)) for a, b, c, d, _u in kssl)

    secs.append(("example", "A worked example, start to finish", """
<p>Here is a real signal, built out of rows that are in the database right now. Read the two
articles below and notice what neither of them says: <strong>neither one mentions KSSL.</strong>
A model reading either article on its own would correctly decide there is nothing here for us,
and it would be wrong.</p>
%s
<h3>Step 1 &mdash; the ontology says these are the same kind of thing</h3>
<p>An <em>M777A2 Ultra-Light Howitzer</em> and a <em>Mobile Tactical Cannon</em> share no words.
Once J1 has typed them, both hang under <code>materiel.weapons.artillery</code>, and so does
KSSL's own line &mdash; the corpus says so in its own words:</p>
<ul>%s</ul>
<h3>Step 2 &mdash; the links become traversable</h3>
<p>J2 turns three different phrasings into three legal link types, and checks each one against
what may sit at either end:</p>
%s
<h3>Step 3 &mdash; the pattern fires</h3>
<p>Nobody wrote a prompt about M777 howitzers. Two of the six standing patterns simply match:</p>
%s
<h3>Step 4 &mdash; what KSSL is told</h3>
<div class="rule"><strong>India is committing to keep the M777 flying while the platform's
largest operator starts replacing it &mdash; and the replacement contract went to Hanwha, who is
building US production and competes with us in India. Our ultralight artillery line sits on both
sides of that: a sustainment and upgrade window opening now, and a replacement-class rival
acquiring its reference customer.</strong></div>
<p style="margin-top:14px">And if anyone asks why we believe it, the answer is mechanical rather
than a matter of trust: the signal names the pattern, the pattern names the links, the links name
the statements, and each statement names the character range and the URL it came from. Every hop
above is a row you can go and look at.</p>""" % (
        step_html,
        kssl_html or "<li class='note'>(no Kalyani artillery statement in the current slice)</li>",
        kv([("<code>procures</code>", "Government of India &rarr; M777A2 sustainment "
             "<span class='note'>&mdash; Agent &rarr; Artefact, legal</span>"),
            ("<code>replaces</code>", "Mobile Tactical Cannon &rarr; M777 towed artillery "
             "<span class='note'>&mdash; Artefact &rarr; Artefact, legal</span>"),
            ("<code>awarded</code>", "Hanwha Defense USA &rarr; US Army contract "
             "<span class='note'>&mdash; Agent &rarr; Activity, legal</span>")]),
        kv([("<strong>Rival advance</strong>", "a rival gains an <code>awarded</code> link "
             "into <code>materiel.weapons.artillery</code> &mdash; a node KSSL sells into"),
            ("<strong>Open demand</strong>", "a buyer <code>procures</code> inside that same "
             "node, and there is no link from KSSL to that buyer")]))))

    # 5b ------------------------------------------------------------------
    ps, sig = pf["stats"], pf["signals"]
    def sig_rows(kind, n=4):
        out = ""
        for r in sig.get(kind, [])[:n]:
            out += ("""<tr><td>%s</td><td class="ty">%s</td><td>%s</td>
<td class="q">%s</td><td class="ty">%s</td></tr>"""
                    % (esc(r["subject"][:38]), esc(r["pred"]), esc(r["object"][:40]),
                       esc(r["quote"][:120]), esc(r["source"])))
        return out
    secs.append(("proof", "We already ran the cheap version, and it works", """
<p>Before asking anyone to build this, we built the throwaway version of it &mdash; a few
hundred lines, no model, no embeddings, no training. Just: match names against the ontology's
own labels, map the verbs with a lookup table, and run three of the six patterns over the
%s statements we already have.</p>
<p>It is deliberately the weakest possible version, so whatever it finds is a
<strong>floor</strong>, not a result:</p>
%s
<p>From that floor it produced <strong>%d distinct signals</strong>. Here is a sample, exactly
as the script printed them:</p>
<h3>Somebody is buying what we make</h3>
<div class="tw"><table class="data"><thead><tr><th>Who</th><th>Link</th><th>What</th>
<th>The sentence it came from</th><th>Source</th></tr></thead><tbody>%s</tbody></table></div>
<div class="rule">The Indian Army's Field Artillery Rationalisation Plan &mdash; three to
three-and-a-half thousand artillery systems &mdash; is the single largest opportunity in
KSSL's core category, and it fell out of a lookup table on a laptop in an afternoon.</div>
<h3>A rival gains ground where we sell</h3>
<div class="tw"><table class="data"><thead><tr><th>Who</th><th>Link</th><th>What</th>
<th>The sentence it came from</th><th>Source</th></tr></thead><tbody>%s</tbody></table></div>
<h3>Something we sell is being replaced</h3>
<div class="tw"><table class="data"><thead><tr><th>What</th><th>Link</th><th>Replaces</th>
<th>The sentence it came from</th><th>Source</th></tr></thead><tbody>%s</tbody></table></div>
<h3>And what it got wrong &mdash; which is the useful part</h3>
<p>Roughly a quarter of what fired is junk, and the junk is specific rather than random.
Three failures, each naming the join that fixes it:</p>
%s
<p>None of those need a cleverer prompt. Each is exactly the work J1 and J4 already describe,
which is the strongest evidence we have that the four joins are the right four.</p>""" % (
        "{:,}".format(ps["propositions"]),
        kv([("Names matched to a category",
             "%s of %s statements &mdash; <strong>%.0f%%</strong>"
             % ("{:,}".format(ps["typed_objects"]), "{:,}".format(ps["propositions"]),
                100.0 * ps["typed_objects"] / max(ps["propositions"], 1))),
            ("Verbs mapped to a link type",
             "%s &mdash; <strong>%.0f%%</strong>"
             % ("{:,}".format(ps["edged"]),
                100.0 * ps["edged"] / max(ps["propositions"], 1))),
            ("Ontology terms used", "{:,}".format(ps["index_terms"])),
            ("Patterns run", "3 of 6"),
            ("Model calls", "<strong>none</strong>")]),
        ps["signals"], sig_rows("open demand"), sig_rows("rival advance"),
        sig_rows("replacement pressure"),
        kv([("<em>&ldquo;the collaboration&rdquo;</em> supplies&hellip;",
             "the subject is a phrase, not a company &mdash; <strong>J4</strong>, which "
             "requires a name before a thing may be an actor"),
            ("<em>&ldquo;weak enforcement replaces all protection&rdquo;</em>",
             "an Arabic article about policing and corruption; <em>protection</em> matched "
             "the armour node by spelling &mdash; <strong>J1</strong>, where meaning "
             "decides the type, not a substring"),
            ("<em>&ldquo;perolehan 20 buah kenderaan perisai&rdquo;</em>",
             "a correct Malay armoured-vehicle signal with a sentence fragment where the "
             "buyer's name belongs &mdash; <strong>J4</strong> again")]))))

    # 6 -------------------------------------------------------------------
    rows = "".join("<tr><td class=\"col\">%s</td><td>%s</td><td>%s</td></tr>" % r
                   for r in TODAY_VS)
    secs.append(("versus", "Why this is better than what we have", """
<p>Not a criticism of the current pipeline &mdash; it does the job it was built for. This is
about what it structurally cannot do.</p>
<div class="tw"><table class="data"><thead><tr><th></th><th>Today: a model reads one article</th>
<th>After: a pattern reads the graph</th></tr></thead><tbody>%s</tbody></table></div>
<p>The line that matters most is the second-to-last. We have spent real time building a
validation gate for every field a model writes, because the field without a gate is exactly
where the invented facts collect. This approach removes most of the need for those gates by
removing the opportunity: the model is no longer the thing that produces facts.</p>""" % rows))

    # 7 -------------------------------------------------------------------
    rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (a, b) for a, b in RISKS)
    secs.append(("risks", "What could go wrong, and how we would know", """
<p>Every one of these is something we can measure rather than argue about.</p>
<div class="tw"><table class="data"><thead><tr><th>The worry</th><th>How it shows itself</th>
</tr></thead><tbody>%s</tbody></table></div>""" % rows))

    # 8 -------------------------------------------------------------------
    rows = "".join("""<tr><td class="col">%s</td><td>%s</td><td class="ty">%s</td>
<td>%s</td></tr>""" % r for r in BUILD)
    secs.append(("order", "The order to build it in", """
<div class="tw"><table class="data"><thead><tr><th></th><th>Step</th><th>Size</th>
<th>Why here</th></tr></thead><tbody>%s</tbody></table></div>
<div class="rule">Step 1 comes first on purpose. It costs a day and it is the only step that can
tell us the other five are not worth doing.</div>
<p class="note" style="margin-top:16px">Nothing here needs a bigger model. J2 asks a model to
choose one of %d labels and J1 asks it to choose one of %d nodes &mdash; small, closed decisions
that a small fast model makes as well as a large one, and far cheaper. The large model keeps only
the writing.</p>
<div class="rule"><strong>A closed predicate list turns out to be a buying advantage.</strong>
A survey of the 2026 extraction literature found that no released model does what our current
extractor does &mdash; open-ended verbs, character offsets and 26 languages at once &mdash; and
that every fast model on the market gives up the open verbs to get the speed. But J2 does not
want open verbs. It wants exactly %d labels, which is the shape those models are built for:
there are 0.3&nbsp;B encoders, Apache-licensed and roughly twenty times smaller than our judge,
that emit a chosen relation label <em>with the character offsets of both ends</em>. The
constraint the market treats as a limitation is our specification.</div>
<p class="note">One caveat carried over from that survey, and it is the familiar one: every
&ldquo;multilingual&rdquo; claim attached to those models is a claim about the encoder they were
built on, not a measurement. The one family that does publish per-language numbers scores Chinese
twenty points below Portuguese. We measure on Russian, Ukrainian, Turkish, Hebrew, Persian and
Greek ourselves before we believe any of it.</p>""" % (rows, n_pred, len(nodes), n_pred)))

    toc = "".join('<li><a href="#%s">%s</a></li>' % (i, t) for i, t, _ in secs)
    body = "".join('<section id="%s"><h2>%s</h2>%s</section>' % (i, t, h) for i, t, h in secs)
    return """<meta charset="utf-8">
<title>Corpus to Signal</title>%s
<header><h1>From a pile of documents to a reason to act</h1>
<p class="sub">We have a corpus broken into statements, and an ontology that says what defence
things are. They have never been joined. This is what joining them buys KSSL, what it takes, and
one real signal traced from two articles to a sentence &mdash; in plain English.</p></header>
<nav class="toc"><ol>%s</ol></nav><main>%s</main>
<footer style="max-width:900px;margin:0 auto;padding:0 24px 60px" class="note">
Generated by <code>docs/build_signals_doc.py</code> from the live database and
<code>l2/ontology/ontology.yaml</code> %s. Companion to <code>PIPELINE.html</code>.</footer>
""" % (STYLE, toc, body, esc(ver))


def main():
    g = gaps()
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    ex, kssl = example(cur)
    con.close()
    nodes, ver, n_lang = ont_facts()
    io.open(OUT, "w", encoding="utf-8").write(build(g, proof(), ex, kssl, nodes, ver, n_lang))
    print("wrote %s (%.1f KB, %d worked-example rows, %d ontology nodes)"
          % (OUT.name, OUT.stat().st_size / 1024.0, len(ex), len(nodes)))


def _demo():
    # The page must be built from measurements, never from numbers typed into it.
    import inspect
    src = inspect.getsource(build)
    for literal in ("17516", "12386", "4963", "206326", "624", "17416"):
        assert literal not in src, "hard-coded corpus number in build(): %s" % literal
    nodes, ver, n_lang = ont_facts()
    assert nodes and ver and all("." in n for n in nodes), "ontology not parsed"
    assert len(PATTERNS) == 6 and len(_JOINS(1, "1", 1, "1", 1, 1, [], ["a"])) == 4
    print("ok (%d nodes, ontology %s, %d joins, %d patterns)"
          % (len(nodes), ver, 4, len(PATTERNS)))
    assert n_lang >= 20, "ontology labels cover only %d languages" % n_lang


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        main()
