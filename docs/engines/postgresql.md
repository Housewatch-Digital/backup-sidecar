# PostgreSQL backups

Use the `postgres16` image for PostgreSQL 16 databases:

```text
ghcr.io/housewatch-digital/backup-sidecar:0.2.0-postgres16
```

The moving `postgres16` tag is convenient for testing, but a versioned tag makes
production upgrades deliberate. The base image remains SQLite- and file-focused.

## What the variant does

For every configured database, the image:

1. Connects with the standard libpq environment variables.
2. Confirms that the server and `pg_dump` major versions match by default.
3. Creates a custom-format, uncompressed logical dump with ownership and ACLs
   omitted.
4. Validates the archive with `pg_restore --list`.
5. Stores the dump and a JSON Lines manifest under
   `.backup-sidecar/postgresql` in the Restic snapshot.

The dump is left uncompressed so Restic can deduplicate and compress it. Each
database is dumped independently; the image does not promise one transactionally
consistent instant across multiple databases.

## Configuration

Set `POSTGRES_DATABASES` to a newline-separated list. Blank lines are ignored and
an empty value disables PostgreSQL backup hooks.

```text
POSTGRES_DATABASES=application
audit database
```

Use standard libpq variables for the connection:

| Variable | Purpose |
| --- | --- |
| `PGHOST` | Required PostgreSQL host or Compose service name |
| `PGPORT` | Port; defaults to `5432` |
| `PGUSER` | Required database role |
| `PGPASSWORD` | Password; convenient for platform-managed secrets |
| `PGPASSFILE` | Readable password file; preferable when secret files are available |
| `PGSSLMODE` and related `PGSSL*` variables | Optional TLS behavior |
| `PGCONNECT_TIMEOUT` | Connection timeout; defaults to 10 seconds |
| `POSTGRES_REQUIRE_MATCHING_MAJOR` | Require PostgreSQL 16 servers; defaults to `true` |

Create a least-privilege login role that can connect to every selected database
and read every object that must be recoverable. PostgreSQL permissions vary by
schema and version, so validate the exact role with `backup-sidecar doctor` and a
real backup. Never expose the password in `BACKUP_NAME`, database names, or
command arguments.

Setting `POSTGRES_REQUIRE_MATCHING_MAJOR=false` allows a deliberate client/server
major mismatch. This is an escape hatch, not the default compatibility policy.

## Scope and limitations

The variant creates logical database dumps. It does not include cluster roles,
role passwords, tablespaces, physical replication state, write-ahead logs, or a
physical copy of `PGDATA`. Keep role and infrastructure definitions in a separate
secured recovery process. Extensions are recorded by `pg_dump`, but the target
PostgreSQL server must have compatible extension packages installed before
restore.

Do not mount `PGDATA` below `/source`. A live data directory is not a valid
file-level backup. Mount application file volumes below `/source` only when they
also belong in the Restic snapshot.

## First-run validation

Run these commands in the sidecar container:

```sh
backup-sidecar doctor
backup-sidecar run
backup-sidecar snapshots
backup-sidecar restore-latest /restore/rehearsal
backup-sidecar verify /restore/rehearsal
```

`restore-latest` verifies the structure of every restored dump. It does not apply
dumps to a database. Complete a restore rehearsal against a disposable PostgreSQL
16 server by following the [restore runbook](../restore-runbook.md).

See the [Docker Compose example](../../examples/compose.postgres16.yaml) and the
[Coolify example](../../examples/compose.coolify-postgres16.yaml).
