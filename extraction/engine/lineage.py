"""Extraction-run lineage: what code, what models, what settings produced a batch.

    python lineage.py            # print what a run started now would record
    python lineage.py --demo

The architecture proposal's §15 asks every extraction-derived record to carry enough version
information to reproduce it: `extraction_run_id`, `pipeline_version`, `model_version`,
`lexicon_version`. The store previously kept only `doc.model`, `doc.gliner` and `doc.built_at`.

This is the one gap worth closing BEFORE a long batch rather than after. Everything else the
normalized layer will want -- parsed numeric values, normalized predicates, span-anchored statement
arguments -- is derivable offline from what is already stored, because span text is verbatim and
offsets are exact. Lineage is not derivable after the fact: once the batch has run, nothing records
which commit or which model digest produced it, and the only way to find out is to run it again.

An Ollama tag is NOT a version. `qwen2.5:7b` is mutable and can be repointed by a pull, so the
digest is resolved and stored alongside it.
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Settings that change what the extractor emits. Recorded because a coverage number measured at
# GLiNER threshold 0.2 is not comparable with one measured at 0.35, and nothing else would say so.
# C_CTX_MAX / C_OPENAI / C_GUIDED added 2026-08-26. On the gateway path (_OPENAI, i.e. whenever
# OLLAMA_API_KEY is set) the completion ceiling is C_CTX_MAX, not the computed reply_budget: the
# 600-doc run was capped at a median 2,267 tokens where the budget asked for 15,260, 6,726 replies
# truncated, and 41% of stored spans came from the recovery pass paying for it a second time.
# None of that was recoverable from the store, because the one setting that caused it was not
# recorded. A quality event only visible in stdout is one nobody can regression-test.
TUNABLES = ("C_MODEL", "C_GLINER", "C_GLINER_TH", "C_CHUNK", "C_MAX_SPAN", "C_MAX_SPAN_W",
            "OLLAMA_URL", "OLLAMA_NUM_PARALLEL", "C_NUM_CTX", "C_TEMP",
            "C_CTX_MAX", "C_OPENAI", "C_GUIDED", "C_FORMAT")


# The runtime modules whose content decides what a run emits.
CODE_FILES = ("comprehend.py", "segment.py", "values.py", "lexicon.py", "store.py", "run.py")


def git_version(repo=HERE):
    """-> 'sha', 'sha-dirty', 'untracked:<hash>', or ''.

    A commit sha is only a version of code that is IN that commit. This directory is not tracked in
    the repository, so `git rev-parse HEAD` cheerfully returned a clean sha of a commit containing
    none of these files -- lineage that looks authoritative and points at the wrong code, which is
    worse than recording nothing. So the tree is asked whether it tracks these files at all, and
    when it does not, the content hash is named as the version instead.
    """
    h = "untracked:" + file_version(*CODE_FILES)
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                             capture_output=True, text=True, timeout=15)
        if sha.returncode:
            return h
        tracked = subprocess.run(["git", "ls-files", "--", "."], cwd=repo,
                                 capture_output=True, text=True, timeout=20)
        if not tracked.stdout.strip():
            return h
        st = subprocess.run(["git", "status", "--porcelain", "."],
                            cwd=repo, capture_output=True, text=True, timeout=20)
        return sha.stdout.strip() + ("-dirty" if st.stdout.strip() else "")
    except Exception:
        return h


def file_version(*names):
    """Content hash of the files that decide output but are not versioned separately.

    The lexicon is data, not code: it can be edited without a commit and it retypes spans, so a
    store built before an edit and one built after are different products of the 'same' pipeline.
    """
    h = hashlib.sha256()
    for n in sorted(names):
        p = HERE / n
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def model_digest(model, url=None):
    """Resolve an Ollama tag to its immutable digest, from /api/tags.

    /api/show does NOT return a digest -- asking it and falling back to whatever it did return got
    `modified_at` stored in the digest column, which is a timestamp wearing a content hash's name.
    /api/tags carries the real one. '' when the daemon cannot be reached: a missing digest must
    never stop a batch, it only means this run is less reproducible.
    """
    url = url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
    try:
        import urllib.request
        d = json.loads(urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=20).read())
        want = model if ":" in model else model + ":latest"
        for m in d.get("models") or []:
            if m.get("name") == want or m.get("model") == want:
                return (m.get("digest") or "")[:16]
    except Exception:
        pass
    return ""


def run_lineage(run_id=None, note=""):
    """-> the dict stored once per extraction run."""
    import comprehend as C
    pipeline = git_version()
    lex = file_version("lexicon.py", "values.py", "segment.py")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg = {k: os.environ[k] for k in TUNABLES if k in os.environ}
    # Record the values in FORCE, not merely the ones overridden in the environment: a default that
    # changes in a later commit would otherwise silently reinterpret this run's numbers.
    cfg.update({"gliner_threshold": C.GLINER_TH, "chunk_chars": C.CHUNK_CHARS,
                "max_span_chars": C.MAX_SPAN_CHARS, "max_span_words": C.MAX_SPAN_WORDS})
    if not run_id:
        run_id = "run-" + started[:19].replace("-", "").replace(":", "").replace("T", "-")
    return {"run_id": run_id, "started_at": started, "pipeline_version": pipeline,
            "lexicon_version": lex, "model": C.MODEL, "model_digest": model_digest(C.MODEL),
            "gliner": C.GLINER_MODEL, "config": json.dumps(cfg, sort_keys=True), "note": note}


def _demo():
    v = git_version()
    # this tree is untracked, so the version must be the CONTENT hash and must say so -- a bare
    # commit sha here would name a commit that does not contain any of these files
    assert v.startswith("untracked:") or 7 <= len(v.split("-")[0]) <= 12, v
    if v.startswith("untracked:"):
        assert v.split(":")[1] == file_version(*CODE_FILES), v
    assert git_version(Path(__file__).parent / "no_such_dir") .startswith("untracked:")
    a = file_version("lexicon.py")
    assert len(a) == 12 and a == file_version("lexicon.py"), "must be stable"
    assert file_version("lexicon.py", "values.py") != a, "must depend on every named file"
    assert file_version("no_such_file_xyz.py") == file_version(), "missing files are skipped"
    assert model_digest("definitely-not-a-model") == "", "unknown tag -> no digest"
    dg = model_digest("qwen2.5:7b")
    # a digest is a content hash, never a timestamp -- storing modified_at here was the bug
    assert dg == "" or (len(dg) == 16 and all(ch in "0123456789abcdef" for ch in dg)), dg
    assert model_digest("x", url="http://127.0.0.1:1") == "", "unreachable -> no raise"

    lin = run_lineage(note="t")
    for k in ("run_id", "started_at", "pipeline_version", "lexicon_version", "model",
              "model_digest", "gliner", "config", "note"):
        assert k in lin, k
    assert lin["run_id"].startswith("run-") and len(lin["run_id"]) > 10, lin["run_id"]
    cfg = json.loads(lin["config"])
    # the settings that decide output must be present whether or not they were set in the env
    for k in ("gliner_threshold", "chunk_chars", "max_span_chars", "max_span_words"):
        assert k in cfg, k
    assert run_lineage(run_id="fixed")["run_id"] == "fixed"
    print("ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        for k, v in run_lineage().items():
            print(f"  {k:<18}{v}")
