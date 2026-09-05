# Archive — not part of the pipeline

Nothing in here runs, and nothing outside here may import it. It is kept only so the
work is recoverable and the reasoning is not lost.

## harvest/  (moved out of `pipeline/` on 2026-09-05)

Fetched each competitor's OWN website — investor-relations, about and product pages —
and wrote what it found into `serving.competitors` (`leadership`, `facilities`,
`sales`) and into the `harvest.*` schema.

**Retired by decision:** the dashboard states facts from the extraction corpus, and a
figure scraped off a company's marketing page is not that. Competitor financials must
come from the extracted data, or from the crawler corpus, or be shown as absent.

Two things this leaves behind, both deliberate rather than forgotten:

- `serving.competitors.leadership` (6 rows) and `.facilities` (12 rows) still hold
  harvest-sourced values on production. They are NOT revenue and were not part of the
  decision above, so they have been left alone rather than silently deleted. They are
  harvest-sourced, and if the same rule applies to them they need purging separately.
- `pipeline/pair_rivals.py` still reads the `harvest.fact` TABLE for rival spec sheets.
  It reads the database, not this code, so it keeps working — but it now has no
  producer, and its data will not refresh.
