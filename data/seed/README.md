# PostgreSQL Seed

`supabase_baseline.dump` is a PostgreSQL custom-format dump used only when the
Compose `db` volume is empty and Postgres runs `/docker-entrypoint-initdb.d`.

## PII warning

The seed may contain personal information and production-like operational data.
Keep this repository private, do not share the dump outside approved deployment
channels, and review data handling before exporting a new file.

## Export

Use a Supabase direct, non-pooler database URL:

```sh
SUPABASE_DATABASE_URL='postgresql://...' ./scripts/export_supabase_seed.sh
```

The script writes `data/seed/supabase_baseline.dump`. Do not create that binary
dump as part of Task 2.

If the dump is missing or empty, local Compose startup logs a warning and leaves
the database empty for development.
