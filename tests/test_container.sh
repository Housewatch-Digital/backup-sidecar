#!/bin/sh
set -eu

image="${BACKUP_TEST_IMAGE:-sqlite-backup-sidecar:dev}"
test_root="$(mktemp -d /tmp/sqlite-backup-container.XXXXXX)"
writer_container="sqlite-backup-writer-$$"

cleanup() {
  docker stop "$writer_container" >/dev/null 2>&1 || true
  docker run --rm \
    --entrypoint sh \
    -v "$test_root:/cleanup" \
    "$image" \
    -c 'rm -rf /cleanup/* /cleanup/.[!.]* /cleanup/..?*' >/dev/null 2>&1 || true
  rm -rf "$test_root" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

mkdir -p \
  "$test_root/cache" \
  "$test_root/repository" \
  "$test_root/restore" \
  "$test_root/source" \
  "$test_root/stage" \
  "$test_root/state"

docker run --rm \
  --entrypoint sqlite3 \
  -v "$test_root/source:/source" \
  "$image" \
  /source/application.db \
  "CREATE TABLE records(value TEXT NOT NULL); INSERT INTO records VALUES ('container-smoke'); PRAGMA journal_mode=WAL;"

docker run --rm -d \
  --name "$writer_container" \
  --entrypoint sh \
  -v "$test_root/source:/source" \
  "$image" \
  -c 'tail -f /dev/null | sqlite3 /source/application.db' >/dev/null

sleep 1

docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  -e BACKUP_NAME=container-smoke \
  -e SQLITE_DATABASES=/source/application.db \
  -e RESTIC_REPOSITORY=/repository \
  -e RESTIC_PASSWORD=container-test-password \
  -v "$test_root/source:/source:ro" \
  -v "$test_root/stage:/stage" \
  -v "$test_root/state:/state" \
  -v "$test_root/cache:/cache" \
  -v "$test_root/repository:/repository" \
  -v "$test_root/restore:/restore" \
  "$image" run

docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  -e BACKUP_NAME=container-smoke \
  -e RESTIC_REPOSITORY=/repository \
  -e RESTIC_PASSWORD=container-test-password \
  -v "$test_root/source:/source:ro" \
  -v "$test_root/stage:/stage" \
  -v "$test_root/state:/state" \
  -v "$test_root/cache:/cache" \
  -v "$test_root/repository:/repository" \
  -v "$test_root/restore:/restore" \
  "$image" restore-latest /restore/rehearsal

restored_value="$(
  docker run --rm \
    --entrypoint sqlite3 \
    -v "$test_root/restore:/restore:ro" \
    "$image" \
    'file:/restore/rehearsal/application.db?immutable=1' \
    'SELECT value FROM records;'
)"
[ "$restored_value" = "container-smoke" ]
