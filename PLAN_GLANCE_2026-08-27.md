# Dynamic "At a glance" — design for audit

## The ask
"At a glance" today prints the same five labels on every signal: Company, Category, Date,
Primary lens, Publisher, Stance. Those are properties of the ROW, not of the article. The
operator read a source article and found things the panel never shows — the order was
"worth 460 million kronor", the contract "is valid for ten years", there are "options for
additional orders worth up to SEK 640 million". At a glance must become dynamic: the rows
it prints are decided by what THIS article states, and change article to article.

## What we already hold (measured, not assumed)
`serving.signal_detail`, origin='pipeline': 14 rows locally, 17 on the VPS.
* `what`  — a one-paragraph summary. 8 of 14 contain a digit.
* `lens`  — 14 of 14 non-empty. Each entry is `["STATEMENT", "<claim> — <i>&ldquo;<verbatim
  source sentence>&rdquo;</i>"]`. **This is the asset.** It is already a quote lifted from
  the source document, so it is evidence, not paraphrase. The panel stopped rendering it
  when "Full-spectrum read" was removed, so today it is carried and shown to nobody.
* `facts` — the fixed 4 rows above.
* `title`, `url`, `dir`.

Real values present in this corpus: `$2.3 billion`, `21 UH-60M`, `460 million kronor`,
`17 Giraffe 1X radars`, `F-16V Block 70`, `155-мм` (Cyrillic mm — the corpus is multilingual).

## The rule
> A fact row appears only when this article STATES it, and it carries the sentence it was
> read from.

Concretely, for a candidate `(label, value)`:
1. `value` must appear **verbatim** (after one normalisation pass) inside `evidence` =
   `what` + every lens quote + `title`.
2. The **sentence** containing it becomes the row's `q` (quote). No sentence, no row.
3. The sentence must also contain the fact's **subject anchor** — see below.

Rule 3 is the one that matters. Past faults in this codebase were all "the number exists
in the document" mistaken for "the number is this fact". A currency amount three sentences
away from the order is not the order's value.

## Extractors (ordered; each yields 0..1 rows unless noted)

| # | Label | Pattern | Subject anchor required in the same sentence |
|---|---|---|---|
| 1 | Order value | `CUR AMT UNIT` or `AMT UNIT CUR` where CUR ∈ {$, €, £, ₹, SEK, NOK, USD, EUR, INR, kronor, crore, lakh, …}, UNIT ∈ {million, billion, bn, m, crore, …} | one of: order, contract, deal, worth, value, purchase, awarded, procurement (or its translation in the sentence's own language — see Multilingual) |
| 2 | Options / ceiling | same pattern, sentence also contains: option, up to, additional, ceiling, framework, maximum | as above |
| 3 | Quantity | `\b(\d[\d,]*)\s+(<product noun>)` where product noun comes from the row's own `title`/`what` proper nouns, or ∈ {units, systems, vehicles, rounds, aircraft, helicopters, radars, rifles, …} | the counted noun IS the anchor |
| 4 | Platform | longest proper-noun run in `title` that also occurs in `what` | — (title-derived, not number-derived) |
| 5 | Customer | country/agency name in a sentence containing: order from, contract with, awarded by, selected by, purchase, delivery to | the verb phrase is the anchor |
| 6 | Contract term | `\b(\d+|one|two|…|ten)[- ](year|month)s?\b` | contract, agreement, framework, valid, term |
| 7 | Delivery | `(deliver\w*|in service|entry into service).{0,40}(19|20)\d\d` or `(19|20)\d\d.{0,40}deliver\w*` | the verb IS the anchor |
| 8 | Programme | capitalised programme token from a curated set present in the corpus (AUKUS, ATAGS, FMS, …) | — |

Then the four existing row-level facts (Company, Category, Date, Primary lens) and the two
added last session (Publisher, Stance) are appended, deduped by label.

**Order of rows: money → quantity → platform → customer → term → delivery → programme →
row-level.** Not by confidence: a stable order means the operator learns where to look,
and every row present is equally grounded by construction.

**Cap: 10 rows.** Past 10 it stops being a glance.

## Multilingual (this codebase has been bitten three times)
The corpus carries Swedish, Russian, French, Ukrainian. So:
* Unit and currency words are matched from a table with the non-English forms that
  actually occur — `kronor`, `мм`, `млн`, `crore` — not an English-only list.
* An anchor list that only holds English words is a LANGUAGE DETECTOR: it silently emits
  zero facts for every non-English article and the panel looks merely thin rather than
  broken. So: if the sentence has **no** anchor from any language table AND the article's
  detected script is non-Latin, the extractor emits nothing and increments a counter that
  the verifier prints per language. A per-language zero is a FAILURE to investigate, not a
  result.
* Digits: normalise Arabic-Indic and full-width digits before matching.

## Normalisation before matching (one pass, both sides)
NFKC · unescape HTML entities · collapse whitespace · unify dashes (– — → -) · unify
quotes · strip the `&ldquo;`/`&rdquo;` wrapper the lens rows carry. Not lowercase: casing
is what identifies a proper noun in extractor 4.

## Rendering
`facts` becomes `[label, value, quote?]`. DetailPanel prints label/value as today and
attaches `title={quote}` plus a small "❞" affordance when a quote exists. No new section,
no layout change. Rows without a quote (the row-level four) render exactly as now.

## Verification (must run before this ships)
`pipeline/verify_glance.py`, over EVERY pipeline detail row, printing:
1. per-row: extracted facts with their quotes;
2. **hard assert**: every extracted `value` is a substring of its own `q`;
3. **hard assert**: every `q` is a substring of the row's evidence;
4. per-label counts and per-language counts (the zero-detector above);
5. a manual-read column so a human can mark wrong rows — the number that matters is
   precision, and only a person can score it.
Target: **zero ungrounded rows**. A missed fact is acceptable; an invented one is not.

## What this deliberately does NOT do
* No LLM at render time — the panel must be deterministic and offline-reproducible.
* No cross-article inference ("Saab's third order this year").
* No unit conversion. `460 million kronor` prints as written; converting to USD would put
  a number on screen that no source states.

---

# AUDIT RESULT (Fable 5, 2026-08-27) — DO NOT BUILD AS SPECCED

Audited against all 14 real `signal_detail` rows. Verdict: the approach is right, the
spec is not. Seven things must change first.

**1. Extractor 4 (Platform) must be dropped.** It is the only extractor with no anchor
and no quote, it fires on all 14 rows, and it is wrong on six: "South China Sea",
"Diego Garcia", "Daimler Truck", and "Saab" as the platform of a Saab article. Eight of
the 14 titles are Title Case, so "proper-noun run by capitalisation" means nothing here.
It would have been the most-rendered and least-grounded row on the panel.

**2. Order value needs negative evidence.** On the Norway row it emits
`$2.3 billion` — anchored, verbatim, quoted, and wrong: the same row's own lens says
*"The approval does not constitute a final Norwegian order"* and *"the maximum estimated
value of the full package"*. Ceiling markers (potential / up to / maximum / option) must
veto extractor 1, and a value claimed by extractor 2 must be barred from extractor 1.

**3. The language list was wrong and the failsafe is blind.** 10 of 14 rows carry
non-English evidence, and the languages are **Malay (3), Croatian (3), Swedish, German,
French, Lithuanian, Ukrainian** — not the "Swedish, Russian, French, Ukrainian" this doc
assumed. Russian does not occur at all. Worse, the zero-counter only fires on non-Latin
script, so **9 of the 10 non-English rows bypass it silently** — the exact failure this
doc quoted as unacceptable. Same fault, third time. Count per detected LANGUAGE.

**4. The motivating example is not extractable.** "options ... up to SEK 640 million"
exists only as Swedish (*"optioner ... upp till 640 miljoner kronor"*), and the trigger
list is English. So does the Croatian row's real order value (*"460 milijuna SEK"*) and
its delivery window (*"2026. do 2029."*). And **"valid for ten years" is in no stored
row at all** — extractors 6 and 7 fire ZERO times on the whole corpus.

**5. Quantity emits garbage.** "FV-014 LM" yields `Quantity: 014 LM`, fully grounded by
these rules. Reject digits inside hyphenated designations and calibres (155-мм).

**6. Customer has no role-awareness.** "The **US** Department of State approved
**Norway's** ... purchase" — two countries, one anchored sentence, and the rules pick the
approver.

**7. The claim halves are not evidence.** Lens rows are `claim — "quote"`, and the
CLAIMS contain hallucinated text ("Saab delivers orispe", "Ondas Networks is a product").
Split on the em-dash BEFORE dash normalisation, and treat only the quote halves as
evidence. The sentence splitter must also survive Croatian year ordinals ("2026. do
2029."), multi-sentence quotes and mid-sentence truncation.

## What this changes structurally

Point 4 is the important one. The facts the operator actually wants — order worth,
contract term, delivery window — are in the SOURCE ARTICLE but not in the six lens quotes
we store. Extracting from `lens` alone can only ever produce a thin panel. So the input
must widen to the stored corpus document text, which is a different architecture than
this doc assumed, and the honest scope for a lens-only version is: money and quantity on
English press releases, and nothing else.

Not implemented pending that decision.
