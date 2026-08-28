"""Measure what a CPU-only box actually does with these models.

    python3 bench_cpu_llm.py --models qwen3:4b,qwen2.5:7b-instruct --runs 3

Neither the VPS nor the data centre has a GPU, so every number that matters --
how long a signal card takes, how long a document takes to extract -- comes out
of this. Ollama reports its own token counts and nanosecond durations, so the
tokens/sec here is the model's, not a stopwatch guess.

Reports, per model:
  load_s        cold load of the weights into RAM
  prompt_tok_s  how fast it reads the document (prefill)
  gen_tok_s     how fast it writes the answer  <- the number people mean
  call_s        wall clock for one realistic call
  rss_gb        resident memory while loaded

Only stdlib: this runs on a bare VPS with no pip install.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
CONTAINER = os.environ.get("OLLAMA_CONTAINER", "kssl-llm-bench")

# A realistic unit of work, not "write a poem". This is the shape the pipeline
# actually sends: a chunk of a defence news story, and a request for structured
# JSON about it. Length matters -- prefill cost scales with it.
DOC = (
    "Bharat Forge announced on Tuesday that its defence subsidiary Kalyani "
    "Strategic Systems Limited has secured an order worth 1,200 crore rupees "
    "for the supply of 155mm/52 calibre advanced towed artillery gun systems "
    "to the Indian Army. The contract, awarded by the Ministry of Defence "
    "under the Buy (Indian-IDDM) category, covers delivery over 36 months "
    "from the company's Pune facility. The ATAGS platform, developed jointly "
    "with the Defence Research and Development Organisation, has a maximum "
    "range of 48 kilometres and weighs approximately 18 tonnes. Company "
    "officials said the order takes the defence order book past 8,000 crore "
    "rupees. Separately, the firm confirmed continuing discussions with a "
    "European partner on a technology transfer arrangement for gun barrels, "
    "and said its Hanwha Defense collaboration on self-propelled howitzers "
    "remains at the evaluation stage. Analysts noted that Tata Advanced "
    "Systems and Larsen and Toubro are competing for related tenders in the "
    "same segment, and that export interest has come from three countries in "
    "Southeast Asia and the Middle East. Deliveries are expected to begin in "
    "the fourth quarter of the next financial year, subject to trials at the "
    "Pokhran range being completed on schedule. "
) * 2

PROMPT = (
    "Read the article and return JSON with keys: headline (string, under 90 "
    "characters), companies (array of company names actually named), "
    "programmes (array of programme or platform names), value_inr_crore "
    "(number or null), and why_it_matters (two sentences). Use only facts "
    "present in the article. Return JSON and nothing else.\n\n"
    "ARTICLE:\n" + DOC + "\n\nJSON:"
)


def post(path, payload, timeout=1800):
    req = urllib.request.Request(
        OLLAMA + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def rss_gb(model):
    """Resident size of the loaded model, from ollama ps."""
    try:
        out = subprocess.run(
            ["docker", "exec", CONTAINER, "ollama", "ps"],
            capture_output=True, text=True, timeout=30).stdout
    except Exception:                                   # noqa: BLE001
        return None
    for line in out.splitlines():
        if line.startswith(model.split(":")[0]):
            parts = line.split()
            for i, p in enumerate(parts):
                if p.upper() in ("GB", "MB") and i:
                    try:
                        v = float(parts[i - 1])
                    except ValueError:
                        continue
                    return round(v / 1024, 2) if p.upper() == "MB" else v
    return None


def bench(model, runs, npredict, threads=None):
    out = {"model": model, "runs": []}

    # ---- cold load: unload first, so load_s is a real cold number
    try:
        post("/api/generate", {"model": model, "keep_alive": 0, "prompt": ""})
    except Exception:                                   # noqa: BLE001
        pass
    time.sleep(2)

    for i in range(runs):
        t0 = time.time()
        try:
            r = post("/api/generate", {
                "model": model,
                "prompt": PROMPT,
                "stream": False,
                "options": dict({"num_predict": npredict, "temperature": 0,
                                 "num_ctx": 8192},
                                **({"num_thread": threads} if threads else {})),
            })
        except urllib.error.URLError as exc:
            print("  run %d FAILED: %s" % (i + 1, exc))
            out["runs"].append({"ok": False, "error": str(exc)})
            continue
        wall = time.time() - t0

        # ollama returns nanoseconds
        ld = r.get("load_duration", 0) / 1e9
        pc, pd = r.get("prompt_eval_count", 0), r.get("prompt_eval_duration", 0) / 1e9
        ec, ed = r.get("eval_count", 0), r.get("eval_duration", 0) / 1e9
        row = {
            "ok": True,
            "call_s": round(wall, 2),
            "load_s": round(ld, 2),
            "prompt_tokens": pc,
            "prompt_tok_s": round(pc / pd, 2) if pd else None,
            "gen_tokens": ec,
            "gen_tok_s": round(ec / ed, 2) if ed else None,
        }
        out["runs"].append(row)
        print("  run %d: %6.1fs  prefill %5d tok @ %6.1f tok/s   "
              "generate %4d tok @ %5.2f tok/s"
              % (i + 1, row["call_s"], pc, row["prompt_tok_s"] or 0,
                 ec, row["gen_tok_s"] or 0))

    ok = [r for r in out["runs"] if r.get("ok")]
    if ok:
        # first call carries the cold load; report steady state separately
        steady = ok[1:] or ok
        out["summary"] = {
            "cold_load_s": ok[0]["load_s"],
            "gen_tok_s": round(sum(r["gen_tok_s"] for r in steady) / len(steady), 2),
            "prompt_tok_s": round(sum(r["prompt_tok_s"] for r in steady) / len(steady), 2),
            "call_s": round(sum(r["call_s"] for r in steady) / len(steady), 2),
            "gen_tokens": round(sum(r["gen_tokens"] for r in steady) / len(steady)),
            "rss_gb": rss_gb(model),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen3:4b,qwen2.5:7b-instruct")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--npredict", type=int, default=600)
    ap.add_argument("--out", default="/opt/kssl/bench/llm_bench.json")
    ap.add_argument("--label", default="")
    # ollama sizes its thread pool from the HOST cpu count, not the container's
    # cpu quota. Below the quota that is pure contention, so this exists to test
    # whether matching threads to the cap recovers the loss.
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args()

    cores = os.cpu_count()
    print("host cores visible: %s   prompt: %d chars, num_predict=%d"
          % (cores, len(PROMPT), a.npredict))
    print("")

    results = []
    for m in [x.strip() for x in a.models.split(",") if x.strip()]:
        print("%s" % m)
        results.append(bench(m, a.runs, a.npredict, a.threads or None))
        print("")

    doc = {"label": a.label, "cores_visible": cores,
           "prompt_chars": len(PROMPT), "npredict": a.npredict,
           "results": results}
    with open(a.out, "w") as f:
        json.dump(doc, f, indent=2)

    print("=" * 74)
    print("%-24s %9s %11s %11s %9s %7s" %
          ("model", "gen tok/s", "prefill t/s", "one call s", "cold load", "GB"))
    print("-" * 74)
    for r in results:
        s = r.get("summary")
        if not s:
            print("%-24s  no successful run" % r["model"])
            continue
        print("%-24s %9.2f %11.1f %11.1f %9.1f %7s" %
              (r["model"], s["gen_tok_s"], s["prompt_tok_s"], s["call_s"],
               s["cold_load_s"], s["rss_gb"] if s["rss_gb"] else "?"))
    print("=" * 74)
    print("written to %s" % a.out)


if __name__ == "__main__":
    sys.exit(main())
