import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2, serving_fill as sf

dsn = os.environ.get("KSSL_DSN", sf.DSN)
con = psycopg2.connect(dsn); cur = con.cursor()
cats = sf.kssl_cats()
patterns, comp_patterns = sf.load_terms()
cutoff, cur_year = sf.recent_cutoff()

# a handful of not-yet-carded, not-yet-seen docs WITH propositions
cur.execute("""SELECT d.document_id, d.title, d.source_id, d.language, d.url
                 FROM extracted.document d
                WHERE NOT EXISTS (SELECT 1 FROM serving.signal_card c WHERE c.id='pl_'||d.document_id)
                  AND NOT EXISTS (SELECT 1 FROM serving.signal_seen s WHERE s.document_id=d.document_id)
                  AND EXISTS (SELECT 1 FROM extracted.proposition p WHERE p.document_id=d.document_id)
                ORDER BY d.document_id LIMIT %s""", (int(os.environ.get("N","4")),))
docs = cur.fetchall()
print("diagnosing %d docs\n" % len(docs), flush=True)

for did, title, source, lang, url in docs:
    print("="*70); print("DOC", did, "|", (title or "")[:70])
    cur.execute("SELECT subject,predicate,object,modality,ev_quote FROM extracted.proposition WHERE document_id=%s ORDER BY i", (did,))
    props = cur.fetchall()
    print("  props:", len(props))
    if sf.is_listing(url): print("  -> GATE: listing url"); continue
    ymd = sf.article_date(cur, did)
    if ymd is None: print("  -> GATE: undated"); continue
    if not sf.is_recent_ym(ymd[:2], cutoff, cur_year): print("  -> GATE: stale", ymd[:2]); continue
    if not sf.is_relevant(patterns, title, props): print("  -> GATE: offtopic (not KSSL-relevant)"); continue
    props = props[:12]
    lines = "\n".join('- %s %s %s [%s] -- "%s"' % (s,p,o,m,(q or "")[:180]) for s,p,o,m,q in props)
    prompt = sf.PROMPT % (", ".join(cats), title or did, source, lang, lines)
    try:
        raw = sf.ask(prompt)
    except Exception as e:
        print("  -> LLM ERROR:", str(e)[:160]); continue
    print("  RAW MODEL OUTPUT:", (raw or "").strip()[:400].replace("\n"," "))
    card = sf.parse_card(raw, cats)
    if card is None:
        # figure out WHY parse_card refused
        r = (raw or "").strip()
        if not r or r.upper().startswith("NONE"): reason="model said NONE (no signal)"
        else:
            import re, json
            m = re.search(r"\{.*\}", r, re.S)
            if not m: reason="no JSON object in reply"
            else:
                try:
                    d=json.loads(m.group(0)); reason="JSON parsed but a field failed validation (pillar/category/company/filler)"
                    reason += " | pillar=%r category=%r company=%r" % (d.get("pillar"), d.get("category"), d.get("company"))
                except Exception: reason="malformed JSON"
        print("  -> VERDICT: REFUSED —", reason)
    else:
        print("  -> VERDICT: CARD! pillar=%s cat=%s co=%s" % (card["pillar"], card["category"], card["company"]))
con.close()
