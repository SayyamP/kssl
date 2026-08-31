"""Comprehension extraction — break an article into pieces, keep every piece's context.

WHAT THIS IS FOR, AND HOW IT DIFFERS FROM l2/extract.py
-------------------------------------------------------
The old extractor answered "which named entities are in this document?" and averaged 17 per doc —
roughly 5% of the words. That is a filter, not comprehension. A person reading the same article
understands essentially all of it: each word has a meaning, the sentence gives those words a joint
meaning, and what is retained is the structure, not the page.

So this pipeline inverts the objective. Every CONTENT token must end up explained by some
annotation, and what cannot be explained is counted and shown rather than quietly dropped. The
score that matters is content coverage (see segment.coverage), and the target is high, not "enough
entities to look useful".

Concretely that means capturing what NER deliberately throws away:
  - common nouns ("hat", "quality assurance", "fuselage") — most of an article's meaning
  - verbs and actions ("signed", "delivers", "will replace") — without these there are no events
  - attributes ("padded", "gray", "airworthy") — the properties the ontology later hangs off
  - values (money, dates, measurements) — handled deterministically in values.py
  - the sentence-level proposition tying them together — who did what, to what, when, where

FOUR GENERATORS, UNIONED
------------------------
  1. values.py     deterministic; best at money/measure/date, which the LLM is worst at
  2. GLiNER        high-recall span finder, general labels, threshold 0.2
  3. LLM pass      the comprehension pass: every meaningful span + gloss + role + propositions
  4. residual pass whatever content tokens the first three missed, re-offered to the LLM

Generator 4 exists because coverage is the objective. Without it the pipeline has no mechanism that
reacts to its own misses — it would report a hole and do nothing about it.

RULES CARRIED FROM THE EARLIER BUILD (each cost a debugging round)
------------------------------------------------------------------
  - Never ask the model for character offsets. Force a VERBATIM quote and locate it in code.
    A model-supplied offset is wrong often enough to poison every highlight.
  - Size the reply budget to the input. A truncated JSON reply returns NOTHING for the chunk, and
    one Italian document produced zero entities that way. Falling back to the NER verdict on a
    failed call is what keeps a bad call from erasing a chunk.
  - Silence is not rejection. An item the model does not mention is not thereby denied.
  - A span that cannot be located verbatim is dropped AND audited, never stored unbacked.
"""
import functools
import json
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
import lexicon  # noqa: E402
import values  # noqa: E402
from segment import classify, coverage, detect_lang, sentences, tokenize  # noqa: E402

HERE = Path(__file__).parent
# One pooled client for the whole process. `httpx.post()` builds a fresh Client -- transport,
# connection pool and an SSL context even for http:// -- then tears it down, on EVERY call:
# measured 8.45ms against 0.29ms for a shared client (29x), all of it GIL-held, plus a socket
# into TIME_WAIT per request. httpx.Client is thread-safe, so the worker pool can share one.
_HTTP = httpx.Client(
    timeout=httpx.Timeout(connect=10.0, read=420.0, write=30.0, pool=10.0),
    limits=httpx.Limits(max_connections=64, max_keepalive_connections=64),
    # The farm gateways sit behind Cloudflare, whose bot protection 403s the default python-httpx
    # User-Agent. A browser/curl UA gets through. Harmless to a local Ollama, required for the farm.
    headers={"User-Agent": os.environ.get("C_USER_AGENT", "curl/8.4.0")})

# The 420s read timeout above is only a FLOOR for calls that do not know their own size (GLiNER
# passes its own). For generation it is incoherent: `stream: False` means the whole reply must
# arrive within one read, so the timeout is the total generation time, while reply_budget legally
# asks for up to 24,000 tokens. Clearing that inside 420s needs 57.1 tok/s. Measured rates:
#
#     vps-a 15.4    vps-b 11.95 (post thread-fix)    dc 7.79    farm 53.5
#
# -- so NO node can do it, the farm included. The failure is also the worst possible shape: the
# socket closes with an empty body, the reply is lost whole, and the work is charged anyway.
# Deriving the timeout from the tokens actually requested makes an honest long generation finish
# and still bounds a degenerate one, which cannot exceed num_predict by construction.
def _keep_alive_value(raw):
    """Ollama accepts keep_alive as an INTEGER (seconds; -1 = pin resident) or as a duration
    STRING with a unit ("24h"). A bare numeric string is neither, and it does not fail quietly:
    every generate call returns HTTP 400 `time: missing unit in duration "-1"`, all three retries
    burn, every chunk is recorded as llm_call_failed, and the document is released and eventually
    parked. Shipping "-1" took the dc from slow to producing nothing at all."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return raw                    # a duration string like "24h" -- passed through untouched


# -1 pins the model resident. The alternative is paying an 80-100s reload per document on a node
# whose own back-pressure rest exceeds Ollama's 5-minute default.
_KEEP_ALIVE = _keep_alive_value(os.environ.get("C_KEEP_ALIVE", "-1"))
_TOK_S = float(os.environ.get("C_TOK_S", "4.0"))          # THIS node's measured rate; low = safe
_TIMEOUT_SAFETY = float(os.environ.get("C_TIMEOUT_SAFETY", "1.5"))
# C_LLM_TIMEOUT is the name already deployed (dc=1800). Honour it as the FLOOR so an operator who
# raised it keeps that floor, while a request larger than the floor can still earn more time.
_TIMEOUT_FLOOR = float(os.environ.get("C_TIMEOUT_FLOOR")
                       or os.environ.get("C_LLM_TIMEOUT") or 420)
# The ceiling is DERIVED, not picked. npred is a permission, not a forecast: reply_budget hands
# out up to 24,000 tokens, but the densest chunk ever measured needed 13,212 (the figure the
# budget assertions below are pinned to). Waiting for a realistically dense reply is the promise
# worth making; waiting for the absolute cap means holding a worker for hours on a reply that
# only a degenerate loop would produce.
_DENSE_TOKENS = 13212
_TIMEOUT_CEIL = float(os.environ.get("C_TIMEOUT_CEIL", "0") or 0) or (
    _DENSE_TOKENS / max(0.1, _TOK_S) * _TIMEOUT_SAFETY + 30.0)


def _read_timeout(tokens):
    """Read timeout for a generation asking for `tokens` output tokens.

    Floor at the old 420s so this can only ever grant MORE time than before -- no call that
    used to succeed can start failing. Ceiling because a runaway that ignores its stop condition
    should not hold a worker for an hour.
    """
    want = tokens / max(0.1, _TOK_S) * _TIMEOUT_SAFETY + 30.0
    return httpx.Timeout(connect=10.0, read=max(_TIMEOUT_FLOOR, min(_TIMEOUT_CEIL, want)),
                         write=30.0, pool=10.0)

# C_FORMAT=tsv makes the model emit tab-separated lines instead of JSON. Measured with the
# production Qwen2.5-7B tokenizer on a 4-span reply: JSON 158 tokens of which 93 (58.9%) are
# scaffolding -- braces, quoted keys, commas -- carrying no information. The same four records as
# TSV are 72 tokens, 9.7% scaffolding: 2.19x fewer tokens for identical content. Generation is
# ~99.99% of a document's wall clock, so this is the largest lever that lives in our own code.
#
# DEFAULT IS json. TSV gives up schema-constrained decoding (Ollama `format` / vLLM `guided_json`),
# so the model can drift and the parser has to be tolerant. Flip it only behind quality_gate.py.
# What makes that safe to try at all: a malformed span cannot corrupt the store, because locate()
# still has to find the quote verbatim in the document, and anything it cannot find is dropped and
# audited. A format regression shows up as measurable recall loss, never as silent bad data.
_FORMAT = os.environ.get("C_FORMAT", "json").strip().lower()


def _tsv_spec(schema):
    """The line format, derived FROM the schema so it cannot drift out of sync with it."""
    return "\n".join(k + "\t" + "\t".join("<%s>" % f for f in v["items"]["properties"])
                     for k, v in schema["properties"].items())


def _tsv_parse(raw, schema):
    """TSV lines -> the exact dict shape json.loads would have produced.

    Returning the same shape is the point: every caller downstream is untouched, so the diff is
    the wire format and nothing else. Deliberately tolerant -- unknown leading tags are skipped and
    short lines are padded, because a strict parser would throw away a reply that is 95% good.
    """
    keys = {k: list(v["items"]["properties"]) for k, v in schema["properties"].items()}
    out = {k: [] for k in keys}
    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        parts = line.rstrip("\r").split("\t")
        fields = keys.get(parts[0].strip())
        if not fields:
            continue                      # prose, a stray header, a fenced code marker
        vals = [v.strip() for v in parts[1:1 + len(fields)]]
        out[parts[0].strip()].append(dict(zip(fields, vals + [""] * (len(fields) - len(vals)))))
    return out


OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("C_MODEL", "qwen2.5:7b")
# How many threads the MODEL SERVER should use. Ollama sends no `-t` flag, so llama.cpp falls back
# to counting the HOST's physical cores from sysfs -- which ignores the container's cpuset. Observed
# on the datacentre: a container pinned to 10 cores (20-29) reported `n_threads = 40`, and one
# pinned to 5 cores reported the same. ggml's per-layer thread barrier is a SPINLOCK hit hundreds
# of times per token, so 40 threads on 10 cores does not merely fail to help -- every barrier
# becomes a context-switch storm. Measured effect: ~5-6 GB/s of effective memory bandwidth against
# ~130-150 GB/s the socket can sustain, i.e. ~15% of the hardware.
#
# Set this to the number of cores the SERVER's cpuset actually grants (10 for the 20-29 pinning).
# It must stay CONSTANT for a run: num_thread is a load-time option, so changing it makes Ollama
# evict and reload the model (~150s on CPU). Unset (0) sends nothing and preserves prior behaviour.
# Two names for one knob, and the deployed one is C_LLM_THREADS -- every worker container sets
# it (dc=6, vps-a=7, vps-b=4) while activate_dc.sh exports C_NUM_THREAD. Reading only one name
# silently drops the thread fix, and that fix is worth 44x on the DC (0.176 -> 7.790 tok/s), so
# the failure would look like "everything is mysteriously slow" with nothing in any log.
_NUM_THREAD = int(os.environ.get("C_LLM_THREADS") or os.environ.get("C_NUM_THREAD") or 0)
# Sampling temperature. 0 (greedy) is right for qwen2.5 and is what every measurement here was
# taken at. It is NOT safe for Qwen3-family models: Qwen document that greedy decoding causes
# repetition loops and degraded output, and this pipeline already has a documented history of that
# exact pathology (unparseable replies growing 9,271 -> 20,818 -> 38,952 chars with the budget).
# So a Qwen3 / MoE endpoint must run ~0.2-0.3 with a fixed seed -- near-deterministic, but off the
# greedy failure mode. Keep it 0 for qwen2.5 so existing results stay reproducible.
_TEMP = float(os.environ.get("C_TEMP", "0") or 0)
_SEED = int(os.environ.get("C_SEED", "0") or 0)   # pin it when temperature > 0

# Endpoint auth. A local Ollama daemon needs none; a remote/farm gateway may want a Bearer key or
# HTTP Basic. Env-gated so local runs are byte-identical: set OLLAMA_API_KEY for Bearer, or
# OLLAMA_USER + OLLAMA_PASS for Basic. ponytail: the two auth modes the farm guide documents, no third.
_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
_BASIC_USER = os.environ.get("OLLAMA_USER", "")
# The farm gateway is OpenAI-shaped (POST /v1/chat/completions, Bearer key, guided_json for
# structured output); a plain local Ollama is native (POST /api/generate, format=schema). A Bearer
# key means we are talking to the gateway. Force with C_OPENAI=0/1 if that heuristic is ever wrong.
_OPENAI = os.environ.get("C_OPENAI", "1" if _API_KEY else "0") == "1"
# guided_json (constrained decoding) is correct but does NOT scale with concurrency on the farm's
# vLLM — it stays ~70 tok/s per call however many run at once, so high concurrency drives each call
# past the gateway's 100s timeout. Free generation scales; the prompt already asks for JSON and
# _salvage recovers imperfect replies. Set C_GUIDED=0 to drop the constraint and run fast.
_GUIDED = os.environ.get("C_GUIDED", "1") == "1"


def _auth():
    """httpx auth kwargs for the model endpoint; empty dict for a no-auth local daemon."""
    if _API_KEY:
        return {"headers": {"Authorization": f"Bearer {_API_KEY}"}}
    if _BASIC_USER:
        return {"auth": httpx.BasicAuth(_BASIC_USER, os.environ.get("OLLAMA_PASS", ""))}
    return {}
GLINER_MODEL = os.environ.get("C_GLINER", "urchade/gliner_multi-v2.1")
GLINER_TH = float(os.environ.get("C_GLINER_TH", "0.2"))
# When set, NER runs on the farm's /extract (GPU, load-balanced) instead of a local torch model:
# one HTTP call per document (all its sentences batched), no local model, no serialization lock.
_GLINER_URL = os.environ.get("C_GLINER_URL", "")
CHUNK_CHARS = int(os.environ.get("C_CHUNK", "700"))
# A span is a PHRASE, not a clause. The first run returned spans like "Cubic creates and delivers
# technology solutions" typed Action: that covers 7 content tokens in one annotation and inflates
# the score without explaining any individual word. Clause-length material is what the proposition
# layer is for, so anything longer than this is refused as a span.
MAX_SPAN_CHARS = int(os.environ.get("C_MAX_SPAN", "60"))
MAX_SPAN_WORDS = int(os.environ.get("C_MAX_SPAN_W", "8"))

# Short, concrete labels only. GLiNER scores labels jointly, so long disjunctive labels collapse:
# "building or facility or plant or base or port" found 0 of 8 facilities where "military base or
# facility" found 25%. Never merge these into one string.
GLINER_LABELS = [
    "person", "organization", "company", "government agency", "country", "city or region",
    "military base or facility", "product", "vehicle", "aircraft", "ship", "weapon",
    "missile", "equipment", "material", "technology", "program or project", "contract or tender",
    "job title or role", "event", "document or standard", "date", "money amount", "measurement",
]

# The span vocabulary. Deliberately wider than the L2 ontology: this layer's job is to account for
# the article, and the ontology's job is to decide what it keeps. Narrowing here is unrecoverable —
# that was the finding from the external benchmark, where a defence-only finder proposed 9 spans
# against 42 gold on a machine-tool release and the LLM never got a chance to keep them.
TYPES = ["Person", "Organization", "Location", "Country", "Facility", "Platform", "WeaponSystem",
         "Equipment", "Product", "Material", "Technology", "Program", "Contract", "Role", "Event",
         "Action", "Attribute", "Concept", "Date", "Money", "Measure", "Count", "Identifier",
         "Document", "Language", "Other"]

# Types where "what does this refer to in THIS article" is a real question with a real answer.
# A verb or an adjective has a dictionary meaning and nothing article-specific to add.
REFERENTIAL = {"Person", "Organization", "Location", "Country", "Facility", "Platform",
               "WeaponSystem", "Equipment", "Product", "Program", "Contract", "Identifier",
               "Document", "Event"}

# values.py speaks its own vocabulary; this is the only place it is translated into ours.
VALUE_TYPE = {"money": "Money", "percent": "Measure", "measurement": "Measure", "date": "Date",
              "duration": "Measure", "count": "Count", "identifier": "Identifier",
              "email": "Identifier", "url": "Identifier", "phone": "Identifier"}

SPAN_SCHEMA = {
    "type": "object",
    "properties": {
        "spans": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "type": {"type": "string", "enum": TYPES},
                "gloss": {"type": "string"},
                "in_article": {"type": "string"},
            }, "required": ["text", "type", "gloss", "in_article"]}},
        "propositions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "time": {"type": "string"},
                "place": {"type": "string"},
                "polarity": {"type": "string", "enum": ["positive", "negative"]},
                "modality": {"type": "string",
                             "enum": ["asserted", "planned", "possible", "reported", "required"]},
                "evidence": {"type": "string"},
            }, "required": ["subject", "predicate", "object", "evidence"]}},
    }, "required": ["spans", "propositions"]}

PROMPT = """You are breaking an article into every meaningful piece, so that later someone can answer questions about the article using only your output.

TEXT:
\"\"\"{text}\"\"\"

Return JSON with two lists.

"spans" — EVERY meaningful piece of the text. Be exhaustive, not selective:
- named things: people, organisations, places, products, platforms, weapons, programs
- ORDINARY nouns too: "hat", "belt loop", "quality assurance", "fuselage", "customer"
- verbs and actions: "signed", "delivers", "will replace", "is recruiting"
- attributes and properties: "padded", "gray", "airworthy", "waterproof"
- roles and job titles, documents, standards, technologies, materials
Do NOT include pure grammar words (the, a, of, and, is).
For each span:
  text       = copied EXACTLY from the text above, character for character
  type       = one of: {types}
  gloss      = what this word/phrase means in general, one short clause
  in_article = what it refers to HERE, in this specific article, one short clause

RULES for spans:
- Keep each span SHORT: a word or a phrase, at most {maxw} words. Never a whole clause or sentence.
  "Cubic creates and delivers technology solutions" is NOT a span — that is a proposition.
  Split it: "Cubic", "creates", "delivers", "technology solutions".
- gloss and in_article MUST be different from each other. gloss is the dictionary meaning, ignoring
  this article. in_article says who or what it actually is HERE.
  Example: text "Cubic" -> gloss "a solid shape with six equal square faces; also a company name",
  in_article "Cubic Corporation, the defence technology supplier this article is about".

"propositions" — what the text actually states. One per fact:
  subject   = who or what (a SHORT phrase, max 6 words)
  predicate = the relation ONLY, 1-3 words, usually a verb: "delivers", "is a", "signed with"
  object    = what the predicate applies to (a SHORT phrase, max 8 words). NEVER leave this empty —
              if there is no object, do not emit the proposition at all.
  time, place = when/where if the text says, else ""
  polarity   = positive, or negative if the text denies it
  modality   = asserted / planned / possible / reported / required
  evidence   = the EXACT sentence fragment from the text that states this

Write gloss and in_article in English even when the text is not.
Copy "text" and "evidence" verbatim from the text — do not translate, correct or reformat them."""


def _salvage(raw):
    """Recover the complete objects from a truncated JSON reply.

    A reply cut off by num_predict is unparseable as a whole, but the items BEFORE the cut are
    intact. Discarding all of them is how one chunk of a document silently contributed nothing --
    observed here (a 10,242-char reply) and previously on an Italian document that ended up with
    zero entities. Scanning for balanced top-level objects inside each named array recovers them.
    """
    out = {}
    for key in ("spans", "propositions"):
        m = re.search(rf'"{key}"\s*:\s*\[', raw)
        if not m:
            continue
        items, depth, start, instr, esc = [], 0, None, False, False
        for i in range(m.end(), len(raw)):
            ch = raw[i]
            if instr:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    instr = False
                continue
            if ch == '"':
                instr = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        items.append(json.loads(raw[start:i + 1]))
                    except json.JSONDecodeError:
                        pass
                    start = None
            elif ch == "]" and depth == 0:
                break
        if items:
            out[key] = items
    return out or None


def _ollama(prompt, schema, num_predict, model=None, retries=3, num_ctx=None, audit=None):
    """One call. Returns a dict, or None if the call genuinely failed (caller must not treat that
    as 'the model found nothing'). An unparseable reply is salvaged rather than retried.

    `audit` records salvage as a durable row. It used to be a print only, which made the rate
    measurable exclusively by grepping a log -- and with several workers the log interleaves with
    no document tag, so per-document and per-language rates could not be attributed at all. A
    quality event that is only observable in stdout is a quality event nobody can regression-test.
    """
    last_raw = ""
    for attempt in range(retries):
        # Do NOT escalate the reply budget HERE. That measurement stands: an unparseable reply
        # grew WITH the budget -- 9,271 chars at npred=2,665, then 20,818 at 6,000, then 38,952 at
        # 12,000, all unparseable. That is a repetition loop, and a bigger budget buys a longer
        # loop. Escalating per attempt would pay minutes for nothing on every one of them.
        #
        # But that conclusion was over-generalised to every unparseable reply, and it is not.
        # TRUNCATION looks identical here -- a truncated reply is also unparseable, and it also
        # runs to its ceiling, so reply LENGTH cannot separate the two. The difference is whether
        # more budget ever FINISHES the job: a truncated reply plateaus and parses, a loop does
        # not. Measured 2026-08-21 (probe_truncation.py): 50% of documents were hitting a ceiling
        # that was simply set too low, and the fix belongs in reply_budget where it is paid once,
        # not in a per-attempt escalation where a loop would be paid for repeatedly.
        npred = num_predict
        # num_ctx holds prompt AND reply. Fixed at 8192 it was the REAL ceiling once the reply
        # budget was raised: a dense chunk wanting ~5,000 output tokens plus a ~1,500-token prompt
        # fits, but a bigger one silently does not, and the reply is cut with no audit row saying
        # so -- the budget would look generous while the context quietly truncated. Sized from the
        # actual request, with a bound so one pathological chunk cannot ask for a huge KV cache on
        # a card shared by four workers.
        # ...and BUCKETED to powers of two, because num_ctx is a LOAD-time option: Ollama keys the
        # loaded runner on it, so a value it has not seen evicts the runner and re-reads the whole
        # model. Sizing ctx from (prompt, npred) produced 117 DISTINCT values across 228 measured
        # calls -- i.e. a full reload on most calls, ~150s each on CPU where there is no GPU to
        # hide it. Three buckets means at most three loads per run. Rounding UP is always safe:
        # num_ctx only has to be >= the requirement, so this cannot change a single token.
        # /2.5 not /3.0 -- CJK packs more tokens per character, and under-estimating the prompt is
        # what silently truncates a reply with no audit row.
        if _FORMAT == "tsv":
            prompt = (prompt + "\n\nOutput format: ONE RECORD PER LINE, fields separated by a "
                      "single TAB character. No JSON, no markdown, no code fences, no commentary. "
                      "Each line must begin with its record type:\n" + _tsv_spec(schema))
        need = int(len(prompt) / 2.5) + npred + 512
        ctx = num_ctx or min(32768, max(8192, 1 << (need - 1).bit_length()))
        # ...and C_NUM_CTX overrides even that. num_ctx is a LOAD-time option: on a GPU a reload
        # is seconds and invisible, but on CPU it is a full reload plus a ~3 GB weight repack, per
        # chunk -- and if a second client asks while a load is in flight, Ollama ABORTS the load
        # ("client connection closed before llama-server finished loading") and nothing ever
        # finishes. Measured at the data centre 2026-08-26: five aborted loads in forty seconds
        # and not one completed generation. Pinning it makes one runner serve the whole document.
        fixed = os.environ.get("C_NUM_CTX")
        if fixed:
            ctx = int(fixed)
        # npred must fit INSIDE ctx. reply_budget caps the Latin-equivalent budget at 24,000 then
        # multiplies by up to 2.29 for hungry scripts, so npred reached 37,762 in the live store --
        # above the 32,768 ceiling. When npred > ctx llama.cpp shifts context mid-generation, which
        # produces exactly the degenerate repetition the budget cap was built to defend against.
        # The clamp lives here, not in reply_budget, so the measured budget assertions still hold.
        # Floor at 256: a prompt larger than ctx makes this go negative, and Ollama reads a negative
        # num_predict as -1 (unlimited) -- the worst possible request on a CPU node, generating until
        # the context fills. A chunk that cannot fit prompt+reply in ctx should be split upstream
        # (chunks() caps sentence length); the floor is the last-resort guard so it can never crash.
        npred = max(256, min(npred, ctx - int(len(prompt) / 2.5) - 256))
        if _OPENAI:
            # vLLM/OpenAI gateway. guided_json restricts generation to the schema (farm guide:
            # "Verified working"). This model's context is small (4096): prompt + max_tokens must
            # fit inside it, or the gateway 400s (ContextWindowExceededError) and can spill to an
            # unconstrained fallback that ignores guided_json. Cap the completion to what's left
            # after a conservative prompt estimate (/2.0 is safe even for CJK, which packs more
            # tokens per char). ponytail: 4096 is THIS model's ceiling; C_CTX_MAX retunes it.
            endpoint = f"{OLLAMA}/v1/chat/completions"
            ctx_max = int(os.environ.get("C_CTX_MAX", "4096"))
            mt = max(256, min(npred, ctx_max - int(len(prompt) / 2.0) - 128))
            body = {"model": model or MODEL, "temperature": _TEMP, "max_tokens": mt,
                    "messages": [{"role": "user", "content": prompt}]}
            want_tokens = mt
            if _GUIDED and _FORMAT != "tsv":
                body["guided_json"] = schema
        else:
            endpoint = f"{OLLAMA}/api/generate"
            opts = {"temperature": _TEMP, "num_ctx": ctx, "num_predict": npred}
            if _TEMP and _SEED:
                opts["seed"] = _SEED          # pinned seed keeps a non-greedy run reproducible
            if _NUM_THREAD:
                opts["num_thread"] = _NUM_THREAD
            # keep_alive per request, because the duty cycle guarantees eviction otherwise.
            # Ollama's default keep_alive is 5 minutes; vps-b rests as long as it worked (50%
            # duty), so its model is evicted after EVERY document and every document then pays a
            # cold load. Measured on both VPS endpoints: load_duration 80-100s, on documents whose
            # whole generation is a few minutes. It also explains a 5x disagreement in measured
            # tok/s -- a cold probe reads 2.26 where a warm bench reads 11.95, and both are right.
            # Set from the request so no one else's container config has to change.
            body = {"model": model or MODEL, "prompt": prompt, "stream": False,
                    "keep_alive": _KEEP_ALIVE, "options": opts}
            want_tokens = npred
            # `format` constrains generation to the JSON schema, so leaving it on would force JSON
            # back out and silently cancel C_FORMAT=tsv. The trade is explicit: TSV buys 2.19x
            # fewer tokens and gives up the grammar that guaranteed a parseable reply.
            if _FORMAT != "tsv":
                body["format"] = schema
        try:
            r = _HTTP.post(endpoint, json=body, timeout=_read_timeout(want_tokens),
                           **_auth())
            if r.status_code == 200:
                raw = (r.json()["choices"][0]["message"]["content"] if _OPENAI
                       else r.json().get("response", ""))
                last_raw = raw or last_raw
                if _FORMAT == "tsv":
                    return _tsv_parse(raw, schema)
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    sal = _salvage(raw)
                    if sal:
                        got = sum(len(v) for v in sal.values())
                        if audit is not None:
                            audit.append({"kind": "llm_reply_truncated",
                                          "detail": {"reply_chars": len(raw), "npred": npred,
                                                     "salvaged": got}})
                        print(f"      [llm] unparseable ({len(raw)} chars) -- salvaged "
                              f"{got} complete items", flush=True)
                        return sal
                    print(f"      [llm] unparseable reply ({len(raw)} chars), nothing salvageable "
                          f"-- attempt {attempt + 1}/{retries}", flush=True)
            else:
                print(f"      [llm] HTTP {r.status_code} attempt {attempt + 1}/{retries}",
                      flush=True)
        except Exception as e:
            print(f"      [llm] {type(e).__name__} attempt {attempt + 1}/{retries}", flush=True)
        time.sleep(1.5 * (attempt + 1))
    return _salvage(last_raw)


# Length-preserving punctuation folding. STRICTLY one character to one character, so an offset in
# the folded string is the same offset in the original — that is what lets us match loosely and
# still store exact spans. Anything that changes length (… -> ..., œ -> oe) is deliberately absent.
_FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "«": '"', "»": '"',
    "–": "-", "—": "-", "‑": "-", "‒": "-", "−": "-", "‐": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", "　": " ",
})


def fold(s):
    return s.translate(_FOLD)


@functools.lru_cache(maxsize=8)
def _folded_doc(text):
    """fold() for the WHOLE document, memoised.

    locate() is called once per span -- ~533 times per document -- and each call re-folded the
    entire document. Length-preserving by construction (see _FOLD), so the cached result is still
    offset-identical to the original: this cannot move a single character position. Bounded at 8
    entries so a long run cannot accumulate documents, and thread-safe.
    """
    return text.translate(_FOLD)


def locate(needle, text, window=None, used=None):
    """Find a verbatim quote and return (start, end), preferring an unused occurrence inside the
    window it came from. Returns None when the model invented or altered the text — which is the
    whole point: an unlocatable span is a hallucination and must not be stored."""
    if not needle or not needle.strip():
        return None
    used = used if used is not None else set()
    cands = []
    n = needle.strip()
    # Match against the FOLDED text. The model reliably emits straight quotes and hyphens where the
    # article has curly ones, which made every French phrase with an apostrophe and every quoted
    # passage unlocatable -- 12 of 34 propositions on one document were discarded for this alone.
    ftext, fn = _folded_doc(text), fold(n)
    for hay_start, hay_end in ([window] if window else []) + [(0, len(text))]:
        seg = ftext[hay_start:hay_end]
        idx = seg.find(fn)
        while idx != -1:
            s = hay_start + idx
            cands.append((s, s + len(fn)))
            idx = seg.find(fn, idx + 1)
        if cands:
            break
    if not cands:
        # Whitespace inside the quote may differ (the model re-flows newlines); match flexibly.
        flex = re.compile(r"\s+".join(re.escape(w) for w in fn.split()), re.S)
        lo, hi = window if window else (0, len(text))
        m = flex.search(ftext, lo, hi) or flex.search(ftext)
        if m:
            cands.append((m.start(), m.end()))
    if not cands and len(fn.split()) >= 8:
        # A long evidence quote the model paraphrased or truncated at the tail: anchor on its first
        # words and extend to the end of that sentence. Better a slightly wider true span than
        # discarding a real statement.
        head = r"\s+".join(re.escape(w) for w in fn.split()[:7])
        m = re.search(head, ftext, re.S)
        if m:
            tail = re.search(r"[.!?…]\s|\n|$", ftext[m.end():])
            end = m.end() + (tail.end() if tail else 0)
            cands.append((m.start(), min(len(text), max(end, m.end()))))
    for c in cands:
        if c not in used:
            return c
    return cands[0] if cands else None


_GLINER_LOCK = threading.Lock()


def gliner_spans(text, model_holder=[None]):
    """GLiNER general-label pass. Returns [] and says so if the model cannot be loaded — a missing
    finder must be visible, not silently reduce coverage.

    Serialized: `model_holder` is a module-level singleton and the model is one torch object, so
    two workers would race to load it and then call predict_entities on the same weights. The LLM
    calls are what the wall clock is made of, and those still overlap -- this lock only stops two
    workers being inside GLiNER at the same moment.
    """
    if _GLINER_URL:
        return _gliner_remote(text)          # remote GPU: no shared model, so no lock -- workers overlap
    with _GLINER_LOCK:
        return _gliner_spans(text, model_holder)


def _gliner_remote(text, retries=3):
    """NER via the farm's /extract. All of a document's sentences go in ONE call (a list batches
    into one GPU pass per the farm guide). Same output shape and offset arithmetic as the local
    pass, and span text is sliced from the document so document.text[start:end] == span.text holds
    by construction. Returns [] on hard failure -- a missing finder must be visible, not silently
    reduce coverage; the caller already treats [] that way."""
    segs = [s for s in sentences(text) if s["text"].strip()]
    if not segs:
        return []
    # The farm GLiNER contract is {"texts":[...]} -> {"results":[[...]]}. "texts" is the key that
    # the current gateway accepts; "text" alone returns HTTP 422/400 and drops all NER silently.
    # Both keys are sent so an older server that reads "text" still works -- extra fields are
    # ignored by pydantic/FastAPI, so this is safe against either shape.
    _sent_texts = [s["text"] for s in segs]
    body = {"texts": _sent_texts, "text": _sent_texts, "labels": GLINER_LABELS, "threshold": GLINER_TH}
    for attempt in range(retries):
        try:
            r = _HTTP.post(_GLINER_URL, json=body, timeout=120, **_auth())
            if r.status_code == 200:
                results = r.json().get("results")
                # Contract drift is a hard failure, not "zero entities": a renamed field or a
                # short/long results list must retry, then surface, never be read as an empty doc.
                if not isinstance(results, list) or len(results) != len(segs):
                    print(f"    [ner] contract drift: results={type(results).__name__} "
                          f"len={len(results) if isinstance(results, list) else 'n/a'} "
                          f"vs {len(segs)} sents, attempt {attempt + 1}/{retries}", flush=True)
                    time.sleep(1.5 * (attempt + 1))
                    continue
                out = []
                for sent, ents in zip(segs, results):
                    for e in ents or []:
                        s, end = sent["start"] + e["start"], sent["start"] + e["end"]
                        out.append({"start": s, "end": end, "text": text[s:end],
                                    "type": _map_label(e["label"]), "gliner_label": e["label"],
                                    "score": round(float(e.get("score", 0)), 3), "source": "gliner"})
                return out
            print(f"    [ner] HTTP {r.status_code} attempt {attempt + 1}/{retries}", flush=True)
        except Exception as e:
            print(f"    [ner] {type(e).__name__} attempt {attempt + 1}/{retries}", flush=True)
        time.sleep(1.5 * (attempt + 1))
    print("    [ner] remote /extract unavailable -- continuing without GLiNER spans", flush=True)
    return []


def _gliner_spans(text, model_holder):
    if model_holder[0] == "unavailable":
        return []
    if model_holder[0] is None:
        try:
            import torch
            from gliner import GLiNER
            torch.set_num_threads(int(os.environ.get("C_THREADS", "24")))
            print(f"    loading GLiNER {GLINER_MODEL} ...", flush=True)
            model_holder[0] = GLiNER.from_pretrained(GLINER_MODEL)
            print("    GLiNER ready", flush=True)
        except Exception as e:
            print(f"    GLiNER UNAVAILABLE ({type(e).__name__}: {str(e)[:90]}) "
                  f"-- continuing without it", flush=True)
            model_holder[0] = "unavailable"
            return []
    out = []
    # GLiNER has a token limit; feed it sentence-sized windows with real offsets.
    for sent in sentences(text):
        seg = sent["text"]
        if not seg.strip():
            continue
        try:
            ents = model_holder[0].predict_entities(seg, GLINER_LABELS, threshold=GLINER_TH)
        except Exception:
            continue
        for e in ents:
            s = sent["start"] + e["start"]
            out.append({"start": s, "end": sent["start"] + e["end"],
                        "text": text[s:sent["start"] + e["end"]],
                        "type": _map_label(e["label"]), "gliner_label": e["label"],
                        "score": round(float(e.get("score", 0)), 3), "source": "gliner"})
    return out


_LABEL_MAP = {
    "person": "Person", "organization": "Organization", "company": "Organization",
    "government agency": "Organization", "country": "Location", "city or region": "Location",
    "military base or facility": "Facility", "product": "Product", "vehicle": "Platform",
    "aircraft": "Platform", "ship": "Platform", "weapon": "WeaponSystem", "missile": "WeaponSystem",
    "equipment": "Equipment", "material": "Material", "technology": "Technology",
    "program or project": "Program", "contract or tender": "Contract", "job title or role": "Role",
    "event": "Event", "document or standard": "Document", "date": "Date",
    "money amount": "Money", "measurement": "Measure",
}


def _map_label(lbl):
    return _LABEL_MAP.get(lbl, "Concept")


def chunks(text, size=CHUNK_CHARS):
    """Sentence-aligned chunks. Never split mid-sentence: a proposition needs its whole sentence."""
    out, cur, start = [], [], None
    for s in sentences(text):
        if start is None:
            start = s["start"]
        cur.append(s)
        if s["end"] - start >= size:
            out.append({"start": start, "end": s["end"], "text": text[start:s["end"]]})
            cur, start = [], None
    if start is not None:
        out.append({"start": start, "end": cur[-1]["end"], "text": text[start:cur[-1]["end"]]})
    return out


# A token is not a character, and how many characters it buys depends entirely on the script.
# Measured with qwen2.5:7b over the 52-document variety harvest, on 1,200 characters per language:
#
#     ja 1.22   ko 1.42   hi 1.52   ru 2.26   nl 2.35   ar 2.50   en 3.01   it 3.52   zh 3.57
#
# The budget below used to be `len(chunk) * 3.2`, which is a sensible token count in Latin script
# and about a THIRD of one in Hangul, kana or Devanagari. The consequence was measurable: replies
# were cut off and had to be salvaged on 72.7% of Hindi calls, 51.6% of Korean and 44.7% of
# Japanese, against 12.0% of Dutch -- with every reply landing at the same ~8,000 characters,
# which is the signature of a budget being hit rather than a model looping.
#
# This is the sixth time in this project that a character count has quietly become a language
# detector. The fix uses a signal that exists in every language: the script of the text itself.
# Devanagari, Hangul, kana AND Han are all expensive.
#
# CORRECTED 2026-08-25 against the real Qwen2.5 tokenizer. The previous comment claimed Han cost
# "3.57 characters per token in Chinese", so Chinese was given the LATIN budget and only counted as
# expensive when kana were present. Re-measuring with tokenizers.Tokenizer on the actual vocab --
# including on the very string the self-check below uses -- gives:
#
#     self-check zh string 1.82   ·   live corpus: zh 2.02  ja 1.46  ru 2.86  it 3.46  en 4.77
#
# 3.57 does not reproduce anywhere. Chinese needs ~1.6x the Latin budget and was getting 1.0x, so
# dense Chinese chunks truncated, were salvaged, and the residual pass then paid again to recover
# what the truncation dropped. Folding Han into _HUNGRY_ALWAYS deletes the kana branch entirely --
# a smaller diff than the special case it removes. Over-budgeting is free (num_predict is a
# CEILING, not a target, and _ollama now clamps it to the context); under-budgeting is not.
_HUNGRY_ALWAYS = re.compile("[ऀ-ॿ぀-ヿ가-힯ᄀ-ᇿ一-鿿㐀-䶿]")
_CPT_LATIN = 3.2        # characters per token, measured across en / it / fr / nl / ru
_CPT_HUNGRY = 1.4       # ...and across ja / ko / hi


def reply_budget(text, per_char=20.0, floor=1200, cap=24000):
    """Output-token budget for one chunk, scaled by what its script actually costs in tokens.

    TWO calibrations live here and they were fixed at different times for different reasons.

    The SCRIPT factor (_CPT_LATIN / cpt) corrects a token budget that had been computed from a
    character count -- Latin is exactly 1.0, so no language the original constant was tuned on can
    regress, and a mixed-script chunk lands between the two measured rates.

    The MAGNITUDE (per_char, cap) has been measured up twice on 2026-08-21, and the second time
    is the one that matters. It was 3.2 / 9000; a 708-character chunk needed ~2,430 tokens and got
    2,265, so half of all documents were salvaged rather than parsed. Raising it to 6.0 / 12000
    fixed that document and left 40% of documents still truncating -- because reply length is
    driven by DENSITY, not by input length. Every span carries a generated gloss AND an in-article
    sentence, so an entity-dense chunk expands about thirtyfold. Re-running one such chunk (734
    characters) at 4,404 / 13,212 / 32,000 gave:

        4,404  -> 17,142 chars, unparseable,  87 items
        13,212 -> 19,622 chars, PARSED,      104 items
        32,000 -> 22,369 chars, PARSED,      105 items

    The item count PLATEAUS at 105, which is what separates truncation from a repetition loop, and
    truncation was costing 17% of the items on that one chunk. The effective requirement was about
    18 output tokens per input character, so per_char is 20 with a cap that clears it. See
    probe_truncation.py, which runs that experiment on demand.

    A generous ceiling is close to free and a tight one is expensive: the three runs above took
    69.6s, 79.5s and 86.8s, and the extra time bought 21% more items.

    Why raising it is close to free: num_predict is a CEILING, not a target. Generation still stops
    at the stop token, and the three runs above took 106.6s, 110.7s and 108.3s. A budget the reply
    does not need costs nothing.

    Why there is still a cap: an unparseable reply is not always truncation. A repetition loop
    never emits a stop token either, so it runs to whatever ceiling it is given -- measured once at
    9,271 chars for npred=2,665, then 20,818 for 6,000, then 38,952 for 12,000, all unparseable.
    Against a loop a bigger budget only buys a longer loop, which is why `_ollama` must not
    escalate. The two failures are observationally identical on reply LENGTH; they differ in
    whether more budget ever finishes the job. The cap bounds what one loop can cost.
    """
    n = len(text)
    if not n:
        return floor
    # C_BUDGET=chars restores the old character-count behaviour. It exists so the A/B that
    # justified this function can be re-run by anyone without editing the formula back out --
    # a claim that a fix works should be reproducible from a flag, not from a git revert.
    if os.environ.get("C_BUDGET") == "chars":
        # Deliberately the ORIGINAL constants, not the arguments: this branch exists so the A/B
        # that justified the script factor can be re-run, and it is only a baseline if it stays
        # fixed while the live formula moves.
        return max(1200, min(6000, int(n * 3.2)))
    # Han is now inside _HUNGRY_ALWAYS, so the kana-share branch that used to decide whether Han
    # counted is gone: Chinese and Japanese are both expensive, and measurement says so.
    hungry = len(_HUNGRY_ALWAYS.findall(text))
    cpt = _CPT_LATIN * (1.0 - hungry / n) + _CPT_HUNGRY * (hungry / n)
    # The cap is applied to the LATIN-EQUIVALENT budget and the script factor is applied after,
    # not the other way round. Capping the final number silently cancels the multilingual fix
    # exactly where it is needed: a Devanagari chunk legitimately needs ~2.3x the tokens of the
    # same text in Latin script, so clipping both to one absolute number gives the hungry script
    # LESS effective budget than the cheap one. The self-check catches this -- hi fell to 1.30x
    # the Latin budget when it must be between 1.5x and 2.3x.
    base = min(int(cap), int(n * per_char))
    return max(floor, int(base * (_CPT_LATIN / cpt)))


def llm_pass(text, ch, audit):
    """The comprehension call for one chunk -> (spans, propositions)."""
    prompt = PROMPT.format(text=ch["text"], types=", ".join(TYPES), maxw=MAX_SPAN_WORDS)
    npred = reply_budget(ch["text"])
    d = _ollama(prompt, SPAN_SCHEMA, npred, audit=audit)
    if d is None:
        audit.append({"kind": "llm_call_failed", "chunk": [ch["start"], ch["end"]]})
        return [], []
    spans, used = [], set()
    win = (ch["start"], ch["end"])
    for s in d.get("spans") or []:
        raw = (s.get("text") or "").strip()
        # Refuse clause-length "spans" -- they buy coverage without explaining any single word.
        if len(raw) > MAX_SPAN_CHARS or len(raw.split()) > MAX_SPAN_WORDS:
            audit.append({"kind": "span_too_long", "text": raw[:90]})
            continue
        loc = locate(raw, text, win, used)
        if not loc:
            audit.append({"kind": "span_not_located", "text": raw[:80]})
            continue
        used.add(loc)
        gloss = (s.get("gloss") or "").strip()[:240]
        in_art = (s.get("in_article") or "").strip()[:240]
        # An in_article identical to the gloss carries no article-specific information. Treat it as
        # absent so the enrich pass has a chance to produce a real one.
        if in_art and in_art.lower() == gloss.lower():
            in_art = ""
        spans.append({"start": loc[0], "end": loc[1], "text": text[loc[0]:loc[1]],
                      "type": s.get("type") or "Other", "gloss": gloss,
                      "in_article": in_art, "source": "llm"})
    props = []
    for p in d.get("propositions") or []:
        subj = (p.get("subject") or "").strip()
        pred = (p.get("predicate") or "").strip()
        obj = (p.get("object") or "").strip()
        # A proposition with no object is a fragment: "Cubic -creates and delivers technology
        # solutions-> ()" is the predicate having swallowed the object. Reject rather than store.
        if not (subj and pred and obj):
            audit.append({"kind": "proposition_incomplete",
                          "triple": f"{subj[:40]} | {pred[:40]} | {obj[:40]}"})
            continue
        ev = locate(p.get("evidence", ""), text, win)
        if not ev:
            audit.append({"kind": "proposition_evidence_not_located",
                          "evidence": (p.get("evidence") or "")[:90]})
            continue
        props.append({"subject": subj[:160], "predicate": pred[:80], "object": obj[:160],
                      "ev_fragment": bool(evidence_is_fragment(
                          text[ev[0]:ev[1]],
                          any(sp["type"] in ("Action", "Event")
                              and sp["start"] >= ev[0] and sp["end"] <= ev[1]
                              for sp in spans))),
                      "time": (p.get("time") or "")[:80], "place": (p.get("place") or "")[:80],
                      "polarity": p.get("polarity") or "positive",
                      "modality": p.get("modality") or "asserted",
                      "evidence": {"start": ev[0], "end": ev[1], "quote": text[ev[0]:ev[1]]}})
    return spans, props


RESIDUAL_SCHEMA = {
    "type": "object",
    "properties": {"spans": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"},
                       "type": {"type": "string", "enum": TYPES},
                       "gloss": {"type": "string"}, "in_article": {"type": "string"}},
        "required": ["text", "type", "gloss", "in_article"]}}},
    "required": ["spans"]}

RESIDUAL_PROMPT = """These words from an article were not yet explained. For EACH one, say what it is.

CONTEXT (the article sentence each came from is shown):
{context}

WORDS TO EXPLAIN:
{words}

Return JSON {{"spans":[...]}} with one entry per word you can explain:
  text       = the word, copied EXACTLY as given
  type       = one of: {types}
  gloss      = what the word means in general
  in_article = what it means HERE in this article
Skip a word only if it is pure grammar or meaningless in isolation."""


def residual_pass(text, tokens, spans, audit, rounds=2, max_calls=10):
    """Offer every still-uncovered content token back to the model, with its sentence for context.

    This is what makes coverage a TARGET rather than a statistic: without it the pipeline measures
    its own misses and does nothing about them.

    Three properties, each of which was worth points:

    ROUNDS. Running once cannot recover a word whose meaning only becomes askable after its
    neighbours are explained. Up to `rounds` passes, stopping the moment a round stops paying --
    a round that adds nothing means the remainder is genuinely unexplainable by this model, and
    another identical question will not change that.

    MEASURED on the first three documents of the 35-language run, and it trimmed this setting:
    round 1 gained 144/181/60 of 148/195/61 missing tokens; round 2 gained 2/0/1; round 3 gained
    0. So `rounds` is 2, not the 3 a sibling implementation uses. Nearly all of the value that
    looked like "rounds" was really the per-surface fix below -- 144 tokens gained across only 126
    distinct surfaces is 18 tokens the old one-per-surface code stranded.

    ONE ASK PER SURFACE, APPLIED TO EVERY OCCURRENCE. The previous version keyed the accept map by
    surface text, so a word occurring five times was asked about once and covered once; the other
    four stayed holes no matter how many rounds ran. Deduping the QUESTION is right and saves
    tokens. Covering one occurrence of the answer was a bug.

    RANKED BY WHAT THEY BUY. A surface with five uncovered occurrences is worth five times one with
    a single occurrence, for the same question. The budget is spent in that order.
    """
    sents = sentences(text)

    def sent_of(tok):
        for sn in sents:
            if sn["start"] <= tok["start"] < sn["end"]:
                return sn["text"][:200]
        return ""

    out, used = [], {(sp["start"], sp["end"]) for sp in spans}
    calls = 0
    for rnd in range(rounds):
        # Recompute coverage against everything found SO FAR, including this pass's own output --
        # otherwise round 2 re-asks about words round 1 already explained.
        coverage(tokens, spans + out)
        missing = [t for t in tokens if t["cls"] == "content" and not t.get("covered")]
        if not missing or calls >= max_calls:
            break

        by_surface = {}
        for t in missing:
            by_surface.setdefault(t["text"], []).append(t)
        # Most occurrences first, then longest: both are proxies for how much one answer buys.
        order = sorted(by_surface, key=lambda w: (-len(by_surface[w]), -len(w)))

        gained = 0
        for i in range(0, len(order), 40):
            if calls >= max_calls:
                break
            batch = order[i:i + 40]
            reps = [by_surface[w][0] for w in batch]
            ctx = "\n".join(dict.fromkeys(sent_of(t) for t in reps if sent_of(t)))[:2000]
            words = "\n".join("- %s" % w for w in batch)
            d = _ollama(RESIDUAL_PROMPT.format(context=ctx, words=words, types=", ".join(TYPES)),
                        RESIDUAL_SCHEMA, max(900, 120 * len(batch)), audit=audit)
            calls += 1
            if d is None:
                audit.append({"kind": "residual_call_failed", "n_words": len(batch)})
                continue
            # Only accept text matching a token actually asked about -- otherwise the model
            # explains a word it invented and coverage rises against nothing.
            asked = set(batch)
            for sp in d.get("spans") or []:
                w = (sp.get("text") or "").strip()
                if w not in asked:
                    audit.append({"kind": "residual_word_not_asked", "text": w[:60]})
                    continue
                for tok in by_surface[w]:          # every occurrence, not just the first
                    key = (tok["start"], tok["end"])
                    if key in used:
                        continue
                    used.add(key)
                    gained += 1
                    out.append({"start": tok["start"], "end": tok["end"], "text": tok["text"],
                                "type": sp.get("type") or "Other",
                                "gloss": (sp.get("gloss") or "")[:240],
                                "in_article": (sp.get("in_article") or "")[:240],
                                "source": "residual"})
        audit.append({"kind": "residual_round",
                      "detail": {"round": rnd + 1, "missing": len(missing),
                                 "surfaces": len(order), "gained": gained, "calls": calls}})
        if gained == 0:
            break                                  # a round that pays nothing will not pay next time
    return out


ENRICH_PROMPT = """For each phrase below, taken from an article, give its meaning.

ARTICLE CONTEXT:
{context}

PHRASES (each shown with the sentence it appears in):
{items}

Return JSON {{"spans":[...]}}, one entry per phrase:
  text       = the phrase, copied EXACTLY as given
  type       = one of: {types}
  gloss      = the general dictionary meaning, ignoring this article
  in_article = what it actually refers to HERE in this article — MUST differ from gloss
Give an entry for every phrase."""


def enrich_pass(text, spans, title, audit):
    """Fill gloss / in_article for spans that have none.

    GLiNER and the regex generator produce offsets and a type but no meaning. In the first run that
    left 91 of 235 spans highlighted-but-unexplained: they counted toward coverage while explaining
    nothing, which is precisely the way a coverage score can be gamed. A span without a meaning is
    not comprehension, so every one of them is sent back for a gloss.
    """
    need = [s for s in spans if not s.get("gloss") or not s.get("in_article")]
    if not need:
        return 0
    sents = sentences(text)

    def sent_of(sp):
        return next((x["text"][:180] for x in sents if x["start"] <= sp["start"] < x["end"]), "")

    filled = 0
    # ONE ASK PER SURFACE, APPLIED TO EVERY OCCURRENCE -- the rule residual_pass already documents
    # and this pass never got. `need` holds SPANS, so a word occurring 8 times contributed 8
    # identical prompt lines. Measured on the 600-doc corpus: 36,596 entries over 28,767 distinct
    # surfaces (21.4% duplicate lines), and 1,752 batches sent where 1,428 do -- 324 whole
    # generations wasted, 18.5% of this pass. Generation is the entire cost of a document, so those
    # are real hours.
    #
    # Output cannot change: the fills below only write when the field is still empty, so the FIRST
    # answer for a surface already won and later duplicates were already no-ops. Deduping keeps the
    # first occurrence -- the one whose sentence decided the answer for all of them anyway. by_text
    # is now built over all of `need` rather than per batch, so one answer reaches every occurrence
    # instead of only those that landed in the same batch.
    by_text = {}
    for s in need:
        by_text.setdefault(s["text"].strip(), []).append(s)
    asks = [occurrences[0] for occurrences in by_text.values()]
    for i in range(0, len(asks), 25):
        batch = asks[i:i + 25]
        items = "\n".join(f'- "{s["text"]}"  (in: {sent_of(s)})' for s in batch)
        d = _ollama(ENRICH_PROMPT.format(context=title[:200], items=items[:4000],
                                         types=", ".join(TYPES)),
                    RESIDUAL_SCHEMA, max(900, 150 * len(batch)), audit=audit)
        if d is None:
            audit.append({"kind": "enrich_call_failed", "n": len(batch)})
            continue
        for e in d.get("spans") or []:
            targets = by_text.get((e.get("text") or "").strip())
            if not targets:
                continue
            g = (e.get("gloss") or "").strip()[:240]
            a = (e.get("in_article") or "").strip()[:240]
            if a.lower() == g.lower():
                a = ""
            for t in targets:
                if not t.get("gloss") and g:
                    t["gloss"] = g
                if not t.get("in_article") and a:
                    t["in_article"] = a
                if e.get("type") and t.get("source") in ("gliner", "regex"):
                    t.setdefault("type_ner", t["type"])
                    t["type"] = e["type"]
            filled += 1
    return filled


_FINITE_HINT = re.compile(
    r"(?i)\b(is|are|was|were|has|have|had|will|shall|can|does|did|says?|said|announced|signed|"
    r"delivered|provides?|includes?|supports?|develops?|operates?|awarded|selected|"
    r"ist|sind|war|waren|hat|haben|wird|werden|"
    r"est|sont|a\b|ont|sera|seront|"
    r"è|sono|era|erano|ha|hanno|"
    r"es|son|tiene|tienen|fue|"
    r"был|была|было|есть|будет)\b")


# Layout marks that say "this is a list / table row / nav strip", in any language. Deliberately
# NOT the guillemets: « » are QUOTE marks in Ukrainian, Russian, German and French, and
# counting them as separators flagged every sentence containing «Mriya» as a nav bar.
_BULLET_CHARS = "•●▪◦‣⁃·*+\\-–—>"
_BULLET = re.compile(r"^[\s ]*[" + _BULLET_CHARS + r"][\s ]")
_BULLETS = re.compile(r"(?m)^[\s ]*[" + _BULLET_CHARS + r"][\s ]")
_URLISH = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\S+@\S+\.\w+")
_NAVSEP = re.compile(r"[|·•]|(?<=\w)/(?=\w)")
_LABELVAL = re.compile(r"^[^.!?\n]{1,45}[:：][\s ]*\S")
# A real sentence end, not the dot inside cubic.com: terminal punctuation must be FOLLOWED by
# whitespace, a closing quote/bracket, or the end of the quote.
_TERMINAL = re.compile(r"[.!?…][\s\"'”»)\]]|[.!?…]$")


def evidence_is_fragment(quote, has_predicate=None):
    """Is this evidence a SENTENCE, or a cell out of a spec table?

    This is not a quality dodge, it is a real distinction the data forced. On a French firearms
    spec page every "sentence" is a label/value pair -- `Couleur/Finition du Canon Noir` -- and a
    14b judge correctly rules that such a fragment does not STATE "the barrel finish is black":
    nothing in it asserts anything, it is a table cell. Those pages scored 0/9 on entailment while
    prose pages scored 73-100%.

    The fact is still real and still worth storing; it is an attribute read off a table rather than
    a proposition stated in prose, and conflating the two makes the entailment number meaningless
    for both. So it is flagged, not dropped.

    `has_predicate` -- does an Action/Event span fall inside the evidence region? The first version
    of this test had only `_FINITE_HINT`, a closed list of auxiliaries, so it behaved as an
    English-only test: 2% of English propositions were flagged against 51% of French and 39% of
    German, because German `erhielt` and French `notifie` are lexical verbs no auxiliary list
    contains. Our own extraction already marks verbs in every language, so use it. Measured over
    the 30-document store it separates 87%/30%, where the obvious alternative -- function-word
    density -- separated 31%/29% and was discarded.

    That does make the flag depend on extraction quality: a verb the finder missed can turn prose
    into a "fragment". So it is a hint ORed with the text tests, never the sole evidence, and
    callers without span context omit it and get the text-only behaviour.

    Returns the reason as a truthy string, "" for prose.
    """
    q = (quote or "").strip()
    if len(q) < 40:
        return "short"
    # several bullets crammed into one quote is a list, whatever the items happen to say
    if len(_BULLETS.findall(q)) >= 2:
        return "bullet-list"
    # ONE leading bullet is not enough: a Saab results release bullets whole sentences
    # ("Nettolikviditeten uppgick till MSEK 690 ..."), so strip the mark and judge what follows.
    body = _BULLET.sub("", q).strip()
    if _LABELVAL.match(body) and not _TERMINAL.search(body):
        return "label:value"
    if len(_NAVSEP.findall(_URLISH.sub(" ", body))) >= 3:
        return "nav-run"
    if has_predicate or _TERMINAL.search(body) or _FINITE_HINT.search(body):
        return ""
    return "no-predicate"


def dedupe_props(props):
    """Collapse propositions repeated across overlapping chunks. Keyed on the triple, lowercased —
    the first run stored 'Cubic creates and delivers technology solutions' twice."""
    seen, out = set(), []
    for p in props:
        k = (p["subject"].lower(), p["predicate"].lower(), p["object"].lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def merge(spans):
    """Union the generators. Longest span wins an overlap; a shorter one nested inside a longer one
    is kept only if it adds a different type, so "Britten-Norman BN-2" does not erase "BN-2"."""
    ranked = sorted(spans, key=lambda s: (-(s["end"] - s["start"]), s["start"]))
    kept = []
    for s in ranked:
        clash = [k for k in kept if s["start"] < k["end"] and s["end"] > k["start"]]
        if not clash:
            kept.append(s); continue
        exact = [k for k in clash if k["start"] == s["start"] and k["end"] == s["end"]]
        if exact:
            # same span from two generators: keep the richer record
            k = exact[0]
            if not k.get("gloss") and s.get("gloss"):
                k.update(gloss=s["gloss"], in_article=s.get("in_article", ""),
                         type=s.get("type", k["type"]))
            k["source"] = "+".join(sorted(set(k["source"].split("+")) | {s["source"]}))
            continue
        if all(s["type"] != c["type"] for c in clash) and (s["end"] - s["start"]) >= 3:
            kept.append(s)
    return sorted(kept, key=lambda s: (s["start"], -(s["end"] - s["start"])))


def comprehend(doc, do_residual=True, verbose=True):
    """Full pipeline for one document -> the comprehension record."""
    text = doc["main_text"]
    # Normalise to NFC ONCE, before any offset exists. Models emit NFC; documents arrive NFD from
    # macOS-origin scrapes, some feeds, and DB round-trips. Without this, locate() fails on every
    # accented span (French/German/Cyrillic) and drops it. Lone surrogates from surrogateescape
    # DB decoding would raise on json posting -- replace them. NFC is NOT length-preserving, so it
    # must be done here (before offsets are minted) and never after, or text[start:end] breaks.
    if text:
        text = unicodedata.normalize("NFC", text.encode("utf-8", "replace").decode("utf-8"))
    # Detect from the text. The corpus label is wrong often enough to matter -- a French job
    # posting labelled `en` had its French grammar counted as unextracted content words.
    lang = detect_lang(text, doc.get("language"))
    t0 = time.time()
    toks = classify(tokenize(text), lang)
    sents = sentences(text)
    audit = []

    spans = values.find(text)
    for s in spans:
        # values.py names its own categories (money, date, measurement...). Left as-is they land in
        # the store beside the capitalised vocabulary and SPLIT one concept across two type names —
        # 22 `money` next to 14 `Money`. Any consumer grouping by type then silently sees half.
        s["type"] = VALUE_TYPE.get(s["type"], s["type"])
    if verbose:
        print(f"    values   {len(spans)}", flush=True)
    g = gliner_spans(text)
    if verbose:
        print(f"    gliner   {len(g)}", flush=True)
    spans += g

    llm_spans, props = [], []
    chs = chunks(text)
    for i, ch in enumerate(chs):
        s, p = llm_pass(text, ch, audit)
        llm_spans += s; props += p
        if verbose:
            print(f"    chunk {i + 1}/{len(chs)}  spans+{len(s)}  props+{len(p)}", flush=True)
    spans += llm_spans

    spans = merge(spans)
    coverage(toks, spans)                      # marks tok["covered"], needed by residual_pass
    if do_residual:
        r = residual_pass(text, toks, spans, audit)
        if verbose:
            print(f"    residual {len(r)}", flush=True)
        spans = merge(spans + r)

    # --- lexicon retyping ---------------------------------------------------------------------
    # Runs over spans that ALREADY EXIST with exact offsets, so it can only change a label, never
    # add or drop a span -- it cannot touch recall. Label accuracy was the measured weakness
    # (80.9% vs the benchmark owner's 86.0%) and the confusions were concentrated enough to name.
    n_retyped = 0
    for s_ in spans:
        new, why = lexicon.retype(s_["text"], s_.get("type"))
        if new and new != s_.get("type"):
            s_["type_before_lexicon"] = s_.get("type")
            s_["type"] = new
            s_["lexicon"] = why
            n_retyped += 1
    if verbose:
        print(f"    lexicon  {n_retyped} spans retyped", flush=True)

    n_filled = enrich_pass(text, spans, doc.get("title", ""), audit)
    # A second attempt for the stragglers. The model must echo `text` byte-exactly to be matched,
    # and a handful never are on the first pass (a smaller batch makes it echo them reliably).
    still = [s for s in spans if not s.get("gloss")]
    if still:
        n_filled += enrich_pass(text, still, doc.get("title", ""), audit)
    if verbose:
        left = sum(1 for s in spans if not s.get("gloss"))
        print(f"    enrich   {n_filled} span groups given a meaning "
              f"({left} still without one)", flush=True)
    props = dedupe_props(props)

    cov = coverage(toks, spans)
    for i, s in enumerate(spans):
        s["id"] = f"s{i}"
        s["sent"] = next((x["i"] for x in sents if x["start"] <= s["start"] < x["end"]), None)
    # Comprehension quality, kept beside coverage so a high score cannot hide empty annotations.
    explained = sum(1 for s in spans if s.get("gloss"))
    contextual = sum(1 for s in spans if s.get("in_article"))
    # "What does it refer to HERE" is only a meaningful question for REFERENTIAL spans. For a bare
    # verb ("ist", "dice", "hat") the article-specific meaning genuinely is the dictionary meaning,
    # the model rightly returned the same string, and blanking it made German and Italian look 17
    # points worse than English on a question that does not apply to them. Scored where it applies.
    ref = [s for s in spans if s.get("type") in REFERENTIAL]
    ref_ctx = sum(1 for s in ref if s.get("in_article"))
    cov["spans"] = len(spans)
    cov["spans_with_gloss"] = explained
    cov["spans_with_in_article"] = contextual
    cov["pct_spans_explained"] = round(100.0 * explained / len(spans), 1) if spans else 0.0
    cov["pct_spans_contextual"] = round(100.0 * contextual / len(spans), 1) if spans else 0.0
    cov["referential_spans"] = len(ref)
    cov["pct_referential_contextual"] = round(100.0 * ref_ctx / len(ref), 1) if ref else 0.0
    return {
        "document_id": doc["document_id"], "url": doc.get("url", ""),
        "source_id": doc.get("source_id", ""), "language": lang,
        "language_declared": doc.get("language", ""),
        "title": doc.get("title", ""), "text": text,
        # Carry the crawler's proven publication date straight through. store_pg lands it in
        # extracted.document.meta, where the serving date-gate needs it: without it the gate falls
        # back to misleading in-body dates and rejects recent docs as "too old"/"no provable date".
        "published_at": doc.get("published_at"),
        "n_sentences": len(sents), "sentences": sents,
        "spans": spans, "propositions": props, "coverage": cov, "audit": audit,
        "elapsed_s": round(time.time() - t0, 1),
        "model": MODEL, "gliner": GLINER_MODEL,
    }


def _demo_residual():
    """The residual pass must cover EVERY occurrence of a surface it asked about, and must stop
    asking once a round stops paying.

    The bug this pins: the accept map was keyed by surface text, so a word occurring five times was
    asked about once and covered once. The other four stayed holes through every later round, and
    no amount of re-running could reach them. Nothing failed; coverage was simply lower for ever.
    """
    import segment as _seg

    text = "Bharat Forge sells radar. Radar matters. The radar is new."
    toks = _seg.classify(_seg.tokenize(text), "en")
    # Pretend only "Bharat Forge" was found, leaving three occurrences of radar/Radar uncovered.
    spans = [{"start": 0, "end": 12, "text": "Bharat Forge", "type": "Organization"}]
    _seg.coverage(toks, spans)

    asked = []
    real_ollama = globals()["_ollama"]

    def fake(prompt, schema, npred, model=None, retries=3, num_ctx=None, audit=None):
        # Record the distinct surfaces asked about, and answer for every one of them.
        words = [l[2:].strip() for l in prompt.splitlines() if l.startswith("- ")]
        asked.append(list(words))
        return {"spans": [{"text": w, "type": "Equipment", "gloss": "a sensor",
                           "in_article": "the sensor in this article"} for w in words]}

    globals()["_ollama"] = fake
    try:
        audit = []
        got = residual_pass(text, toks, spans, audit)
    finally:
        globals()["_ollama"] = real_ollama

    # Every uncovered occurrence must now carry a span, not just the first of each surface.
    lowered = [g["text"].lower() for g in got]
    assert lowered.count("radar") == 3, \
        "asked once per surface but covered %d of 3 occurrences: %r" % (lowered.count("radar"), got)
    # ...and each one must sit at its OWN offsets, or two spans claim the same characters.
    assert len({(g["start"], g["end"]) for g in got}) == len(got), got
    for g in got:
        assert text[g["start"]:g["end"]] == g["text"], "offset contract broken by residual"

    # The QUESTION is deduped even though the answer is applied broadly -- asking three times for
    # one word is the token waste the surface map was introduced to avoid.
    assert asked and len(asked[0]) == len(set(asked[0])), asked

    # A round that gains nothing must end the loop rather than re-asking an identical question.
    rounds = [a for a in audit if a.get("kind") == "residual_round"]
    assert rounds, "each round must record what it cost and what it bought"
    assert len(rounds) <= 3
    # The loop must end for a REASON, and both reasons are legitimate: a round that gained
    # nothing, or nothing left to gain. It must never simply run out of rounds with work pending.
    import segment as _s2
    _s2.coverage(toks, spans + got)
    still = [t for t in toks if t["cls"] == "content" and not t.get("covered")]
    assert (not still) or rounds[-1]["detail"]["gained"] == 0 or len(rounds) == 3, (rounds, still)

    # An answer for a word never asked about must be refused, or coverage rises against nothing.
    def liar(prompt, schema, npred, model=None, retries=3, num_ctx=None, audit=None):
        return {"spans": [{"text": "invented", "type": "Other", "gloss": "x", "in_article": "y"}]}

    globals()["_ollama"] = liar
    try:
        toks2 = _seg.classify(_seg.tokenize(text), "en")
        _seg.coverage(toks2, spans)
        audit2 = []
        assert residual_pass(text, toks2, spans, audit2) == [], \
            "a word the model invented must never become a span"
        assert any(a.get("kind") == "residual_word_not_asked" for a in audit2)
    finally:
        globals()["_ollama"] = real_ollama


def _demo():
    _demo_residual()
    txt = ("Cubic Corp. and 4C Strategies signed a $4.5 million deal on 12 March 2026.\n"
           "The padded hat is gray.")
    toks = classify(tokenize(txt), "en")
    # locate() is the anti-hallucination primitive: verbatim only
    assert locate("4C Strategies", txt) == (txt.index("4C"), txt.index("4C") + 13)
    assert locate("4D Strategies", txt) is None, "invented text must not locate"
    # whitespace re-flow must still locate (the model re-wraps newlines)
    assert locate("deal on 12  March 2026", txt) is not None
    # --- punctuation folding: the model writes straight quotes where the article has curly ones.
    # This single mismatch discarded 12 of 34 propositions on a French document.
    curly = "Diplômé(e) d’une formation d’ingénieur, vous justifiez de l’expérience."
    hit = locate("Diplômé(e) d'une formation d'ingénieur", curly)
    assert hit is not None, "straight-vs-curly apostrophe must still locate"
    assert curly[hit[0]:hit[1]].startswith("Diplômé(e) d’une"), curly[hit[0]:hit[1]]
    q = 'He said “Exonaut will support the plan” yesterday.'
    assert locate('“Exonaut will support the plan”'.replace("“", '"').replace("”", '"'), q)
    assert locate("A—B", "the A–B link") is not None       # em vs en dash
    # folding must be length-preserving, or every offset after it silently shifts
    for s in [curly, q, "a–b “c” d’e", "x y"]:
        assert len(fold(s)) == len(s), s
    # a long evidence quote whose tail was paraphrased still anchors on its head
    art = ("The CCTEMS will enable training for critical decision-making and real time "
           "behavioral response in a controlled environment. Next sentence.")
    got = locate("The CCTEMS will enable training for critical decision-making and something else "
                 "entirely that was never written", art)
    assert got is not None and art[got[0]:got[1]].startswith("The CCTEMS will enable"), got
    # ...but a short invented phrase must still be refused
    assert locate("totally invented", art) is None
    # merge: longest wins, but a nested span of a DIFFERENT type survives
    m = merge([{"start": 0, "end": 11, "text": "Cubic Corp.", "type": "Organization", "source": "a"},
               {"start": 0, "end": 5, "text": "Cubic", "type": "Organization", "source": "b"}])
    assert len(m) == 1 and m[0]["end"] == 11, m
    m2 = merge([{"start": 0, "end": 20, "text": "x", "type": "Event", "source": "a"},
                {"start": 5, "end": 10, "text": "y", "type": "Money", "source": "b"}])
    assert len(m2) == 2, m2
    # identical span from two generators merges into one record carrying both sources
    m3 = merge([{"start": 0, "end": 5, "text": "Cubic", "type": "Organization", "source": "gliner"},
                {"start": 0, "end": 5, "text": "Cubic", "type": "Organization", "source": "llm",
                 "gloss": "a company"}])
    assert len(m3) == 1 and m3[0]["source"] == "gliner+llm" and m3[0]["gloss"] == "a company", m3
    # chunks never split a sentence
    for c in chunks(txt, 10):
        assert c["text"].strip(), c
    assert "".join(c["text"] for c in chunks(txt, 10)).replace(" ", "").replace("\n", "") \
        .startswith("CubicCorp")
    # coverage responds to annotation, and content/function are separated
    c0 = coverage(toks, [])
    assert c0["pct_content"] == 0.0 and c0["content_tokens"] > 0
    # every type values.py can emit must translate into the canonical vocabulary, or the store ends
    # up with `money` beside `Money` and a consumer grouping by type sees half the rows
    import values as _v
    assert {t for t, _ in _v.PATTERNS} <= set(VALUE_TYPE), \
        {t for t, _ in _v.PATTERNS} - set(VALUE_TYPE)
    assert set(VALUE_TYPE.values()) <= set(TYPES)

    # --- salvage: a reply cut off mid-array must still yield its complete items ---------------
    trunc = ('{"spans": [{"text": "Cubic", "type": "Organization", "gloss": "a firm", '
             '"in_article": "the subject"}, {"text": "hat", "type": "Product", "gloss": "headwear",'
             ' "in_article": "the item"}, {"text": "belt", "type": "Prod')
    sal = _salvage(trunc)
    assert sal and len(sal["spans"]) == 2, sal
    assert sal["spans"][1]["text"] == "hat"
    # a brace inside a string must not confuse the depth counter
    weird = '{"spans": [{"text": "a{b}c", "type": "Other", "gloss": "x", "in_article": "y"}]}'
    assert len(_salvage(weird)["spans"]) == 1
    # an escaped quote must not end the string early
    esc = '{"spans": [{"text": "say \\"hi\\"", "type": "Other", "gloss": "x", "in_article": "y"}]}'
    assert len(_salvage(esc)["spans"]) == 1, _salvage(esc)
    assert _salvage("total garbage, no json here") is None

    # --- evidence fragment vs sentence: the distinction the spec-table pages forced -----------
    assert evidence_is_fragment("Couleur/Finition du Canon Noir")           # a table cell
    assert evidence_is_fragment("Poids 1230 g")
    assert evidence_is_fragment("Aufgaben:")
    assert not evidence_is_fragment(
        "Airbus opened a new distribution centre in Hamburg to serve its customers.")
    assert not evidence_is_fragment(
        "Die Werft hat das Schiff im Jahr 2026 an den Kunden ausgeliefert worden ist")
    # a long clause with a finite verb but no full stop is still a sentence, not a fragment
    assert not evidence_is_fragment(
        "the brigade is responsible for surface transportation across the theatre")
    # the Action/Event span rescues a lexical verb no auxiliary list contains -- this is the whole
    # point of the has_predicate argument, and without it these read as English-only failures
    de = "Die Werft erhielt den Auftrag fuer zwei weitere Fregatten der Klasse 126"
    assert evidence_is_fragment(de) == "no-predicate", "text alone cannot see 'erhielt'"
    assert not evidence_is_fragment(de, has_predicate=True)
    # ... but it never overrides a positive layout marker, or a bulleted price list would pass
    assert evidence_is_fragment(
        "- on sale\n- on sale\n- VINTAGE LOGO T-SHIRT  Was $24.99  As low as $14.99",
        has_predicate=True) == "bullet-list"
    assert evidence_is_fragment(
        "For further information please contact: Fenna Maynard, PR Coordinator",
        has_predicate=True) == "label:value"
    # ONE bullet on a real sentence is still a sentence (Saab bullets its results release)
    assert not evidence_is_fragment(
        "• Nettolikviditeten uppgick till MSEK 690 (-2 354) vid periodens utgang.")
    # a dot inside a hostname is not a sentence end -- this contact block used to pass as prose
    assert evidence_is_fragment(
        "Cathy Weis\nCubic Defence Australia\nCathy.Weis@cubic.com") == "no-predicate"
    # guillemets are QUOTE marks, not nav separators: this Ukrainian sentence must stay prose
    assert not evidence_is_fragment(
        "«Мрія» стартувала "
        "з аеродрому на "
        "Байконурі у 1989 році.",
        has_predicate=True)

    # ---- the reply budget must not be a character count wearing a token count's name.
    latin = "The company announced a new contract for the defence ministry today. " * 10
    assert reply_budget(latin) == int(len(latin) * 20.0), \
        "Latin script must be byte-for-byte unchanged, or this is a regression not a fix"

    # 1,200 characters of each script, at the rates measured on the variety harvest
    hi = "भारत डायनामिक्स ने नई मिसाइल का परीक्षण किया। " * 20
    ko = "한화시스템은 새로운 레이더를 공개했습니다. " * 26
    ja = "三菱重工業は新型艦艇の開発を発表しました。" * 28
    # Real prose in these scripts still contains spaces, digits and punctuation, all of which
    # tokenise cheaply -- so the blend never reaches the pure-script ceiling of 3.2/1.4 = 2.29x,
    # and it should not. What must hold is that the budget rises substantially and stays bounded.
    for name, s in (("hi", hi), ("ko", ko), ("ja", ja)):
        ratio = reply_budget(s) / max(1, int(len(s) * 20.0))
        assert 1.5 < ratio <= 2.3, \
            "%s should get well over the Latin budget but under the pure-script ceiling, got %.2fx" % (
                name, ratio)

    # a mixed chunk lands between the two rates, rather than snapping to either
    mixed = latin[:600] + hi[:600]
    r_mixed = reply_budget(mixed) / max(1, int(len(mixed) * 20.0))
    assert 1.0 < r_mixed < 2.3, "a mixed-script chunk must be blended, got %.2fx" % r_mixed

    # Chinese is EXPENSIVE, not cheap. This assertion used to demand the opposite -- it pinned the
    # Latin budget on the strength of a "3.57 chars/token" figure that does not reproduce. Measured
    # on THIS EXACT STRING with the real Qwen2.5 tokenizer: 1.82 chars/token. On the live corpus:
    # zh 2.02, against en 4.77. A test that asserts a wrong number keeps the bug alive, so it is
    # inverted here rather than deleted -- the regression it now guards is the real one.
    zh = "中国船舶集团发布了新型护卫舰的详细规格。" * 30
    r_zh = reply_budget(zh) / max(1, int(len(zh) * 20.0))
    assert r_zh > 1.5, "Chinese must be budgeted as a hungry script, got %.2fx" % r_zh

    # The read timeout must cover what reply_budget is allowed to ask for. The pair used to be
    # incoherent: a 24,000-token budget against a fixed 420s read needs 57.1 tok/s, and the
    # fastest node measured is the farm at 53.5. These assertions fail if either side drifts back
    # out of agreement -- the budget growing, or the timeout being pinned to a constant again.
    # keep_alive must never leave here as a bare numeric string -- Ollama 400s on it.
    assert _keep_alive_value("-1") == -1 and isinstance(_keep_alive_value("-1"), int), \
        "a numeric keep_alive must be sent as an integer, not a string"
    assert _keep_alive_value("24h") == "24h", "a duration string must pass through unchanged"
    assert not isinstance(_KEEP_ALIVE, str) or not _KEEP_ALIVE.lstrip("-").isdigit(), \
        "C_KEEP_ALIVE=%r would be rejected by Ollama with HTTP 400" % (_KEEP_ALIVE,)

    assert _read_timeout(100).read == _TIMEOUT_FLOOR, \
        "a small request must still get the old floor, never less"
    assert _read_timeout(10 ** 9).read == _TIMEOUT_CEIL, \
        "a runaway must stay bounded"
    _big = _read_timeout(24000).read
    assert _big > _TIMEOUT_FLOOR, \
        "the largest legal budget must get more than the old fixed 420s, got %.0fs" % _big
    # The promise is the DENSE reply, not the cap -- see _TIMEOUT_CEIL. If this fails, either the
    # measured dense requirement moved or the ceiling stopped being derived from it.
    assert _big >= _DENSE_TOKENS / _TOK_S, \
        "the timeout must cover the measured dense reply at this node's rate"

    assert reply_budget("") == 1200 and reply_budget("x" * 100000) == 24000, \
        "floor and the Latin-equivalent cap hold"
    # A hungry script may exceed the raw cap, because the cap bounds the Latin
    # equivalent and the same text costs more tokens in Devanagari. What it may NOT do
    # is come out below the Latin budget for the same text.
    _hi_long = "\u0915\u0930\u0928\u093e " * 4000
    assert reply_budget(_hi_long) > 24000, \
        "capping after the script factor cancels the multilingual fix"
    # The magnitude fix must actually clear the measured requirement: a 708-character Latin chunk
    # needed about 2,430 output tokens and used to be given 2,265. If this ever drops back below
    # that, half the corpus silently returns to being salvaged instead of parsed.
    assert reply_budget("x" * 708) > 2430, "the budget must clear the first measured requirement"
    # ...and the SECOND, larger one: a 734-character chunk parsed only at 13,212
    # tokens. This is the assertion that would have caught 6.0/12000 being still too
    # small -- it was raised once, tested on one document, and shipped.
    assert reply_budget("x" * 734) >= 13212, "the budget must clear the dense-chunk requirement"
    # ...and C_BUDGET=chars must still reproduce the OLD number, or the A/B baseline has moved.
    import os as _os
    _os.environ["C_BUDGET"] = "chars"
    try:
        assert reply_budget("x" * 708) == int(708 * 3.2), "the chars baseline must not move"
    finally:
        del _os.environ["C_BUDGET"]
    # enrich_pass asks ONCE PER SURFACE, and the answer reaches EVERY occurrence. The pass used
    # to slice `need` (a span list) directly, so a word appearing 10 times cost 10 identical
    # prompt lines. Measured on the 600-doc corpus that was 21.4% duplicate lines and 324 wasted
    # generations. Generation is ~100% of a document's runtime, so this is hours, not micros.
    _calls = []

    def _fake_llm(prompt, schema, npred, audit=None, **kw):
        _calls.append(prompt)
        return {"spans": [{"text": t, "gloss": "g-" + t} for t in ("alpha", "beta", "gamma")]}

    _real_llm, globals()["_ollama"] = _ollama, _fake_llm
    try:
        _spans = [{"text": t, "start": 0, "end": len(t)}
                  for t in ("alpha", "beta", "gamma") for _ in range(10)]
        _filled = enrich_pass("alpha beta gamma", _spans, "t", [])
    finally:
        globals()["_ollama"] = _real_llm
    # 30 spans, 3 distinct surfaces: one batch of 3, not two batches of 25+5.
    assert len(_calls) == 1, "enrich_pass must ask once per SURFACE, got %d calls" % len(_calls)
    # count the item line, not the bare word: sent_of() echoes the surrounding sentence, which
    # legitimately contains the word again.
    assert _calls[0].count('- "alpha"') == 1, "a surface must be ASKED about once"
    # ...and every occurrence still gets the answer, including ones a naive dedupe would strand.
    assert all(sp.get("gloss") == "g-" + sp["text"] for sp in _spans), \
        "deduping the question must not drop occurrences from the fill"
    assert _filled == 3
    # C_FORMAT=tsv must produce EXACTLY the shape json.loads produced, or every caller breaks.
    _reply = ("spans\tMBDA\tOrganization\ta missile maker\tthe supplier here\n"
              "spans\tRafale\tProduct\ta fighter jet\tthe aircraft sold\n"
              "Here is the data you asked for:\n"          # prose the model added -> skipped
              "propositions\tIndia\tbought\tRafale\t2024\t\tpositive\tfactual\tIndia bought\n"
              "spans\tTruncated\tOther\n")                 # cut off mid-record -> padded
    _got = _tsv_parse(_reply, SPAN_SCHEMA)
    assert set(_got) == set(SPAN_SCHEMA["properties"]), "TSV must return every schema key"
    assert len(_got["spans"]) == 3 and len(_got["propositions"]) == 1, \
        "got %d spans / %d props" % (len(_got["spans"]), len(_got["propositions"]))
    assert _got["spans"][0] == {"text": "MBDA", "type": "Organization",
                                "gloss": "a missile maker", "in_article": "the supplier here"}, \
        "TSV fields must map by schema order"
    # A truncated final line is padded, never dropped: the text is still locatable, and locate()
    # is the thing that decides whether a span is real.
    assert _got["spans"][2]["text"] == "Truncated" and _got["spans"][2]["in_article"] == ""
    assert _got["propositions"][0]["object"] == "Rafale"
    assert _tsv_spec(SPAN_SCHEMA).startswith("spans\t<text>\t<type>")
    print("ok")


if __name__ == "__main__":
    _demo() if "--demo" in sys.argv else _demo()
