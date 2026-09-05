"""Fail if any regex literal in the pipeline contains a control character.

    python no_control_chars.py

A regex written through a shell heredoc has had its \b collapse into a literal 0x08
byte SIX times while building this pipeline. The pattern still compiles and simply never
matches, so the field goes quietly empty and reads as a thin source rather than a bug.
Each module asserts its own patterns in its demo; this catches the ones that have no
demo, and runs over the whole tree in one second.
"""
import io
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
bad = []
for p in sorted(ROOT.rglob("*.py")):
    if "__pycache__" in str(p):
        continue
    try:
        text = io.open(p, encoding="utf-8").read()
    except Exception:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        for c in line:
            if ord(c) < 32 and c != "\t":
                bad.append((p.relative_to(ROOT), i, hex(ord(c)), line.strip()[:70]))
                break
if bad:
    print("CONTROL CHARACTERS IN SOURCE — these regexes compile and never match:")
    for rel, i, code, line in bad:
        print("  %s:%d  %s  %s" % (rel, i, code, line))
    sys.exit(1)
print("no control characters in %d files" % len(list(ROOT.rglob("*.py"))))
