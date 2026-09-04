FROM alpine:3.24 AS base

ARG VERSION=0.3.0

LABEL org.opencontainers.image.title="Backup Sidecar" \
      org.opencontainers.image.description="Engine-aware database and file-volume backups to Restic repositories" \
      org.opencontainers.image.source="https://github.com/Housewatch-Digital/backup-sidecar" \
      org.opencontainers.image.version="$VERSION"

RUN apk add --no-cache \
      ca-certificates \
      jq \
      restic \
      rsync \
      sqlite \
      tzdata \
      util-linux \
    && update-ca-certificates \
    && mkdir -p \
      /cache \
      /hooks/doctor.d \
      /hooks/failure.d \
      /hooks/post-backup.d \
      /hooks/pre-backup.d \
      /hooks/verify.d \
      /restore \
      /source \
      /stage \
      /state

COPY bin/sqlite-backup /usr/local/bin/sqlite-backup
COPY bin/backup-sidecar /usr/local/bin/backup-sidecar

RUN chmod 0755 /usr/local/bin/sqlite-backup /usr/local/bin/backup-sidecar

ENV BACKUP_SIDECAR_VERSION="$VERSION" \
    BACKUP_SOURCE_DIR=/source \
    BACKUP_STAGE_ROOT=/stage \
    BACKUP_STATE_DIR=/state \
    BACKUP_CACHE_DIR=/cache \
    RESTORE_ROOT=/restore

VOLUME ["/cache", "/restore", "/stage", "/state"]

HEALTHCHECK --interval=5m --timeout=10s --start-period=30m --retries=3 \
  CMD ["backup-sidecar", "health"]

ENTRYPOINT ["backup-sidecar"]
CMD ["idle"]

FROM base AS postgres

ARG POSTGRES_MAJOR=18

RUN apk add --no-cache "postgresql${POSTGRES_MAJOR}-client"

LABEL org.opencontainers.image.title="Backup Sidecar for PostgreSQL ${POSTGRES_MAJOR}" \
      org.opencontainers.image.description="PostgreSQL ${POSTGRES_MAJOR}, SQLite, and file-volume backups to Restic repositories"

ENV RESTIC_TAG_PREFIX=backup-sidecar

COPY variants/postgres/lib/postgresql.sh /usr/local/lib/backup-sidecar/postgresql.sh
COPY variants/postgres/hooks/doctor.d/10-postgresql /hooks/doctor.d/10-postgresql
COPY variants/postgres/hooks/pre-backup.d/10-postgresql /hooks/pre-backup.d/10-postgresql
COPY variants/postgres/hooks/verify.d/10-postgresql /hooks/verify.d/10-postgresql

RUN chmod 0755 \
      /hooks/doctor.d/10-postgresql \
      /hooks/pre-backup.d/10-postgresql \
      /hooks/verify.d/10-postgresql \
    && chmod 0644 /usr/local/lib/backup-sidecar/postgresql.sh

FROM base AS default
