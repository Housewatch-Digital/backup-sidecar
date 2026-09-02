# Restore runbook

Do not restore directly into a live application volume. Restore into a separate
volume, inspect the result, and plan the cutover.

## Restore the latest snapshot

Mount an empty persistent volume at `/restore`, then run:

```sh
sqlite-backup snapshots
sqlite-backup restore-latest /restore/rehearsal
```

The restore command chooses the latest snapshot with the current tag, then runs
SQLite `PRAGMA quick_check` against every database recorded in the snapshot.

## Inspect the result

Review:

- `/restore/rehearsal/.sqlite-backup/manifest`
- `/restore/rehearsal/.sqlite-backup/sqlite-paths`
- Expected SQLite row counts
- A sample of uploaded or generated files
- File ownership and permissions required by the application

Run verification again at any time:

```sh
sqlite-backup verify /restore/rehearsal
```

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
