"""The code-switched rows, labelled by hand, because sampling keeps missing them.

    python test_translation_fixture.py           # hermetic: routing + controls
    KSSL_FIXTURE_LIVE=1 ... python test_translation_fixture.py   # + the real farm

WHY A FIXTURE AND NOT MORE SAMPLING. Five rounds of random per-language sampling
reported 97.8% "mechanically clean" while the single row this layer was built for --

    sette veicoli ruotati 8x8 Centauro II are forniti

-- was scored as clean. It has no non-ASCII letter and no foreign function word, so
looks_translated() calls it English; a model that copies it out is recorded as
"unchanged"; and the harness applies the same rule, so the copy counts as a pass. The
measurement shared the code's blind spot, which is what a measurement must never do.

Here the answer is known in advance. Every row below is real corpus text, read and
labelled by hand, and for the mixed ones `unchanged` is a FAILURE by definition. No
amount of sampling produces that guarantee.

The `lang` field is the language the DATABASE has recorded, not necessarily the true
one -- extracted.document.language is a detector's opinion and it is sometimes wrong.
Four rows below are deliberately mislabelled in exactly the way the corpus mislabels
them (French filed as zh, Russian and Dutch filed as fi, German filed as he), because
the layer has to work when the label lies.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import translate as T                                                  # noqa: E402

# (db_label, text, note). All real rows from the staging corpus.
MIXED = [
    ("it", "sette veicoli ruotati 8x8 Centauro II are forniti",
     "THE row: English verb, Italian subject and object, no diacritic, no function word"),
    ("it", "Il Centauro II is a armored fighting vehicle", "Italian subject, English tail"),
    ("it", "Il nuovo velivolo will undergo Operational Test and Evaluation (OT&E)", ""),
    ("de", "Kommandeur der Einsatzflottille 1 said Was Russland da macht, braucht eine Antwort",
     "German on both sides of an English verb"),
    ("de", "Repräsentanten der Krankenhausgesellschaft und der PflegeGesellschaft are appointed by Minister Schweitzer", ""),
    ("fr", "Mark Rutte has excellentes relations avec le président Trump", ""),
    ("fr", "Les Forces maritimes combinées is a the largest multinational naval partnership in the world", ""),
    ("es", "el número de usuarios has an impact on la calidad de la red", ""),
    ("es", "El Ejército Argentino will be deployed in Rosario", ""),
    ("pl", "koszt zakupu includes cenę oferowaną przez producenta powiększoną do koszty obsługi FMS", ""),
    ("nl", "Een goed salaris is between €3,500 and €4,800", "currency and digits must survive"),
    ("pt", "modernização das Forças Armadas are state programs", ""),
    ("cs", "Saab has marži EBIT ve výši 8,9 procenta", "decimal comma: 8,9 must survive"),
    ("da", "Der has been announced 22,8 mia. kr. of the 25 mia. kr. in 2025",
     "two decimal-comma figures and a year"),
    ("sv", "Erfarenhet av standarder och regelverk kopplade till säkerhetskritiska system is required for the position", ""),
    ("no", "Du will be responsible for rask fremtaking av prototyper og testobjekter", ""),
    ("tr", "test programı includes inşikâh testleri, Albatros-S KİDA ile müşterek harekât ve güdümlü mermi atış provaları",
     "agglutinative: almost no function words for the gate to find"),
    ("tr", "Meteor Füzesi is used Eurofighter Typhoon, Rafale, Gripen ve F-35 Lightning II gibi ileri platformlarla",
     "four aircraft designators must survive"),
    ("fi", "kokous gathered maanantaina iltapäivällä", "agglutinative, two diacritics only"),
    ("uk", "Nammo will receive ліцензію на боєприпаси", "Cyrillic tail"),
    ("uk", "650 ракет MSE на рік is not a target for 2027", "quantity, designator, year"),
    ("ru", "речь идёт is about о наличии позиционных районов ПВО-ПРО", ""),
    ("id", "India has 128 unit dibuat di India", "quantity must survive"),
    ("ms", "Peregrine is placed di sisi laluan maritim", "product name must survive"),
    # THE LABEL LIES. These four are filed under the wrong language in the corpus.
    ("zh", "Participer à la validation industrielle is a action", "French filed as zh"),
    ("fi", "Link naar het klokkenluidersysteem is a whistleblowing system", "Dutch filed as fi"),
    ("fi", "ссылка на систему информирования is a reporting system", "Russian filed as fi"),
    ("he", "Bundesministerium der Verteidigung is defense technology company", "German filed as he"),
]

# Must come back byte-identical. A layer that translates these is worse than none.
CONTROLS = [
    ("en", "Warsaw ordered 32 F-35s"),
    ("en", "Peru imported cluster munitions"),
    ("en", "Compliance Program establishes fair-trade culture"),
    ("en", "Lockheed Martin undertakes all operational responsibilities of the project"),
    ("en", "RCWS320C-UAS enables layered air defence concepts"),
    ("en", "Saab invests 40% of its resources"),
    # An English row on a document the corpus labels non-English: still must not change.
    ("de", "Rheinmetall is participating in the large business opportunity"),
    ("tr", "HAVELSAN integrates networked combat capabilities with autonomous unmanned systems"),
]

FLOOR = float(os.environ.get("KSSL_FIXTURE_FLOOR") or 0.95)


def hermetic():
    """No network. Two things: every mixed row must be ROUTED to the model, and the
    string gate's blind spot is reported as a number rather than left implicit."""
    bad = []
    for lang, text, _note in MIXED:
        if not T.needs_english(text, lang):
            bad.append((lang, text))
    assert not bad, "these mixed rows would never be sent to the model:\n" + \
        "\n".join("  [%s] %s" % (l, t) for l, t in bad)

    # THE BLIND SPOT, MEASURED. With no language recorded -- 119 served cards have no
    # extracted.document row -- the string is all there is. This is not a failure and
    # is not asserted as one; it is the number that says how much work the document
    # label is doing, and it must not silently get worse.
    unseen = [t for _l, t, _n in MIXED if T.looks_translated(t)]
    seen = len(MIXED) - len(unseen)
    print("  string gate alone sees %d/%d mixed rows (%.0f%%); the rest are carried "
          "by the document label" % (seen, len(MIXED), 100 * seen / len(MIXED)))
    for t in unseen[:4]:
        print("      invisible to the string gate: %s" % t[:78])

    for lang, text in CONTROLS:
        assert T.looks_translated(text), \
            "control row must read as English to the gate: %r" % text
    # ...and with no language, an English control is never even asked about.
    for lang, text in CONTROLS:
        assert not T.needs_english(text, None), \
            "control row would be sent to the model for nothing: %r" % text
    print("  %d control row(s) read as English and cost no call" % len(CONTROLS))
    print("ok - hermetic")


def live():
    """The real farm. Every mixed row must come back CHANGED and pass verdict; every
    control row must come back identical."""
    langs = sorted({l for l, _t, _n in MIXED})
    fails, copied = [], []
    for lang in langs:
        rows = [(t, n) for l, t, n in MIXED if l == lang]
        st = {}
        got = T.translate_lines([t for t, _n in rows], lang, stats=st)
        for (src, note), out in zip(rows, got):
            if out == src:
                copied.append((lang, src, note))
            else:
                ok, why = T.verdict(src, out)
                if not ok:
                    fails.append((lang, src, why, out))
        print("  [%s] %d row(s)  %s" % (lang, len(rows),
              {k: v for k, v in sorted(st.items()) if k != "seen"}))

    st = {}
    ctl = T.translate_lines([t for _l, t in CONTROLS], None, stats=st)
    changed = [(a[1], b) for a, b in zip(CONTROLS, ctl) if a[1] != b]
    assert not changed, "control rows were altered:\n" + \
        "\n".join("  %r -> %r" % (a, b) for a, b in changed)
    assert not st.get("asked"), "control rows cost %s call(s)" % st.get("asked")

    n = len(MIXED)
    good = n - len(copied) - len(fails)
    print("\n  translated %d/%d (%.1f%%)  copied-out %d  refused %d"
          % (good, n, 100 * good / n, len(copied), len(fails)))
    for lang, src, note in copied:
        print("    COPIED OUT [%s] %s%s" % (lang, src[:70], "  (%s)" % note if note else ""))
    for lang, src, why, out in fails:
        print("    REFUSED [%s] %s\n            %s -> %s" % (lang, why, src[:60], out[:60]))
    assert good / n >= FLOOR, \
        "%.1f%% translated, floor is %.0f%%" % (100 * good / n, 100 * FLOOR)
    print("ok - live")


if __name__ == "__main__":
    hermetic()
    if os.environ.get("KSSL_FIXTURE_LIVE") == "1":
        live()
    else:
        print("(live pass skipped -- set KSSL_FIXTURE_LIVE=1 with the farm configured)")
