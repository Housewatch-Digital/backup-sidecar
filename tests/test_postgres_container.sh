#!/bin/sh
set -eu

backup_image="${BACKUP_POSTGRES_TEST_IMAGE:-sqlite-backup-sidecar:postgres16-dev}"
postgres_image="${POSTGRES_TEST_IMAGE:-pgvector/pgvector:pg16}"
test_root="$(mktemp -d /tmp/backup-sidecar-postgres.XXXXXX)"
network="backup-sidecar-postgres-$$"
source_container="backup-sidecar-postgres-source-$$"
restore_container="backup-sidecar-postgres-restore-$$"

cleanup() {
  docker rm -f "$source_container" "$restore_container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker run --rm \
    --entrypoint sh \
    -v "$test_root:/cleanup" \
    "$backup_image" \
    -c 'rm -rf /cleanup/* /cleanup/.[!.]* /cleanup/..?*' >/dev/null 2>&1 || true
  rm -rf "$test_root" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

wait_for_postgres() {
  container="$1"
  attempts=0
  until docker exec "$container" \
    psql -U protocolpal -d protocolpal -At -c 'SELECT 1;' >/dev/null 2>&1; do
    attempts="$((attempts + 1))"
    [ "$attempts" -lt 60 ] || {
      docker logs "$container" >&2
      return 1
    }
    sleep 1
  done
}

mkdir -p \
  "$test_root/cache" \
  "$test_root/repository" \
  "$test_root/restore" \
  "$test_root/source" \
  "$test_root/stage" \
  "$test_root/state"

docker network create "$network" >/dev/null
docker run --rm -d \
  --name "$source_container" \
  --network "$network" \
  --network-alias postgres-source \
  -e POSTGRES_DB=protocolpal \
  -e POSTGRES_USER=protocolpal \
  -e POSTGRES_PASSWORD=container-test-password \
  "$postgres_image" >/dev/null
wait_for_postgres "$source_container"

docker exec "$source_container" \
  psql -U protocolpal -d protocolpal -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION vector; CREATE TABLE records(label text NOT NULL, embedding vector(3) NOT NULL); INSERT INTO records VALUES ('sample', '[1,2,3]');" >/dev/null

docker run --rm \
  --network "$network" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  -e BACKUP_NAME=postgres-container-smoke \
  -e SQLITE_DATABASES= \
  -e POSTGRES_DATABASES=protocolpal \
  -e PGHOST=postgres-source \
  -e PGPORT=5432 \
  -e PGUSER=protocolpal \
  -e PGPASSWORD=container-test-password \
  -e RESTIC_REPOSITORY=/repository \
  -e RESTIC_PASSWORD=restic-container-test-password \
  -v "$test_root/source:/source:ro" \
  -v "$test_root/stage:/stage" \
  -v "$test_root/state:/state" \
  -v "$test_root/cache:/cache" \
  -v "$test_root/repository:/repository" \
  -v "$test_root/restore:/restore" \
  "$backup_image" run

docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  -e BACKUP_NAME=postgres-container-smoke \
  -e RESTIC_REPOSITORY=/repository \
  -e RESTIC_PASSWORD=restic-container-test-password \
  -v "$test_root/source:/source:ro" \
  -v "$test_root/stage:/stage" \
  -v "$test_root/state:/state" \
  -v "$test_root/cache:/cache" \
  -v "$test_root/repository:/repository" \
  -v "$test_root/restore:/restore" \
  "$backup_image" restore-latest /restore/rehearsal

docker run --rm -d \
  --name "$restore_container" \
  --network "$network" \
  --network-alias postgres-restore \
  -e POSTGRES_DB=protocolpal \
  -e POSTGRES_USER=protocolpal \
  -e POSTGRES_PASSWORD=container-test-password \
  "$postgres_image" >/dev/null
wait_for_postgres "$restore_container"

docker run --rm \
  --network "$network" \
  --entrypoint pg_restore \
  -e PGPASSWORD=container-test-password \
  -v "$test_root/restore:/restore:ro" \
  "$backup_image" \
  --host=postgres-restore \
  --port=5432 \
  --username=protocolpal \
  --dbname=protocolpal \
  --no-owner \
  --no-acl \
  --exit-on-error \
  /restore/rehearsal/.backup-sidecar/postgresql/0001.dump

restored_value="$(
  docker exec "$restore_container" \
    psql -U protocolpal -d protocolpal -At \
    -c "SELECT label || ':' || embedding::text FROM records;"
)"
[ "$restored_value" = 'sample:[1,2,3]' ]
