# Coolify deployment

Use the sidecar as another service in the application's Docker Compose stack.
Start with [`examples/compose.coolify.yaml`](../../examples/compose.coolify.yaml)
for SQLite/files or
[`examples/compose.coolify-postgres16.yaml`](../../examples/compose.coolify-postgres16.yaml)
for PostgreSQL 16, then replace the example application and database settings.

## Mount the source data

Mount application volumes read-only at distinct paths below `/source`:

```yaml
volumes:
  - database-data:/source/database:ro
  - uploads:/source/uploads:ro
```

Then list each SQLite database by its path inside the sidecar:

```text
SQLITE_DATABASES=/source/database/application.db
```

Leave `SQLITE_DATABASES` empty for a file-only backup. Do not include live
PostgreSQL or MySQL data directories.

## Configure storage

Set these as Coolify environment variables or secrets:

```text
BACKUP_NAME=application-production
RESTIC_REPOSITORY=<repository-url>
RESTIC_PASSWORD=<repository-password>
```

Add the credential variables required by the chosen Restic backend. Use a unique
repository path and least-privilege storage credential for each environment.

## Add persistent sidecar volumes

Keep `/state`, `/cache`, and `/stage` writable. Mount a separate empty volume at
`/restore` for recovery rehearsals. The application data below `/source` should
remain read-only.

The default container filesystem can remain read-only when `/tmp` is a writable
`tmpfs`, as shown in the example.

SQLite WAL mode also needs its existing `-wal` and `-shm` files when the source
mount is read-only. Run `backup-sidecar doctor` while the application is running.
If a cleanly closed WAL database has removed those files, see the read-only WAL
note in the main README before scheduling backups.

## Configure PostgreSQL 16

Use the image tag ending in `-postgres16`, set `PGHOST` to the PostgreSQL Compose
service name, and set `POSTGRES_DATABASES` to the database names to dump. The
sidecar connects across the internal Compose network; do not publish PostgreSQL's
port for the backup container.

Use Coolify-managed environment variables or secrets for `PGUSER`, `PGPASSWORD`,
the Restic password, and storage credentials. The example reuses the application
database role for portability. A dedicated read-only backup role is preferable
when its permissions have been tested against every schema and extension.

Do not mount the PostgreSQL data volume into the backup container. The variant
runs `pg_dump` against the live server, verifies the resulting custom-format dump,
and then stores it in Restic. PostgreSQL remains online during the dump.

## Add scheduled tasks

Run the container with `command: ["idle"]`, then add these tasks to the backup
service:

| Task | Command | Example schedule |
| --- | --- | --- |
| Backup | `backup-sidecar run` | `0 */6 * * *` |
| Repository prune | `backup-sidecar prune` | `30 6 * * 0` |
| Repository check | `backup-sidecar check` | `0 7 1 * *` |

Choose the backup schedule from the acceptable recovery point. Hourly backups
limit ordinary data loss to roughly one hour; daily backups limit it to roughly
one day. Stagger jobs across deployments. In a multi-container resource, select
the `backup` service/container as the scheduled-task target and set a timeout long
enough for the largest dump and Restic upload.

Coolify's scheduled task runs inside the already-running backup container. Keep
the service in `idle` mode; do not also enable `daemon` mode or each deployment
will have two independent schedules.

## Relationship to Coolify backups

Coolify's native PostgreSQL database backup also uses `pg_dump` custom format and
is a good choice when Coolify exposes a Backups page for that database resource.
A PostgreSQL service embedded inside a Git Compose deployment may not expose that
page. The PostgreSQL sidecar covers that case and can apply the same encrypted
Restic, retention, verification, and restore workflow across many applications.

A Coolify archive of the live PostgreSQL volume is not a replacement for either
logical backup method. If you separately archive file volumes, keep containers
running only when those files tolerate file-level consistency; stop writers when
the application requires a single point-in-time filesystem image.

## Verify the deployment

1. Run `backup-sidecar doctor` with Coolify's Execute Now action.
2. Run `backup-sidecar run`.
3. Record the returned Restic snapshot ID.
4. Run `backup-sidecar snapshots`.
5. Restore into an empty path below `/restore`.
6. Inspect the result and run `backup-sidecar verify`.
7. For PostgreSQL, apply the dump to a disposable PostgreSQL 16 server and run
   application-level checks.

The container health check remains unhealthy until the first successful backup.
