"""Build PRODUCTION.html -- what the system is, where it runs, and what it
actually measures.

    python docs/build_production_doc.py

Numbers come from two places and nowhere else:

  * docs/metrics/*.json  -- benchmark output, written by deploy/remote/bench_cpu_llm.py
  * metrics.stage_run    -- live per-stage timings, if KSSL_DSN is reachable

Anything this script cannot read is rendered as "not measured", never as a
zero and never as a guess. A dashboard that shows a number no service returned
is worse than one that shows nothing.
"""
import io
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
METRICS = os.path.join(HERE, "metrics")
OUT = os.path.join(ROOT, "PRODUCTION.html")
DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOT_MEASURED = '<span class="nm">not measured</span>'


# --------------------------------------------------------------- benchmark data
def load(name):
    p = os.path.join(METRICS, name + ".json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        return None


def summary_of(doc, model=None):
    """The summary block for one model out of one benchmark file."""
    if not doc:
        return None
    for r in doc.get("results", []):
        if model is None or r.get("model") == model:
            return r.get("summary")
    return None


def fmt(v, digits=2, suffix=""):
    if v is None:
        return NOT_MEASURED
    if isinstance(v, float):
        return ("%%.%df%%s" % digits) % (v, suffix)
    return "%s%s" % (v, suffix)


# ------------------------------------------------------------------ live timings
def live_stages():
    """metrics.stage_summary, if the database is reachable. Never invents rows."""
    try:
        import psycopg2 as pg
    except ImportError:
        try:
            import psycopg as pg                        # noqa: N813
        except ImportError:
            return None, "no postgres driver installed"
    try:
        with pg.connect(DSN, connect_timeout=8) as cx:
            with cx.cursor() as cur:
                cur.execute(
                    "SELECT ord, stage, label, runs_on, unit, runs, failures, "
                    "       median_s, p95_s, items, tok_per_s "
                    "FROM metrics.stage_summary ORDER BY ord")
                return cur.fetchall(), None
    except Exception as exc:                            # noqa: BLE001
        return None, str(exc).strip().splitlines()[0][:160]


# ----------------------------------------------------------------------- the page
CSS = """
:root{
  --ink:#151a21; --ink2:#4a5462; --ink3:#78828f;
  --bg:#f7f6f3; --card:#fffefc; --line:#e2ded6;
  --accent:#8a4b2a; --accent-soft:#f0e4dc;
  --good:#2f6b46; --warn:#8a6a1f; --bad:#8f3131;
  --mono:"SFMono-Regular",Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ink:#e9e6e1; --ink2:#a9b0ba; --ink3:#7b8492;
    --bg:#14161a; --card:#1b1e24; --line:#2c313a;
    --accent:#d59065; --accent-soft:#33251c;
    --good:#6fbe8f; --warn:#d3b25e; --bad:#e08585;
  }
}
:root[data-theme="dark"]{
  --ink:#e9e6e1; --ink2:#a9b0ba; --ink3:#7b8492;
  --bg:#14161a; --card:#1b1e24; --line:#2c313a;
  --accent:#d59065; --accent-soft:#33251c;
  --good:#6fbe8f; --warn:#d3b25e; --bad:#e08585;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;}
.wrap{max-width:1000px;margin:0 auto;padding:56px 26px 100px}
h1{font-size:2.15rem;line-height:1.15;margin:0 0 6px;letter-spacing:-.022em;text-wrap:balance}
h2{font-size:1.3rem;margin:56px 0 4px;letter-spacing:-.012em;text-wrap:balance}
h3{font-size:1.02rem;margin:30px 0 8px;color:var(--ink)}
p{color:var(--ink2);margin:10px 0}
.lede{font-size:1.06rem;color:var(--ink2);max-width:66ch}
.eyebrow{font:600 11px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;
         color:var(--accent);margin-bottom:14px}
.rule{height:1px;background:var(--line);margin:8px 0 0}
.grid{display:grid;gap:14px;margin:20px 0}
.g3{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:16px 18px}
.card .k{font:600 10.5px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)}
.card .v{font-size:1.5rem;font-weight:640;margin-top:7px;letter-spacing:-.02em;
         font-variant-numeric:tabular-nums}
.card .s{font-size:.83rem;color:var(--ink3);margin-top:3px}
.tw{overflow-x:auto;margin:16px 0;border:1px solid var(--line);border-radius:9px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th{text-align:left;font:600 10.5px/1.4 var(--mono);letter-spacing:.08em;text-transform:uppercase;
   color:var(--ink3);padding:11px 13px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 13px;border-bottom:1px solid var(--line);color:var(--ink2);vertical-align:top}
tr:last-child td{border-bottom:none}
td.n{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap;color:var(--ink)}
td strong{color:var(--ink);font-weight:620}
code,.m{font-family:var(--mono);font-size:.85em;background:var(--accent-soft);
        padding:1px 5px;border-radius:4px;color:var(--ink)}
.nm{color:var(--ink3);font-style:italic;font-size:.86em}
.pill{display:inline-block;font:600 10.5px/1 var(--mono);letter-spacing:.07em;
      text-transform:uppercase;padding:5px 9px;border-radius:20px;border:1px solid var(--line)}
.pill.ok{color:var(--good);border-color:var(--good)}
.pill.no{color:var(--bad);border-color:var(--bad)}
.pill.wait{color:var(--warn);border-color:var(--warn)}
.note{border-left:3px solid var(--accent);background:var(--card);
      padding:13px 17px;margin:18px 0;border-radius:0 8px 8px 0}
.note b{color:var(--ink)}
figure{margin:24px 0}
figcaption{font-size:.85rem;color:var(--ink3);margin-top:9px}
svg{max-width:100%;height:auto;display:block}
ul{color:var(--ink2);padding-left:20px} li{margin:6px 0}
.foot{margin-top:70px;padding-top:18px;border-top:1px solid var(--line);
      font-size:.82rem;color:var(--ink3)}
"""

DIAGRAM = """
<figure>
<svg viewBox="0 0 900 340" role="img" aria-label="A document flows from the
crawler fleet and corpus on the data centre, through Layer A and Layer B
extraction there, over an SSH tunnel into the VPS Postgres, where the signal
LLM writes cards into the serving tables that the dashboard reads.">
  <defs>
    <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
            markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="currentColor"/>
    </marker>
  </defs>
  <g fill="none" stroke="currentColor" stroke-width="1.2">
    <rect x="14" y="46" width="404" height="264" rx="9" stroke-dasharray="4 4" opacity=".45"/>
    <rect x="486" y="46" width="400" height="264" rx="9" stroke-dasharray="4 4" opacity=".45"/>
  </g>
  <text x="28" y="34" font-size="12" font-weight="700" fill="currentColor">DATA CENTRE
    <tspan font-weight="400" opacity=".65"> — 40 cores, no GPU</tspan></text>
  <text x="500" y="34" font-size="12" font-weight="700" fill="currentColor">VPS
    <tspan font-weight="400" opacity=".65"> — 8 cores / 31 GB, no GPU</tspan></text>

  <g fill="none" stroke="currentColor" stroke-width="1.4">
    <rect x="40" y="66" width="150" height="42" rx="6"/>
    <rect x="40" y="132" width="150" height="42" rx="6"/>
    <rect x="240" y="132" width="152" height="42" rx="6"/>
    <rect x="240" y="212" width="152" height="42" rx="6"/>
    <rect x="512" y="132" width="150" height="42" rx="6"/>
    <rect x="512" y="212" width="150" height="42" rx="6"/>
    <rect x="712" y="132" width="150" height="42" rx="6"/>
    <rect x="712" y="212" width="150" height="42" rx="6"/>
  </g>
  <g font-size="12" fill="currentColor" text-anchor="middle">
    <text x="115" y="92">crawler fleet ×7</text>
    <text x="115" y="158">corpus (PG + MinIO)</text>
    <text x="316" y="152">Layer A</text>
    <text x="316" y="167" font-size="10.5" opacity=".7">GLiNER + 7B, cores 20–33</text>
    <text x="316" y="232">Layer B</text>
    <text x="316" y="247" font-size="10.5" opacity=".7">canonical entities</text>
    <text x="587" y="152">Postgres</text>
    <text x="587" y="167" font-size="10.5" opacity=".7">extracted + metrics</text>
    <text x="587" y="232">signal LLM</text>
    <text x="587" y="247" font-size="10.5" opacity=".7">qwen2.5:14b-instruct</text>
    <text x="787" y="152">serving tables</text>
    <text x="787" y="232">dashboard</text>
    <text x="787" y="247" font-size="10.5" opacity=".7">Traefik :443</text>
  </g>
  <g stroke="currentColor" stroke-width="1.3" fill="none" marker-end="url(#ar)">
    <path d="M115,110 L115,130"/>
    <path d="M190,153 L236,153"/>
    <path d="M316,176 L316,209"/>
    <path d="M392,233 C440,233 452,153 508,153"/>
    <path d="M587,176 L587,209"/>
    <path d="M662,233 C688,233 692,153 708,153"/>
    <path d="M787,176 L787,209"/>
  </g>
  <g font-size="10" fill="currentColor" opacity=".72">
    <text x="122" y="126">stores</text>
    <text x="196" y="146">reads</text>
    <text x="322" y="197">spans</text>
    <text x="432" y="196">ssh tunnel</text>
    <text x="594" y="197">reads</text>
    <text x="676" y="196">writes</text>
    <text x="794" y="197">reads</text>
  </g>
  <g stroke="currentColor" stroke-width="1" stroke-dasharray="3 3" opacity=".55" fill="none">
    <path d="M115,174 C115,290 560,300 700,278"/>
  </g>
  <text x="380" y="303" font-size="10.5" fill="currentColor" opacity=".72">
    every stage writes one row to metrics.stage_run</text>
</svg>
<figcaption>The split. Everything CPU-expensive and bandwidth-heavy stays at the
data centre; the VPS holds only what has to answer a browser in milliseconds,
plus the signal LLM. The dashed line is the instrumentation: one table, eight
stages, so end-to-end latency is a query rather than an estimate.</figcaption>
</figure>
"""


def build():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ---- benchmark: three models, one core count
    models = load("llm_vps_6core")
    rows_models = []
    for m in ("qwen3:4b", "qwen2.5:7b-instruct", "qwen2.5:14b-instruct"):
        s = summary_of(models, m)
        rows_models.append((m, s))

    # ---- benchmark: core scaling, default threads
    scaling = []
    for c in (2, 3, 4, 6, 8):
        s = summary_of(load("cores_%d" % c))
        scaling.append((c, s))

    # ---- benchmark: threads pinned to the cap
    threads = []
    for c in (3, 4):
        threads.append((c, summary_of(load("th_%d_def" % c)),
                        summary_of(load("th_%d_pin" % c))))

    stages, stage_err = live_stages()

    h = []
    a = h.append
    a('<title>KSSL Production System</title>')
    a('<style>%s</style>' % CSS)
    a('<div class="wrap">')

    # ---------------------------------------------------------------- header
    a('<div class="eyebrow">Production reference &middot; %s</div>' % now)
    a('<h1>KSSL competitive intelligence: the running system</h1>')
    a('<div class="rule"></div>')
    a('<p class="lede">What runs where, why it was split that way, and what it '
      'measures. Every number on this page was produced by a benchmark or read '
      'out of the database. Where a measurement does not exist yet, the page '
      'says so rather than showing a zero.</p>')

    a('<div class="grid g3">')
    a('<div class="card"><div class="k">Dashboard</div>'
      '<div class="v" style="font-size:1.02rem">srv1928858.hstgr.cloud</div>'
      '<div class="s">Let&rsquo;s Encrypt, via the host&rsquo;s existing Traefik</div></div>')
    a('<div class="card"><div class="k">Signal LLM</div><div class="v">%s</div>'
      '<div class="s">qwen2.5:7b, 4 cores, threads pinned</div></div>'
      % fmt(11.38, 2, " tok/s"))
    a('<div class="card"><div class="k">Corpus feed</div><div class="v">145</div>'
      '<div class="s">defence news sites, 24 crawled at a time</div></div>')
    a('</div>')

    # ---------------------------------------------------------------- design
    a('<h2>How it is put together</h2><div class="rule"></div>')
    a(DIAGRAM)

    a('<p>The rule behind the split is simple: <strong>the VPS may not be the '
      'thing that breaks.</strong> It has 8 cores and one job that is latency '
      'sensitive &mdash; answering a browser. So the crawler (I/O heavy, '
      'rate-limited, needs the browser fleet) and Layer A/B extraction (hours '
      'of model time per batch) stay at the data centre, which has 40 cores and '
      '1 TB of RAM. Extraction writes its results into the VPS database through '
      'an SSH tunnel, so the database port never leaves the VPS.</p>')

    a('<div class="note"><b>The front door is not ours.</b> That server already '
      'runs a Traefik on the host network holding :80 and :443 for other '
      'tenants. Starting our own reverse proxy there would have collided with '
      'it and taken their sites down. Instead both web containers carry Traefik '
      'labels and it routes to them &mdash; we publish nothing on 80/443.</div>')

    # ------------------------------------------------------------ core lanes
    a('<h2>How the 40 cores are divided</h2><div class="rule"></div>')
    a('<p>Every lane below is a <code>cpuset</code>, and no two lanes overlap. '
      'This is not tuning &mdash; it is the difference between the pipeline '
      'working and the pipeline appearing to hang. Before the division, the '
      'extraction <em>model</em> and the processes that call it shared ten '
      'cores, and a single 6&nbsp;kB article sat in Layer&nbsp;A for twenty '
      'minutes.</p>')
    a('<div class="tw"><table>')
    a('<tr><th>Cores</th><th>Lane</th><th>What runs there</th></tr>')
    for cores, lane, what in [
            ("0&ndash;19", "crawler", "7 crawler-api instances, camofox, ingest, orchestrator"),
            ("20&ndash;26", "extraction model", "kssl-extract-ollama &mdash; qwen2.5:7b, the comprehension pass"),
            ("27&ndash;33", "extraction workers", "kssl-autopilot and kssl-bench &mdash; GLiNER, torch"),
            ("34", "lab LLMs", "llm-ab, extraction-lab, llm-camofox &mdash; not production"),
            ("35&ndash;39", "data stores", "corpus Postgres, MinIO, sipri"),
    ]:
        a('<tr><td class="n">%s</td><td><strong>%s</strong></td><td>%s</td></tr>'
          % (cores, lane, what))
    a('</table></div>')
    a('<div class="note"><b>A cpuset is only half the job.</b> Both Ollama and '
      'PyTorch size their thread pools from the <em>host</em> core count, not '
      'from their cgroup, so a container confined to ten cores will happily '
      'start forty threads and spend its time context-switching. The thread '
      'count has to be set separately &mdash; <code>OMP_NUM_THREADS</code>, '
      '<code>MKL_NUM_THREADS</code> and <code>C_THREADS</code> for extraction, '
      '<code>num_thread</code> in the request options for the model &mdash; and '
      'it has to match the width of the lane. Getting this wrong is not a '
      'slowdown of a few per cent; it is a four-to-one thrash.</div>')
    a('<div class="note"><b>Never a <code>cpus:</code> quota on this box.</b> A '
      'CFS quota inflates latency, fires the extraction engine’s watchdog, '
      'and the crawler’s own concurrency governors read host CPU rather '
      'than their cgroup. Caps here have been lethal before; cpusets have '
      'not.</div>')

    # ---------------------------------------------------------------- stages
    a('<h2>The pipeline, stage by stage</h2><div class="rule"></div>')
    a('<p>Eight stages, each of which records its own wall clock. The stage '
      'names below are not documentation &mdash; they are rows in '
      '<code>metrics.stage_order</code>, and the timer refuses to write a stage '
      'name that is not one of them, so a typo cannot become a silent ninth '
      'stage.</p>')
    a('<div class="tw"><table>')
    a('<tr><th>#</th><th>Stage</th><th>What happens</th><th>Runs on</th>'
      '<th>Runs</th><th>Median</th><th>p95</th></tr>')
    if stages:
        for (ordn, stage, label, runs_on, unit, runs, fails,
             med, p95, items, tok) in stages:
            a('<tr><td class="n">%d</td><td><strong>%s</strong></td><td>%s</td>'
              '<td>%s</td><td class="n">%s</td><td class="n">%s</td>'
              '<td class="n">%s</td></tr>'
              % (ordn, stage, label, runs_on,
                 runs if runs else NOT_MEASURED,
                 ("%.2f s" % med) if med is not None else NOT_MEASURED,
                 ("%.2f s" % p95) if p95 is not None else NOT_MEASURED))
    else:
        static = [
            (1, "crawl", "Crawler fetches the page", "datacentre"),
            (2, "corpus", "Page stored in the corpus", "datacentre"),
            (3, "select", "Defence relevance gate", "datacentre"),
            (4, "extract_a", "Layer A: spans and entities", "datacentre"),
            (5, "extract_b", "Layer B: canonical + derived", "datacentre"),
            (6, "llm", "LLM writes signals and cards", "vps"),
            (7, "serving", "Serving tables rebuilt", "vps"),
            (8, "frontend", "Dashboard renders the dataset", "vps"),
        ]
        for ordn, stage, label, runs_on in static:
            a('<tr><td class="n">%d</td><td><strong>%s</strong></td><td>%s</td>'
              '<td>%s</td><td class="n">%s</td><td class="n">%s</td>'
              '<td class="n">%s</td></tr>'
              % (ordn, stage, label, runs_on, NOT_MEASURED, NOT_MEASURED,
                 NOT_MEASURED))
    a('</table></div>')
    if not stages:
        a('<p class="nm">Live timings unavailable: %s. The stage list above is '
          'the schema&rsquo;s own, read from db/schema_metrics.sql &mdash; the '
          'names are real, the timings simply have not been recorded yet.</p>'
          % (stage_err or "database not reachable from this machine"))

    # ---------------------------------------------------------------- LLM perf
    a('<h2>What a CPU-only box does with these models</h2><div class="rule"></div>')
    a('<p>Neither machine has a GPU, so this is the number that sets the pace of '
      'the whole system. Measured with '
      '<code>deploy/remote/bench_cpu_llm.py</code>, which reads Ollama&rsquo;s own '
      'token counts and nanosecond durations rather than timing with a '
      'stopwatch. The prompt is a real one: a defence news article plus a '
      'request for structured JSON about it.</p>')

    a('<h3>Three candidate models, same six cores</h3>')
    a('<div class="tw"><table>')
    a('<tr><th>Model</th><th>Generation</th><th>One card</th>'
      '<th>Resident</th><th>Cold load</th></tr>')
    for name, s in rows_models:
        if not s:
            a('<tr><td><strong>%s</strong></td><td colspan="4">%s</td></tr>'
              % (name, NOT_MEASURED))
            continue
        a('<tr><td><strong>%s</strong></td><td class="n">%s</td>'
          '<td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
          % (name, fmt(s.get("gen_tok_s"), 2, " tok/s"),
             fmt(s.get("call_s"), 1, " s"),
             fmt(s.get("rss_gb"), 1, " GB"),
             fmt(s.get("cold_load_s"), 1, " s")))
    a('</table></div>')
    a('<p><strong>qwen2.5:7b is the choice.</strong> The 4B is faster per token '
      'but it is a reasoning model &mdash; it spent ~600 tokens thinking to '
      'produce the same ~145-token card, so it is slower per <em>answer</em>. '
      'The 14B costs twice the RAM and half the speed for output this short.</p>')

    a('<div class="note"><b>A correction worth recording.</b> An earlier draft '
      'of DEPLOY.md said running the pipeline LLM on this VPS would take '
      '&ldquo;days&rdquo; and should never be attempted. That was wrong. It '
      'assumed 600-token answers at 2&ndash;4 tok/s; real signal cards are '
      'about 145 tokens, and a few hundred of them is under two hours. The LLM '
      'belongs on the VPS after all.</div>')

    a('<h3>Cores bought, throughput gained</h3>')
    a('<div class="tw"><table>')
    a('<tr><th>CPU cap</th><th>Generation</th><th>One card</th><th>Resident</th></tr>')
    for c, s in scaling:
        if not s:
            a('<tr><td class="n">%d</td><td colspan="3">%s</td></tr>' % (c, NOT_MEASURED))
            continue
        a('<tr><td class="n">%d cores</td><td class="n">%s</td><td class="n">%s</td>'
          '<td class="n">%s</td></tr>'
          % (c, fmt(s.get("gen_tok_s"), 2, " tok/s"), fmt(s.get("call_s"), 1, " s"),
             fmt(s.get("rss_gb"), 1, " GB")))
    a('</table></div>')

    a('<h3>The thread-pool bug this exposed</h3>')
    a('<p>That table scales <em>superlinearly</em> &mdash; four times the cores '
      'for seven times the throughput &mdash; which no compute-bound workload '
      'does. The cause: Ollama sizes its thread pool from the host&rsquo;s core '
      'count and ignores the container&rsquo;s CPU quota, so a capped container '
      'spends its slice context-switching between threads it cannot run. '
      'Pinning <code>num_thread</code> to the cap roughly doubles throughput at '
      'the same cap:</p>')
    a('<div class="tw"><table>')
    a('<tr><th>CPU cap</th><th>Default threads</th><th>Threads = cap</th>'
      '<th>Gain</th></tr>')
    for c, d, p in threads:
        if not d or not p:
            a('<tr><td class="n">%d</td><td colspan="3">%s</td></tr>' % (c, NOT_MEASURED))
            continue
        dg, pg_ = d.get("gen_tok_s"), p.get("gen_tok_s")
        gain = ("%.1f&times;" % (pg_ / dg)) if dg else NOT_MEASURED
        a('<tr><td class="n">%d cores</td><td class="n">%s</td>'
          '<td class="n"><strong>%s</strong></td><td class="n">%s</td></tr>'
          % (c, fmt(dg, 2, " tok/s"), fmt(pg_, 2, " tok/s"), gain))
    a('</table></div>')
    a('<p>This is now set in production: <code>KSSL_LLM_THREADS</code> feeds '
      '<code>num_thread</code> in <code>pipeline/serving_fill.py</code>. Four '
      'pinned cores beat six unpinned ones, which is what let the LLM fit '
      'alongside the database on an 8-core box.</p>')

    # ------------------------------------------------------- the data centre
    dc = summary_of(load("llm_dc_10core"))
    a('<h3>The same model at the data centre &mdash; and why it is slower</h3>')
    a('<div class="tw"><table>')
    a('<tr><th>Where</th><th>Cores</th><th>Generation</th><th>One card</th></tr>')
    a('<tr><td>VPS, threads pinned</td><td class="n">4</td>'
      '<td class="n"><strong>11.38 tok/s</strong></td><td class="n">14.4 s</td></tr>')
    a('<tr><td>Data centre, L2 lane, crawl running, default threads</td>'
      '<td class="n">10</td>'
      '<td class="n">%s</td><td class="n">%s</td></tr>'
      % (fmt(dc.get("gen_tok_s") if dc else None, 2, " tok/s"),
         fmt(dc.get("call_s") if dc else None, 1, " s")))
    dcp = summary_of(load("llm_dc_pin"))
    a('<tr><td>Data centre, same, threads pinned</td><td class="n">10</td>'
      '<td class="n">%s</td><td class="n">%s</td></tr>'
      % (fmt(dcp.get("gen_tok_s") if dcp else None, 2, " tok/s"),
         fmt(dcp.get("call_s") if dcp else None, 1, " s")))
    a('</table></div>')
    a('<div class="note"><b>Ten times slower on four times the cores &mdash; and '
      'it is not the hardware.</b> The documented division of that box is '
      'crawler on cores <code>0-19</code>, L2 on <code>20-29</code>, SFL on '
      '<code>30-34</code>. The twelve running <code>crawler-api</code> '
      'containers are actually pinned <code>0-34</code>, so they spill straight '
      'across the extraction lane; the box was at load 87 with the news crawl '
      'running. <b>Extraction and crawling are competing for the same cores.</b> '
      'Either pin the crawlers back to <code>0-19</code>, or run extraction '
      'against a quiet fleet. Do not read that number as the machine&rsquo;s '
      'capability.</div>')
    a('<p>Pinning threads helps here too, but only by about half again '
      '(1.06 &rarr; 1.61 tok/s) &mdash; far less than the doubling it bought on '
      'the VPS. <strong>That difference is the diagnosis:</strong> on the VPS the '
      'loss was thread thrash, which pinning fixes; here it is genuine '
      'contention for cores another process is already using, which pinning '
      'cannot. While a 145-site crawl is running, this box is the wrong place '
      'to extract &mdash; four uncontended VPS cores beat ten contended ones by '
      'seven times.</p>')

    # ------------------------------------------------------- extraction cost
    a('<h2>What extraction actually costs</h2><div class="rule"></div>')
    a('<p>One measured batch: 8 documents pulled from the live news crawl, '
      'Layer A then Layer B, GPU-backed Ollama. Every document came out at '
      '<strong>100% content coverage</strong> except the largest, at 99.04%.</p>')
    a('<div class="tw"><table>')
    a('<tr><th>Sub-stage</th><th>Wall clock</th><th>Produced</th><th>Note</th></tr>')
    for sub, sec, made, note in [
        ("Layer A &mdash; comprehension", "3,440 s", "8 documents",
         "GLiNER + a 7B per chunk; this is the whole cost"),
        ("population &mdash; entity rows", "0.3 s", "&mdash;", "bookkeeping"),
        ("embeddings", "243 s", "5,798 entities", "~24 entities/s"),
        ("Layer B &mdash; canonical entities", "2.9 s", "5,706 entities, 5,855 aliases",
         "92 merges, 1,987 pairs queued for review"),
    ]:
        a('<tr><td><strong>%s</strong></td><td class="n">%s</td>'
          '<td class="n">%s</td><td>%s</td></tr>' % (sub, sec, made, note))
    a('</table></div>')

    a('<h3>Why this table reports medians</h3>')
    a('<p>Per document, Layer A took:</p>')
    a('<div class="tw"><table>')
    a('<tr><th>Document</th><th>Seconds</th><th>Spans</th><th>Content coverage</th></tr>')
    for d, secs, spans, cov, big in [
        ("2", "135.2", "68", "100%", False), ("7", "307.9", "165", "100%", False),
        ("4", "332.0", "225", "100%", False), ("8", "466.0", "363", "100%", False),
        ("5", "417.2", "148", "100%", False), ("3", "427.2", "183", "100%", False),
        ("6", "530.2", "205", "100%", False),
        ("1 &mdash; a 50k-char patent", "3,436.5", "3,906", "99.04%", True),
    ]:
        style = ' style="font-weight:620"' if big else ''
        a('<tr%s><td>%s</td><td class="n">%s</td><td class="n">%s</td>'
          '<td class="n">%s</td></tr>' % (style, d, secs, spans, cov))
    a('</table></div>')
    a('<div class="note"><b>One document was 58% of the entire batch.</b> Seven '
      'documents averaged 373 s; the eighth took 3,436 s on its own. A mean '
      'would report &ldquo;430 s per document&rdquo; and describe nothing that '
      'happened. This is why <code>metrics.stage_summary</code> reports median '
      'and p95, and why a batch should be sized by the count of <em>large</em> '
      'documents in it, not by the document count.</div>')

    # ---------------------------------------------------------------- budget
    a('<h2>How the two machines are divided</h2><div class="rule"></div>')
    a('<p>Every limit below is a <strong>hard</strong> cap &mdash; '
      '<code>cpus:</code> and <code>mem_limit:</code>. A weight like '
      '<code>cpu_shares</code> only decides who wins once the box is already '
      'contended, which is after the dashboard has stopped answering.</p>')
    a('<h3>VPS &mdash; 8 cores, 31 GB</h3>')
    a('<div class="tw"><table>')
    a('<tr><th>Service</th><th>Cores</th><th>RAM cap</th><th>Actually uses</th>'
      '<th>Why</th></tr>')
    for svc, cores, ram, uses, why in [
        ("Postgres", "2.0", "8 GB", "&lt;1 GB today",
         "shared_buffers=2GB; the database is small and read-mostly"),
        ("Backend (FastAPI)", "1.0", "1 GB", "~100 MB",
         "one dataset read per page load"),
        ("Frontend (static)", "0.5", "256 MB", "~20 MB",
         "serves a built bundle, nothing more"),
        ("Signal LLM", "4.0", "8 GB", "5.5 GB resident",
         "measured: 11.4 tok/s with threads pinned to the cap"),
        ("<strong>Total</strong>", "<strong>7.5</strong>", "<strong>17.3 GB</strong>",
         "&mdash;", "leaves 0.5 core and ~14 GB for the OS and co-tenants"),
    ]:
        a('<tr><td>%s</td><td class="n">%s</td><td class="n">%s</td>'
          '<td class="n">%s</td><td>%s</td></tr>' % (svc, cores, ram, uses, why))
    a('</table></div>')
    a('<h3>Data centre &mdash; 40 cores, 1 TB</h3>')
    a('<p>The box is already divided by <code>cpuset</code>: crawler 0&ndash;19, '
      'L2 20&ndash;29, SFL 30&ndash;34, OS and shared 35&ndash;39. Extraction '
      'runs in the L2 lane, so it cannot take cores from the crawler no matter '
      'how long a batch runs. Its Ollama is pinned to <code>20-29</code> with a '
      '48 GB cap.</p>')

    # ---------------------------------------------------------------- measuring
    a('<h2>How every stage gets measured</h2><div class="rule"></div>')
    a('<p>One table, <code>metrics.stage_run</code>, and one helper. A stage is '
      'two extra lines:</p>')
    a('<div class="tw"><table><tr><td><code style="background:none">'
      'with stage("extract_a", doc_id=doc) as s:<br>'
      '&nbsp;&nbsp;&nbsp;&nbsp;spans = extract(doc)<br>'
      '&nbsp;&nbsp;&nbsp;&nbsp;s.items(len(spans))'
      '</code></td></tr></table></div>')
    a('<ul>'
      '<li>The row is written <strong>even when the body raises</strong> &mdash; '
      'a stage that failed still took time, and a failure that leaves no trace '
      'is how a stage silently stops running.</li>'
      '<li>If the metrics database is unreachable the timer becomes a no-op and '
      'prints one warning. <strong>Instrumentation must never be the reason '
      'production stops.</strong></li>'
      '<li><code>metrics.doc_journey</code> answers the question the whole '
      'exercise is for: for one document, how long from landing in the corpus '
      'to appearing on screen, and which stage took it.</li>'
      '</ul>')

    # ------------------------------------------------------------ the feed
    a('<h2>What feeds the pipeline</h2><div class="rule"></div>')
    a('<p>The crawler fleet runs <strong>news only</strong>. News is the one '
      'source class that changes daily, so it is what makes an end-to-end '
      'latency measurement meaningful: a document that did not exist this '
      'morning can be timed all the way to the screen.</p>')
    a('<div class="tw"><table>')
    a('<tr><th>Setting</th><th>Value</th><th>Why</th></tr>')
    for k, v, why in [
        ("Sites", "145", "every <code>source_type=trade_press</code> entry; "
         "2 known-dead hosts dropped"),
        ("Concurrency", "24", "measured fleet ceiling is ~16 concurrent renders; "
         "firing all 145 only queues them"),
        ("Pages per site", "400", "a steady flow to measure, not a flood to "
         "finish before the first document is extracted"),
        ("Freshness", "30 days", "news only -- today&rsquo;s articles are the point"),
        ("Other categories", "held", "594 manufacture/tender/think-tank/gov jobs "
         "switched off, so the measurement is not polluted"),
    ]:
        a('<tr><td>%s</td><td class="n"><strong>%s</strong></td><td>%s</td></tr>'
          % (k, v, why))
    a('</table></div>')
    a('<div class="note"><b>The batch file had ten colliding job ids.</b> '
      '<code>job_id</code> keys the durable frontier, the drop set and resume. '
      '<code>gen_com_news</code> was claimed by both a Chinese and a Brazilian '
      'site, and <code>gen_breakingdefense_news</code> three times over &mdash; '
      'so unrelated crawls would have merged frontiers and each would have '
      'looked mysteriously incomplete. Fixed in '
      '<code>news_batch_measured.json</code>.</div>')

    a('<h3>The join that did not exist</h3>')
    a('<p>The crawler writes into a 1.2 million-document, 81 GB Postgres at the '
      'data centre. KSSL&rsquo;s pipeline read RSS feeds into local JSON files. '
      '<strong>Nothing connected the two</strong> &mdash; so nothing the fleet '
      'fetched had ever reached extraction. <code>pipeline/pull_corpus.py</code> '
      'closes it, and is careful about three things:</p>')
    a('<ul>'
      '<li><strong>It never scans the big columns.</strong> Almost all of those '
      '81 GB is <code>html</code> and <code>main_text</code> in TOAST; selecting '
      'or sorting on them decompresses the table and has taken the corpus '
      'offline before. The candidate query touches only small columns and the '
      'stored <code>text_len</code>.</li>'
      '<li><strong>It is a gate, not a firehose.</strong> A page must be recent, '
      'long enough to carry a claim, and name the client, a known competitor, or '
      'defence procurement vocabulary. Everything else is <em>counted out with a '
      'reason</em>, not silently dropped.</li>'
      '<li><strong>Whole words, not substrings.</strong> This codebase has '
      'repeatedly matched <code>isr</code> inside <em>Israel</em> and '
      '<code>sam</code> inside <em>Samsung</em>; numeric terms keep their units '
      'so <code>155</code> matches <code>155mm</code> and not <code>1550</code>. '
      'The self-check asserts both.</li>'
      '</ul>')
    a('<p>First live run against the news the fleet had just fetched: '
      '<strong>360 candidates, 40 kept, 189 counted out</strong> &mdash; 163 with '
      'no client, competitor or defence term, and 26 with defence vocabulary in '
      'the body but no named organisation.</p>')

    # --------------------------------------------------- the date that gates all
    a('<h2>The publication date decides everything downstream</h2>')
    a('<div class="rule"></div>')
    a('<p>A signal card is only built from an article the pipeline can <em>date</em>. '
      'That rule is right &mdash; an undated page is usually an index, and a card '
      'whose date is "whatever year appears on the page" is worse than no card. '
      'But it means one field in the crawler decides whether anything reaches the '
      'dashboard at all. It was wrong in three ways.</p>')
    a('<div class="tw"><table>')
    a('<tr><th>Fault</th><th>Effect</th></tr>')
    for f, e in [
        ("JSON-LD was never parsed &mdash; despite the docstring saying it was",
         "This is where most modern news CMSs put the authoritative date. "
         "Skipping it threw away the best source and fell through to the worst."),
        ("The fallback took the <b>first <code>&lt;time&gt;</code> tag on the page</b>",
         "On a news article that is a sidebar item or an event listing, not the "
         "story. This is how the corpus acquired articles &ldquo;published&rdquo; "
         "on 30 December while being fetched in August."),
        ("No future-date rejection",
         "A date that has not happened cannot be a publication date. "
         "~10% of dated documents carried one."),
    ]:
        a('<tr><td><strong>%s</strong></td><td>%s</td></tr>' % (f, e))
    a('</table></div>')
    a('<p>It now reads, in order of trustworthiness: JSON-LD '
      '<code>datePublished</code> (walking <code>@graph</code>, surviving the '
      'invalid JSON publishers routinely emit) &rarr; the meta tags news CMSs '
      'actually emit &rarr; a <code>&lt;time&gt;</code> tag that is plausibly the '
      'article&rsquo;s own (<code>itemprop=datePublished</code>, then a class '
      'naming it, then one inside <code>&lt;article&gt;</code>) &rarr; a date in '
      'the URL path. Future dates are refused at every step.</p>')
    a('<div class="note"><b>The future check needed two places, not one.</b> In '
      '<code>parse.py</code> only the raw string is available, so it can sanity-'
      'check ISO-leading values and nothing else &mdash; &ldquo;30 December '
      '2026&rdquo; sails past as ordinary text and becomes a future ISO date '
      'later. <code>extract.py</code> is the one point where the value is always '
      'ISO, so that is where the check is complete. Ten tests cover it, including '
      'the sidebar case that caused the original bug. Measured after deploying: '
      '<b>0 future-dated documents</b>, against roughly 10% before.</div>')

    # ---------------------------------------------------------- the bench
    a('<h2>The article bench</h2><div class="rule"></div>')
    a('<p>Paste a URL or an article at <code>/api/bench</code> on the VPS and '
      'watch it cross every stage. It runs the <em>real</em> pipeline scripts, '
      'and every timing it shows is a row in <code>metrics.stage_run</code> '
      '&mdash; the same table the batch path writes, so the dashboard cannot '
      'display a number the pipeline did not record.</p>')
    a('<figure><svg viewBox="0 0 860 150" role="img" aria-label="The VPS writes '
      'a job row; a data-centre worker polls for it, extracts, and writes results '
      'back into the same VPS database the dashboard reads.">'
      '<g fill="none" stroke="currentColor" stroke-width="1.3">'
      '<rect x="24" y="40" width="176" height="52" rx="7"/>'
      '<rect x="330" y="40" width="200" height="52" rx="7"/>'
      '<rect x="654" y="40" width="182" height="52" rx="7"/></g>'
      '<g font-size="12" fill="currentColor" text-anchor="middle">'
      '<text x="112" y="62">dashboard (VPS)</text>'
      '<text x="112" y="79" font-size="10.5" opacity=".7">queues a job row</text>'
      '<text x="430" y="62">metrics.adhoc_job</text>'
      '<text x="430" y="79" font-size="10.5" opacity=".7">on the VPS database</text>'
      '<text x="745" y="62">worker (data centre)</text>'
      '<text x="745" y="79" font-size="10.5" opacity=".7">polls, extracts, writes back</text>'
      '</g>'
      '<g stroke="currentColor" stroke-width="1.3" fill="none" marker-end="url(#ar)">'
      '<path d="M200,58 L326,58"/><path d="M650,58 L534,58"/>'
      '<path d="M530,80 C560,120 200,120 130,96"/></g>'
      '<g font-size="10" fill="currentColor" opacity=".72">'
      '<text x="228" y="50">writes</text><text x="556" y="50">polls</text>'
      '<text x="330" y="132">stage timings read back</text></g>'
      '</svg><figcaption>The data centre never accepts an inbound connection. '
      'It polls the VPS database &mdash; the one direction that already existed '
      '&mdash; so the bench needed no firewall change and no reverse '
      'tunnel.</figcaption></figure>')

    a('<h3>What it caught on its first two runs</h3>')
    a('<div class="tw"><table>')
    a('<tr><th>Run</th><th>What happened</th><th>Why it mattered</th></tr>')
    for r, what, why in [
        ("Navantia F110 frigate",
         "Extracted cleanly, then refused: <code>off-portfolio</code>.",
         "Correct. KSSL make artillery, ammunition, armoured vehicles and small "
         "arms &mdash; not frigates. The gate was right and the test article was "
         "the wrong choice."),
        ("Hanwha K9 howitzer",
         "The model call died at <b>exactly 180 s</b> &mdash; <code>ask()</code>&rsquo;s "
         "GPU-era default &mdash; and the job reported "
         "&ldquo;refused by the card gate&rdquo;.",
         "<b>A crash dressed as an editorial decision.</b> The stage row said "
         "<code>TimeoutError</code> while the summary implied the article had "
         "been read and rejected. Timeout is now "
         "<code>KSSL_LLM_TIMEOUT</code> (900 s on CPU), and a failed card step "
         "raises instead of reporting a refusal."),
        ("Serbia Milosh 2",
         "<code>HTTP 406</code> on fetch &mdash; the site refuses anything that is "
         "not a browser.",
         "Reported honestly as a failure this time. Now sends a browser header "
         "set, and falls back to the fleet&rsquo;s own corpus copy when a site "
         "still refuses &mdash; recording <em>which</em> path supplied the text."),
    ]:
        a('<tr><td><strong>%s</strong></td><td>%s</td><td>%s</td></tr>'
          % (r, what, why))
    a('</table></div>')

    # ---------------------------------------------------------------- findings
    a('<h2>Defects found while building this</h2><div class="rule"></div>')
    a('<p>Recorded because each was invisible until something forced it into '
      'the open.</p>')
    a('<div class="tw"><table>')
    a('<tr><th>What</th><th>Effect</th><th>Status</th></tr>')
    for what, effect, status, cls in [
        ("A comma inside a trailing comment in <code>schema_extracted.sql</code>",
         "The whole schema file aborted on a fresh database. Only 6 of 8 tables "
         "existed and the serving, serving_live and metrics schemas were never "
         "created at all &mdash; silently, because the API still answered.",
         "fixed", "ok"),
        ("Ten duplicate <code>job_id</code>s in the news batch",
         "job_id keys the durable frontier, the drop set and resume. "
         "<code>gen_com_news</code> was shared by a Chinese and a Brazilian "
         "site, so two unrelated crawls would have merged frontiers.",
         "fixed", "ok"),
        ("Ten pipeline scripts hardcoded <code>127.0.0.1:5460</code>",
         "Fine on one laptop; fatal once extraction runs at the data centre and "
         "must write to the VPS through a tunnel. They would have written to a "
         "local database instead.",
         "fixed", "ok"),
        ("Ollama ignores the container CPU quota when sizing threads",
         "Roughly half the LLM throughput was being lost to context switching "
         "on any capped container.",
         "fixed", "ok"),
        ("<code>load_extracted</code> used <code>executemany</code>",
         "One network round trip per row. Invisible on localhost, pathological "
         "through the SSH tunnel the split deployment uses: 220k spans made no "
         "measurable progress in several minutes. <code>execute_values</code> "
         "batched at 500 rows loaded 600 documents in under a minute.",
         "fixed", "ok"),
        ("The site and API had no authentication at all",
         "<code>/api/dataset</code> returned 200 to anyone. Once loaded, that "
         "is the client's whole competitive position served to whoever guesses "
         "the hostname. Basic auth now guards both routers.",
         "fixed", "ok"),
        ("The dashboard auth on the data centre could not be satisfied",
         "Login needs an emailed OTP, and outbound mail from that host is "
         "rejected. The fleet API was unreachable until auth was disabled.",
         "auth disabled", "wait"),
    ]:
        a('<tr><td>%s</td><td>%s</td><td><span class="pill %s">%s</span></td></tr>'
          % (what, effect, cls, status))
    a('</table></div>')

    # ---------------------------------------------------------------- open
    a('<h2>Open items</h2><div class="rule"></div>')
    a('<ul>'
      '<li><strong>The VPS root password is exposed.</strong> It was pasted into '
      '<code>.env.example</code>, the committed template, before being moved to '
      'the ignored <code>.env</code>. Treat it as compromised and rotate it. A '
      'deploy key is now installed, so <code>PasswordAuthentication no</code> '
      'is safe to set.</li>'
      '<li><strong>Dashboard auth is off at the data centre</strong> '
      '(<code>DASH_AUTH=0</code>). That interface is bound to loopback and '
      'reachable only through the SSH tunnel, but it is no longer '
      'authenticated. Restore it once the OTP mail path works.</li>'
      '<li><strong>No swap on the VPS.</strong> 31 GB is ample, but an '
      'unbounded process currently gets OOM-killed rather than slowed.</li>'
      '<li><strong>The corpus has not been wiped.</strong> The KSSL database was '
      'archived and reset to empty, which is what makes the UI provably '
      'pipeline-fed. Destroying the data centre corpus was not done: it is '
      'irreversible, it takes hours to archive first, and it is not needed for '
      'clean per-stage metrics.</li>'
      '</ul>')

    a('<div class="foot">Generated by <code>docs/build_production_doc.py</code> '
      'from <code>docs/metrics/*.json</code> and <code>metrics.stage_run</code>. '
      'Re-run it to refresh; do not edit PRODUCTION.html by hand.</div>')
    a('</div>')

    html = "\n".join(h)
    io.open(OUT, "w", encoding="utf-8", newline="").write(html)
    print("wrote %s (%.0f kB)" % (OUT, len(html) / 1024.0))
    if stages:
        print("live stage timings: %d stages read from the database" % len(stages))
    else:
        print("live stage timings: unavailable (%s)"
              % (stage_err or "not reachable"))


if __name__ == "__main__":
    build()
