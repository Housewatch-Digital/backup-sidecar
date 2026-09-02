# Backup hooks

Hooks let the sidecar prepare application data before staging or notify another
system after a result. They are executable files mounted into these directories:

| Directory | When it runs | Failure behavior |
| --- | --- | --- |
| `/hooks/pre-backup.d` | Before SQLite snapshots and ordinary file staging | Aborts the backup |
| `/hooks/post-backup.d` | After upload and retention | Marks the run failed, although the snapshot already exists |
| `/hooks/failure.d` | After any failed backup run | Logged, but cannot replace the original exit status |

Files run in lexical filename order. Non-executable files and missing hook
directories are ignored. Use numeric prefixes when order matters:

```text
10-export-postgres
20-check-export
```

The hook is executed directly, so include a valid interpreter line such as
`#!/bin/sh`. Avoid passing shell commands through environment variables.

## Environment

Hooks inherit all container environment variables. The sidecar also exports:

- `BACKUP_RUN_DIR` for every hook during a backup run
- `BACKUP_SNAPSHOT_ID` before post-backup hooks
- `BACKUP_EXIT_CODE` before failure hooks

The run directory is temporary and is removed when the command finishes. Put an
export below `BACKUP_SOURCE_DIR` when it should be included in the same backup.

## Database export example

A pre-backup hook can run `pg_dump` or `mysqldump` and atomically replace a file
under `/source/exports`. The required database client must exist in the image, so
derive a small custom image from the sidecar when needed.

Example PostgreSQL hook:

```sh
#!/bin/sh
set -eu

temporary=/source/exports/database.dump.tmp
destination=/source/exports/database.dump
pg_dump --format=custom --file="$temporary" "$DATABASE_URL"
mv "$temporary" "$destination"
```

Do not mount a live PostgreSQL or MySQL data directory and copy it as ordinary
files. A database-native export or physical-backup workflow is required.
