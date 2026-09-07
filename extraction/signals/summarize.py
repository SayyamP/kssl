"""The article, read for the reader -- an English write-up detailed enough that
opening the source is optional.

WHY THIS EXISTS. `serving.signal_detail.what` is one sentence, and the model that
writes it never sees the article: serving_fill's card prompt is fed the extracted
PROPOSITIONS, so `what` is a summary of a summary. Beside it the panel showed six
STATEMENT rows -- a six-word paraphrase and the publisher's own sentence, in the
publisher's own language. Between them the reader got fragments in two languages and
still had to open the article. This module reads `extracted.document.text` and writes
the paragraph plus specifics the fragments were standing in for.

WHAT IT DOES NOT DO. It does not replace the quotes. `ev_quote` is located by offset
and stays the publisher's sentence in the publisher's language; that block moves below
this one, it is not translated and not thrown away. And this write-up carries no
significance verdict -- `why` (sowhat) already owns that, and a summary that argues is
a summary that invents.
"""

import html as _html
import os
import re

import translate

PROMPT_VERSION = "s1"

# How much of the article the model reads. Defence news is front-loaded -- the award,
# the quantity and the customer are in the first screen -- and a 7B given 20k chars
# summarises the navigation chrome as readily as the story.
MAX_CHARS = int(os.environ.get("KSSL_SUMMARY_MAX_CHARS") or 7000)

# Below this the model has not written a summary, it has written a headline.
MIN_CHARS = 160

_PROMPT = """Summarise this news article for a reader who will NOT open it.

Write in ENGLISH, whatever language the article is written in.

Answer in exactly this shape:
A paragraph of 2 to 4 sentences: who did what, when, and what the outcome was.
Then 3 to 6 lines each starting with "- ", carrying the specifics the paragraph left
out: quantities, sums of money, dates, contract terms, model and programme names,
delivery schedules, named people with their roles, and places.

Rules:
- Use ONLY facts stated in the article. Never add anything you know from elsewhere.
- Spell every product, programme, company and person name exactly as the article does.
- If the article gives a number, give that number.
- No heading, no preamble, no closing comment, no guess about why it matters.

Article title: %s
Article:
%s"""

_RETRY = """Rewrite the text below in English. Keep every fact, number, name and the
same shape (a paragraph, then the "- " lines). Change nothing else.

%s"""

# A model asked for "no preamble" writes one anyway about a fifth of the time.
_PREAMBLE = re.compile(
    r"^\s*(?:here\s+is|here's|this\s+article|the\s+article|summary|in\s+summary|"
    r"executive\s+summary)\b[^.\n:]*[:.]\s*", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+")


def _clean(raw):
    """-> (paragraph_lines, bullet_lines). Shape is taken from the text, not trusted
    from the prompt: a model that answers in all bullets or all prose still parses.

    A paragraph ends at a BLANK line or at the first bullet -- never at a newline. The
    model hard-wraps its prose, so splitting on newlines turned one paragraph into
    three sentence fragments, each in its own <p>."""
    text = _PREAMBLE.sub("", str(raw or "").strip())
    paras, bullets, buf = [], [], []

    def flush():
        if buf:
            paras.append(" ".join(buf))
            buf.clear()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            flush()
        elif _BULLET.match(line):
            flush()
            bullets.append(_BULLET.sub("", line).strip(" .;").strip())
        elif bullets:
            # a wrapped continuation of the last bullet. Prose that appears after the
            # list is the model's closing commentary, which the prompt forbids and
            # which is the one thing here that is not the article.
            bullets[-1] += " " + line
        else:
            buf.append(line)
    flush()
    return [p for p in paras if p], [b for b in bullets if len(b) > 3]


def to_html(paras, bullets):
    """Escaped, because this text is the model's and the panel renders it as HTML."""
    out = "".join("<p>%s</p>" % _html.escape(p, quote=False) for p in paras)
    if bullets:
        out += "<ul>%s</ul>" % "".join(
            "<li>%s</li>" % _html.escape(b, quote=False) for b in bullets)
    return out


def summarize(text, title=None, language=None, ask=None, stats=None):
    """-> HTML string, or None when the article yields nothing worth showing.

    None is a real answer: the panel keeps its existing blocks rather than showing an
    empty section or a sentence the model padded out to look like a summary.
    """
    body = (text or "").strip()
    if len(body) < 200:
        _bump(stats, "summary_thin_source")
        return None
    if ask is None:                                   # pragma: no cover - wired by caller
        raise ValueError("summarize() needs the caller's ask()")

    raw = ask(_PROMPT % (title or "", body[:MAX_CHARS]))
    paras, bullets = _clean(raw)
    blob = " ".join(paras + bullets)
    if not blob:
        _bump(stats, "summary_empty")
        return None

    # THE LANGUAGE GATE RUNS BEFORE THE LENGTH GATE, and the order is load-bearing.
    # The prompt says English; the 7B obeys it for English sources and drifts back to
    # the source language for Russian and Turkish ones. Russian and Turkish also say
    # the same thing in fewer characters than English does, so a foreign answer sits
    # under MIN_CHARS far more often than its English rewrite would -- checking length
    # first would refuse it as "thin" and never ask for the English that would have
    # passed.
    #
    # looks_translated(), NOT needs_english(). needs_english is a gate on the INPUT and
    # answers from the document's language alone: needs_english(anything, "ru") is True
    # whatever the string says, so it would send every summary of a Russian article to
    # the retry and refuse the perfectly good English that came back.
    if not translate.looks_translated(blob):
        _bump(stats, "summary_retried")
        paras, bullets = _clean(ask(_RETRY % blob))
        blob = " ".join(paras + bullets)
        if not translate.looks_translated(blob):
            _bump(stats, "summary_not_english")
            return None

    # Below this the model has written a headline, not a summary.
    if len(blob) < MIN_CHARS:
        _bump(stats, "summary_thin")
        return None

    _bump(stats, "summary_written")
    return to_html(paras, bullets)


def _bump(stats, key):
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


def _demo():
    """Self-check: shape parsing, preamble, commentary, escaping, refusals."""
    good = """Here is a summary: Rheinmetall won a 2026 framework order from the German
Bundeswehr for 155 mm artillery ammunition, worth up to EUR 1.2 billion.
Deliveries run from 2027 to 2030.

- Order value up to EUR 1.2 billion
- 155 mm artillery ammunition
* Deliveries 2027-2030
1. Customer: Bundeswehr, via BAAINBw
"""
    paras, bullets = _clean(good)
    assert len(paras) == 1, paras
    assert paras[0].startswith("Rheinmetall won"), paras          # preamble stripped
    assert len(bullets) == 4, bullets                             # -, *, and 1. all count
    assert bullets[3] == "Customer: Bundeswehr, via BAAINBw", bullets

    # prose after the list is closing commentary, not a second paragraph
    tail = "Lead.\n- one fact\ncontinued here"
    p2, b2 = _clean(tail)
    assert p2 == ["Lead."] and b2 == ["one fact continued here"], (p2, b2)

    # a paragraph-only answer still parses; an all-bullets answer still parses
    assert _clean("Just one paragraph.") == (["Just one paragraph."], [])
    assert _clean("- first fact\n- second fact")[1] == ["first fact", "second fact"]
    # a stub too short to be a fact is dropped, not rendered as an empty row
    assert _clean("- a\n- b")[1] == []

    html = to_html(["A <b>tag</b> & co"], ["x < y"])
    assert "<b>" not in html and "&lt;b&gt;" in html, html
    assert html.startswith("<p>") and "<ul><li>" in html, html

    calls = []

    def ask_en(prompt):
        calls.append(prompt)
        return ("Saab delivered two GlobalEye aircraft to the Swedish Air Force in "
                "March 2026 under a 2022 contract.\n"
                "- Two GlobalEye airborne early warning aircraft\n"
                "- Customer: Swedish Air Force\n"
                "- Contract signed 2022, delivery March 2026\n")

    art = "x" * 400
    out = summarize(art, "Saab delivers", "en", ask=ask_en)
    assert out and "<ul>" in out and "GlobalEye" in out, out
    assert "Article title: Saab delivers" in calls[0], calls[0]

    # too short a source is refused without asking the model at all
    st = {}
    assert summarize("tiny", ask=ask_en, stats=st) is None
    assert st == {"summary_thin_source": 1}, st

    # a one-line answer is a headline, not a summary
    st = {}
    assert summarize(art, ask=lambda p: "Saab delivered aircraft.", stats=st) is None
    assert st.get("summary_thin") == 1, st

    # non-English survives one retry, and is refused when the retry also fails
    st = {}
    seen = {"n": 0}
    ru_first = ("\u0420\u043e\u0441\u0441\u0438\u0439\u0441\u043a\u0430\u044f "
                "\u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f "
                "\u043f\u043e\u0441\u0442\u0430\u0432\u0438\u043b\u0430 "
                "\u0434\u0432\u0430\u0434\u0446\u0430\u0442\u044c "
                "\u0431\u0440\u043e\u043d\u0435\u043c\u0430\u0448\u0438\u043d "
                "\u0432 \u043c\u0430\u0440\u0442\u0435 2026 \u0433\u043e\u0434\u0430 "
                "\u043f\u043e \u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442\u0443 "
                "\u0441 \u043c\u0438\u043d\u0438\u0441\u0442\u0435\u0440\u0441\u0442\u0432\u043e\u043c "
                "\u043e\u0431\u043e\u0440\u043e\u043d\u044b.\n"
                "- \u0414\u0432\u0430\u0434\u0446\u0430\u0442\u044c "
                "\u0431\u0440\u043e\u043d\u0435\u043c\u0430\u0448\u0438\u043d "
                "\u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u043e\n")

    def ask_ru(prompt):
        seen["n"] += 1
        if seen["n"] == 1:
            return ru_first
        return ("The company delivered twenty armoured vehicles in March 2026 under a "
                "standing contract with the ministry of defence.\n"
                "- Twenty armoured vehicles delivered\n"
                "- Delivered March 2026\n")

    out = summarize(art, "t", "ru", ask=ask_ru, stats=st)
    assert out and "armoured vehicles" in out, out
    assert st.get("summary_retried") == 1 and st.get("summary_written") == 1, st

    # a retry that comes back still foreign is refused, not served
    st = {}
    ru_only = ("\u0420\u043e\u0441\u0441\u0438\u0439\u0441\u043a\u0430\u044f "
               "\u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f "
               "\u043f\u043e\u0441\u0442\u0430\u0432\u0438\u043b\u0430 "
               "\u0434\u0432\u0430\u0434\u0446\u0430\u0442\u044c "
               "\u0431\u0440\u043e\u043d\u0435\u043c\u0430\u0448\u0438\u043d "
               "\u0432 \u043c\u0430\u0440\u0442\u0435 2026 \u0433\u043e\u0434\u0430 "
               "\u043f\u043e \u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442\u0443 "
               "\u0441 \u043c\u0438\u043d\u0438\u0441\u0442\u0435\u0440\u0441\u0442\u0432\u043e\u043c "
               "\u043e\u0431\u043e\u0440\u043e\u043d\u044b \u0441\u0442\u0440\u0430\u043d\u044b.")
    assert summarize(art, "t", "ru", ask=lambda p: ru_only, stats=st) is None
    assert st.get("summary_not_english") == 1, st

    # AND THE CASE THAT NEEDS_ENGLISH WOULD HAVE BROKEN: a Russian article whose
    # summary comes back in good English on the first ask is served as-is, with no
    # retry at all.
    st = {}
    out = summarize(art, "t", "ru", ask=ask_en, stats=st)
    assert out and "GlobalEye" in out, out
    assert "summary_retried" not in st, st

    print("summarize: ok")


if __name__ == "__main__":
    _demo()
