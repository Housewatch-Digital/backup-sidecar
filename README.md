# Backup Sidecar

Backup Sidecar creates engine-aware database backups without copying live database
storage. The base image uses SQLite's online backup API, verifies each copy,
stages ordinary files mounted beside the databases, and sends the completed
snapshot to an encrypted Restic repository. The `postgres16` image adds verified
PostgreSQL 16 logical dumps through `pg_dump`.

The container works with Docker Compose, Coolify, Kubernetes, and other container
platforms. Restic supports local storage, SFTP, REST servers, S3-compatible
storage, Backblaze B2, Azure Blob Storage, and Google Cloud Storage.

## What it protects

- One or more explicitly configured SQLite databases in the base image
- One or more PostgreSQL 16 databases in the `postgres16` image
- Ordinary files from one or more volumes mounted below `/source`
- Encrypted, deduplicated Restic snapshots
- Restores verified with SQLite `PRAGMA quick_check` and/or `pg_restore --list`

Do not copy live PostgreSQL or MySQL data directories. Use the PostgreSQL variant,
another engine-aware backup method, or a custom [hook](docs/hooks.md). The
PostgreSQL variant creates logical dumps; it does not back up PostgreSQL roles,
tablespaces, physical replication state, or the server data directory.

Ordinary files are copied one at a time and are not a point-in-time filesystem
snapshot. This is suitable for immutable files, atomically replaced files, and
content that tolerates file-level consistency. Use a storage snapshot or stop
writes when an application needs a single instant across several ordinary files.
Files that vanish during staging are omitted and produce a warning without
failing the backup.

## SQLite quick start

Mount application data read-only under `/source`. Each line in
`SQLITE_DATABASES` must be an absolute database path below `/source`.

```yaml
services:
  backup:
    image: ghcr.io/housewatch-digital/backup-sidecar:0.2.0
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
`backup-sidecar run`. See the [Docker Compose](docs/platforms/docker-compose.md),
[Coolify](docs/platforms/coolify.md), and
[Kubernetes](docs/platforms/kubernetes.md) guides.

For PostgreSQL 16, use
`ghcr.io/housewatch-digital/backup-sidecar:0.2.0-postgres16` and follow the
[PostgreSQL guide](docs/engines/postgresql.md). Versioned tags are recommended in
production; the moving `postgres16` tag is also published.

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
5. Adds restore metadata under `.sqlite-backup` and, when applicable,
   `.backup-sidecar`.
6. Uploads the staged data to Restic.
7. Applies snapshot retention without pruning.
8. Runs executable post-backup hooks.
9. Records the snapshot ID and completion time under `/state`.

A failed run records its status and invokes failure hooks. See
[hooks](docs/hooks.md) for the hook contract.

## Commands

```text
backup-sidecar run
backup-sidecar idle
backup-sidecar daemon
backup-sidecar doctor
backup-sidecar snapshots
backup-sidecar check
backup-sidecar prune
backup-sidecar restore-latest /restore/rehearsal
backup-sidecar verify /restore/rehearsal
backup-sidecar health
backup-sidecar status
```

The existing `sqlite-backup` executable remains as a compatibility alias. Run
`backup-sidecar doctor` before the first backup. It validates the mounts,
configured databases, tools, and Restic access without creating a backup or
initializing a repository.

## Retention and health

The defaults retain 30 daily, 8 weekly, and 12 monthly snapshots. A normal backup
runs `restic forget` but does not reclaim repository data. Run
`backup-sidecar prune` weekly and `backup-sidecar check` monthly.

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

The test suite exercises live SQLite WAL-mode writes, multiple databases,
PostgreSQL custom-format dumps, PostgreSQL extensions, file-only backups, hooks,
restore verification, compatibility behavior, and a real local Restic repository
when Restic is installed.
