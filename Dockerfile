FROM alpine:3.24

ARG VERSION=0.1.1

LABEL org.opencontainers.image.title="SQLite Backup Sidecar" \
      org.opencontainers.image.description="SQLite-aware and file-volume backups to Restic repositories" \
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
      /hooks/failure.d \
      /hooks/post-backup.d \
      /hooks/pre-backup.d \
      /restore \
      /source \
      /stage \
      /state

COPY bin/sqlite-backup /usr/local/bin/sqlite-backup

RUN chmod 0755 /usr/local/bin/sqlite-backup

ENV BACKUP_SIDECAR_VERSION="$VERSION" \
    BACKUP_SOURCE_DIR=/source \
    BACKUP_STAGE_ROOT=/stage \
    BACKUP_STATE_DIR=/state \
    BACKUP_CACHE_DIR=/cache \
    RESTORE_ROOT=/restore

VOLUME ["/cache", "/restore", "/stage", "/state"]

HEALTHCHECK --interval=5m --timeout=10s --start-period=30m --retries=3 \
  CMD ["sqlite-backup", "health"]

ENTRYPOINT ["sqlite-backup"]
CMD ["idle"]
