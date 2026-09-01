# Live backend snapshot — VPS1 (`srv1928858`, kssl-db)

A point-in-time export of the two backend schemas that serve the KSSL app, taken **2026-09-01**
from the production Postgres on VPS1.

These files are a **snapshot**, not the deployment DDL. The hand-maintained schema scripts in
`db/schema_extracted.sql`, `db/schema_serving.sql` and `extraction/db/*.sql` remain the source of
truth for how a fresh stack is built — they are deliberately not overwritten by `pg_dump` output,
because the dump carries index/constraint noise and a fresh deploy should not inherit it.

| file | what it is | size |
|---|---|---|
| `schema_live.sql` | `pg_dump --schema-only` of `extracted` + `serving`, exactly as it exists in production | 76 KB |
| `extracted_data.sql.gz` | all 8 `extracted.*` tables | 66 MB |
| `serving_data.sql.gz` | 14 `serving.*` tables | 474 KB |

## Row counts at export

```
extracted.proposition   116,749      serving.card           5,720  (EXCLUDED - see below)
extracted.entity_alias   63,376      serving.matchup          634
extracted.entity         49,487      serving.company_source   335
extracted.document        5,542      serving.signal_detail    234
extracted.extraction_run     76      serving.signal_card      228
extracted.span      (632 MB table)   serving.source_registry  190
                                     serving.tender           128
                                     serving.geo_presence     109
                                     serving.competitors       79
                                     serving.geo_comp          70
                                     serving.ui_config         44
                                     serving.innovation        38
                                     serving.patent            26
                                     serving.partner           12
```

## What is NOT in here, and why

**`serving.card` is excluded.** It is 247 MB on disk and **99.4% of the entire serving dump**
(81 MB compressed, against 474 KB for everything else in `serving` combined). It is also a
**derived** table: `card_text`, `spans` and `statements` are built from the `extracted` layer,
which *is* fully included here. Rebuild it after restoring:

```bash
docker compose run --rm cards --init --build
```

If you need the built cards as bytes rather than rebuilding them, say so and they can be added as
a separate artifact — they were left out to keep the repository from carrying 81 MB of output that
one command regenerates.

**No account data exists to exclude.** This database has no `app_users`, `app_sessions`,
`payments`, `alerts`, `saved_tenders`, `bids`, `user_tenders`, `ai_analysis` or `bidassist` table —
verified against `information_schema.tables` before exporting, not assumed. Both dumps were also
scanned line-by-line (1.6M lines) for credential shapes — AWS keys, GitHub PATs, Slack tokens,
private-key headers, Razorpay keys, and DSNs with inline passwords. Zero hits.

## Restore

Into an empty database:

```bash
createdb kssl
psql -d kssl -f schema_live.sql

# extracted.entity has a SELF-REFERENCING foreign key (entity.redirects_to -> entity.entity_id)
# and NOTHING in this schema is DEFERRABLE - checked, not assumed. A plain --data-only load
# therefore fails the moment a row redirects to an entity that COPY has not inserted yet.
# Drop that one constraint for the load and put it back afterwards:
psql -d kssl -c 'ALTER TABLE extracted.entity DROP CONSTRAINT entity_redirects_to_fkey;'

gunzip -c extracted_data.sql.gz | psql -d kssl --single-transaction
gunzip -c serving_data.sql.gz  | psql -d kssl --single-transaction

psql -d kssl -c 'ALTER TABLE extracted.entity
  ADD CONSTRAINT entity_redirects_to_fkey FOREIGN KEY (redirects_to)
  REFERENCES extracted.entity(entity_id);'

docker compose run --rm cards --init --build     # rebuilds serving.card
```

If you are restoring as a superuser you can instead keep the constraint and load with
`psql --single-transaction -c 'SET session_replication_role = replica;'` in the same session, which
suppresses FK triggers for the load. The drop/re-add above is written for the ordinary case where
the restoring role is not a superuser. Re-adding the constraint revalidates the whole table, so a
failure there means the dump genuinely has a dangling `redirects_to` — worth knowing, not
something to force past.

`serving.signal_seen` is in the data dump but not the row-count table above: it had no rows at
export time (it is written at runtime by the UI), so it does not appear in `pg_stat_user_tables`.
