# Docker Compose deployment

Use `daemon` mode when the sidecar should schedule its own backups. Use `idle`
mode when a host scheduler or container platform will run `sqlite-backup run`.

## Multiple volume example

```yaml
services:
  backup:
    image: ghcr.io/housewatch-digital/backup-sidecar:0.1.1
    command: ["daemon"]
    restart: unless-stopped
    init: true
    read_only: true
    environment:
      BACKUP_NAME: application-production
      SQLITE_DATABASES: |-
        /source/app/main.db
        /source/audit/audit.sqlite
      RESTIC_REPOSITORY: ${RESTIC_REPOSITORY}
      RESTIC_PASSWORD: ${RESTIC_PASSWORD}
      BACKUP_INITIAL_DELAY_SECONDS: 60
      BACKUP_INTERVAL_SECONDS: 3600
    volumes:
      - app-data:/source/app:ro
      - audit-data:/source/audit:ro
      - backup-cache:/cache
      - backup-stage:/stage
      - backup-state:/state
      - backup-restore:/restore
    tmpfs:
      - /tmp:size=64m,noexec,nosuid,nodev
    security_opt:
      - no-new-privileges:true
```

Add the credential variables required by the chosen Restic backend. Run a
configuration check before starting the schedule:

```sh
docker compose run --rm backup doctor
```

For a restore rehearsal:

```sh
docker compose run --rm backup restore-latest /restore/rehearsal
```

Do not mount application data read-write unless a pre-backup hook must create an
export. Prefer a separate writable export volume for that case.
