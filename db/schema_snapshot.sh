#!/bin/sh
# Column inventory of serving + serving_live, from any database.
#
#   db/schema_snapshot.sh "$KSSL_DSN" > db/schema_snapshot.txt
#
# CI applies db/*.sql + db/migrations/*.sql to an empty Postgres, runs this, and
# diffs the result against the checked-in file: a schema change that does not
# reproduce the snapshot fails the build. Run it against production to prove the
# repo still describes the live database -- that is the check the drift of
# 2026-09 (eleven columns and a table) needed and did not have.
#
# Sorted by name, so a column's ORDINAL POSITION is deliberately not compared:
# ALTER appends, CREATE TABLE groups, and every consumer names its columns.
#
# serving.card and serving.signal_seen are excluded: they are created at runtime
# by card_writer.py and serving_fill.py, not by any file here.
set -eu
psql "${1:?usage: schema_snapshot.sh DSN}" -Atc "
  SELECT table_schema || '.' || table_name || '.' || column_name
         || ' ' || data_type
         || CASE WHEN is_nullable = 'NO' THEN ' NOT NULL' ELSE '' END
         || COALESCE(' DEFAULT ' || column_default, '')
    FROM information_schema.columns
   WHERE table_schema IN ('serving', 'serving_live')
     AND table_name NOT IN ('card', 'signal_seen')
   ORDER BY 1"
