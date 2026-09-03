# SQLite Backup Sidecar

SQLite Backup Sidecar creates consistent SQLite backups without stopping the
application. It uses SQLite's online backup API, verifies each copy, stages any
ordinary files mounted beside the databases, and sends the completed snapshot to
an encrypted Restic repository.

The container works with Docker Compose, Coolify, Kubernetes, and other container
platforms. Restic supports local storage, SFTP, REST servers, S3-compatible
storage, Backblaze B2, Azure Blob Storage, and Google Cloud Storage.

## What it protects

- One or more explicitly configured SQLite databases
- Ordinary files from one or more volumes mounted below `/source`
- Encrypted, deduplicated Restic snapshots
- Restores verified with SQLite `PRAGMA quick_check`

Do not copy live PostgreSQL or MySQL data directories with this sidecar. Use
`pg_dump`, `pg_basebackup`, `mysqldump`, or another engine-aware backup method,
then place the resulting export under `/source` if this sidecar should upload it.
The [hook support](docs/hooks.md) can automate that export.

Ordinary files are copied one at a time and are not a point-in-time filesystem
snapshot. This is suitable for immutable files, atomically replaced files, and
content that tolerates file-level consistency. Use a storage snapshot or stop
writes when an application needs a single instant across several ordinary files.
Files that vanish during staging are omitted and produce a warning without
failing the backup.

## Quick start

Mount application data read-only under `/source`. Each line in
`SQLITE_DATABASES` must be an absolute database path below `/source`.

```yaml
services:
  backup:
    image: ghcr.io/housewatch-digital/backup-sidecar:0.1.1
    command: ["daemon"]
    environment:
      BACKUP_NAME: example-production
      SQLITE_DATABASES: /source/app/application.db
      RESTIC_REPOSITORY: /repository
      RESTIC_PASSWORD: replace-with-a-secret
      BACKUP_INITIAL_DELAY_SECONDS: 60
      BACKUP_INTERVAL_SECONDS: 86400
    volumes:
      - application-data:/source/app:ro
      - backup-repository:/repository
      - backup-cache:/cache
      - backup-stage:/stage
      - backup-state:/state
      - backup-restore:/restore
```

For a platform scheduler, use `command: ["idle"]` and schedule
`sqlite-backup run`. See the [Docker Compose](docs/platforms/docker-compose.md),
[Coolify](docs/platforms/coolify.md), and
[Kubernetes](docs/platforms/kubernetes.md) guides.

## Required settings

| Variable | Meaning |
| --- | --- |
| `BACKUP_NAME` | Unique name containing letters, numbers, dots, underscores, or hyphens |
| `RESTIC_REPOSITORY` | Any repository URL supported by Restic |
| `RESTIC_PASSWORD` or `RESTIC_PASSWORD_FILE` | Restic repository encryption password |

Provider credentials are passed directly to Restic. The sidecar does not require
a particular cloud provider's variables. See [storage backends](docs/backends.md).

## SQLite and file settings

`BACKUP_SOURCE_DIR` defaults to `/source`. Mount any number of volumes at distinct
paths below it:

```yaml
volumes:
  - application-data:/source/application:ro
  - uploads:/source/uploads:ro
```

Set `SQLITE_DATABASES` to a newline-separated list:

```text
/source/application/primary.db
/source/application/tenant data/secondary.sqlite
```

Leave it empty for a file-only backup. The sidecar excludes each configured
database and its `-wal`, `-shm`, and `-journal` files from the ordinary file copy.

For a read-only WAL-mode mount, run `doctor` while the application has the
database open. SQLite can read WAL mode from a read-only directory when the
`-wal` and `-shm` files already exist. A cleanly closed WAL database may remove
those files and then require a writable directory to open again. The sidecar does
not use SQLite's `immutable` mode automatically because that mode can ignore live
WAL data. If the application is stopped and the database is known to be clean,
either mount its directory writable for the backup process or treat the stable
database as an ordinary file.

`BACKUP_EXCLUDES` accepts newline-separated rsync patterns:

```text
/application/cache/
/application/tmp/
*.log
```

Exclude known temporary paths to avoid repeated vanished-file warnings. The
sidecar does not exclude `*.tmp` automatically because an application may use
that suffix for data that must be backed up.

## Backup sequence

Each `run` command:

1. Takes a deployment lock.
2. Runs executable pre-backup hooks in lexical order.
3. Creates and verifies each SQLite snapshot.
4. Copies ordinary files into a private staging directory.
5. Adds restore metadata under `.sqlite-backup`.
6. Uploads the staged data to Restic.
7. Applies snapshot retention without pruning.
8. Runs executable post-backup hooks.
9. Records the snapshot ID and completion time under `/state`.

A failed run records its status and invokes failure hooks. See
[hooks](docs/hooks.md) for the hook contract.

## Commands

```text
sqlite-backup run
sqlite-backup idle
sqlite-backup daemon
sqlite-backup doctor
sqlite-backup snapshots
sqlite-backup check
sqlite-backup prune
sqlite-backup restore-latest /restore/rehearsal
sqlite-backup verify /restore/rehearsal
sqlite-backup health
sqlite-backup status
```

Run `sqlite-backup doctor` before the first backup. It validates the mounts,
configured SQLite paths, database health, tools, and Restic access without
creating a backup or initializing a repository.

## Retention and health

The defaults retain 30 daily, 8 weekly, and 12 monthly snapshots. A normal backup
runs `restic forget` but does not reclaim repository data. Run
`sqlite-backup prune` weekly and `sqlite-backup check` monthly.

The health check allows 93,600 seconds, or 26 hours, between successful backups.
Set `BACKUP_MAX_AGE_SECONDS` to match the schedule and alerting tolerance.

## Restore safety

The sidecar only restores into an empty path below `/restore`. It never replaces
live application data. Follow the [restore runbook](docs/restore-runbook.md) to
inspect a restore before planning an application-specific cutover.

## Development

```sh
make test
make image
```

The test suite exercises live WAL-mode writes, multiple databases, file-only
backups, hooks, restore verification, compatibility behavior, and a real local
Restic repository when Restic is installed.
