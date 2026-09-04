# Backup hooks

Hooks let the sidecar prepare application data before staging or notify another
system after a result. They are executable files mounted into these directories:

| Directory | When it runs | Failure behavior |
| --- | --- | --- |
| `/hooks/doctor.d` | During `doctor`, after base configuration checks | Fails `doctor` |
| `/hooks/pre-backup.d` | Before SQLite snapshots and ordinary file staging | Aborts the backup |
| `/hooks/post-backup.d` | After upload and retention | Marks the run failed, although the snapshot already exists |
| `/hooks/failure.d` | After any failed backup run | Logged, but cannot replace the original exit status |
| `/hooks/verify.d` | After built-in checks of a restored snapshot | Fails restore verification |

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
- `BACKUP_PAYLOAD_DIR` for pre-backup hooks; write generated artifacts here
- `BACKUP_SNAPSHOT_ID` before post-backup hooks
- `BACKUP_EXIT_CODE` before failure hooks
- `BACKUP_RESTORE_DIR` for verify hooks

The run and payload directories are temporary and removed when the command
finishes. Files written under `BACKUP_PAYLOAD_DIR` are included in the current
snapshot without modifying a source volume. Reserve `.backup-sidecar` in the
payload for generated backup metadata; that path is excluded from ordinary source
staging so a mounted volume cannot overwrite hook output.

## Database export example

A pre-backup hook can run `pg_dump` or `mysqldump` and write the output directly
under `BACKUP_PAYLOAD_DIR`. The required database client must exist in the image.
The published `postgres16` variant includes maintained PostgreSQL hooks; use a
derived image for other engines.

Example PostgreSQL hook:

```sh
#!/bin/sh
set -eu

mkdir -p "$BACKUP_PAYLOAD_DIR/.backup-sidecar/custom"
temporary="$BACKUP_PAYLOAD_DIR/.backup-sidecar/custom/database.dump.tmp"
destination="$BACKUP_PAYLOAD_DIR/.backup-sidecar/custom/database.dump"
pg_dump --format=custom --file="$temporary" "$DATABASE_URL"
pg_restore --list "$temporary" >/dev/null
mv "$temporary" "$destination"
```

Do not mount a live PostgreSQL or MySQL data directory and copy it as ordinary
files. A database-native export or physical-backup workflow is required.
