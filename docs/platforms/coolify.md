# Coolify deployment

Use the sidecar as another service in the application's Docker Compose stack.
Start with [`examples/compose.coolify.yaml`](../../examples/compose.coolify.yaml)
and replace the example application image and volume paths.

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
mount is read-only. Run `sqlite-backup doctor` while the application is running.
If a cleanly closed WAL database has removed those files, see the read-only WAL
note in the main README before scheduling backups.

## Add scheduled tasks

Run the container with `command: ["idle"]`, then add these tasks to the backup
service:

| Task | Command | Example schedule |
| --- | --- | --- |
| Backup | `sqlite-backup run` | `0 5 * * *` |
| Repository prune | `sqlite-backup prune` | `30 6 * * 0` |
| Repository check | `sqlite-backup check` | `0 7 1 * *` |

Choose the backup schedule from the acceptable recovery point. Hourly backups
limit ordinary data loss to roughly one hour; daily backups limit it to roughly
one day. Stagger jobs across deployments.

## Verify the deployment

1. Run `sqlite-backup doctor` with Coolify's Execute Now action.
2. Run `sqlite-backup run`.
3. Record the returned Restic snapshot ID.
4. Run `sqlite-backup snapshots`.
5. Restore into an empty path below `/restore`.
6. Inspect the result and run `sqlite-backup verify`.

The container health check remains unhealthy until the first successful backup.
