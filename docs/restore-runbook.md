# Restore runbook

Do not restore directly into a live application volume. Restore into a separate
volume, inspect the result, and plan the cutover.

## Restore the latest snapshot

Mount an empty persistent volume at `/restore`, then run:

```sh
backup-sidecar snapshots
backup-sidecar restore-latest /restore/rehearsal
```

The restore command chooses the latest snapshot with the current tag, then runs
the checks supplied by the image. The base image runs SQLite `PRAGMA quick_check`;
the PostgreSQL 18 image also validates every logical dump with
`pg_restore --list`.

## Inspect the result

Review:

- `/restore/rehearsal/.sqlite-backup/manifest`
- `/restore/rehearsal/.sqlite-backup/sqlite-paths`
- `/restore/rehearsal/.backup-sidecar/postgresql/databases.jsonl`, when present
- Expected SQLite row counts
- A sample of uploaded or generated files
- File ownership and permissions required by the application

Run verification again at any time:

```sh
backup-sidecar verify /restore/rehearsal
```

## Rehearse a PostgreSQL restore

The sidecar deliberately does not overwrite a live database. Start a disposable
PostgreSQL 18 server with the same required extension packages as production,
create an empty target database, then restore each archive listed in
`databases.jsonl`.

For one database from a Compose deployment:

```sh
docker compose run --rm --entrypoint pg_restore backup \
  --host=postgres-rehearsal \
  --port=5432 \
  --username=restore_user \
  --dbname=application_rehearsal \
  --no-owner \
  --no-acl \
  --exit-on-error \
  /restore/rehearsal/.backup-sidecar/postgresql/0001.dump
```

Supply the restore password through `PGPASSWORD` or `PGPASSFILE`, not a command
argument. If the target database is not empty, decide explicitly whether to drop
and recreate it or use appropriate `pg_restore --clean` options. Do not assume a
clean restore into a populated database is safe.

Verify schema objects, extensions, row counts, representative application reads,
and migrations. Record the snapshot ID, restore duration, PostgreSQL image, and
extension versions used in the rehearsal.

## Cut over

A typical SQLite cutover is:

1. Stop application writes.
2. Take one final backup of the current live data.
3. Preserve the old live volume.
4. Copy the verified restored data into a new volume.
5. Start the application against the new volume.
6. Run application health and data checks.
7. Keep the old volume until the rollback window closes.

The sidecar does not automate cutover because replacing live data is destructive
and application-specific.

A PostgreSQL cutover follows the same safety principles: stop writes, take a final
logical backup, preserve the old database, restore into a separately created
database or server, verify it, and only then repoint the application.
