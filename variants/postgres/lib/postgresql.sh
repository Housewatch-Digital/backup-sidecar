#!/bin/sh

: "${POSTGRES_DATABASES:=}"
: "${POSTGRES_REQUIRE_MATCHING_MAJOR:=true}"
: "${PGPORT:=5432}"
: "${PGCONNECT_TIMEOUT:=10}"

export PGPORT PGCONNECT_TIMEOUT

postgres_log() {
  printf '%s\n' "PostgreSQL: $*" >&2
}

postgres_die() {
  postgres_log "ERROR: $*"
  return 1
}

postgres_enabled() {
  [ -n "$POSTGRES_DATABASES" ]
}

postgres_require_command() {
  command -v "$1" >/dev/null 2>&1 || postgres_die "$1 is not installed"
}

postgres_matching_major_required() {
  case "$POSTGRES_REQUIRE_MATCHING_MAJOR" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    0|false|FALSE|no|NO|off|OFF) return 1 ;;
    *) postgres_die "POSTGRES_REQUIRE_MATCHING_MAJOR must be true or false" ;;
  esac
}

postgres_client_version() {
  pg_dump --version | sed -n 's/^pg_dump (PostgreSQL) \([0-9][0-9.]*\).*/\1/p'
}

postgres_client_major() {
  version="$(postgres_client_version)"
  [ -n "$version" ] || postgres_die "could not determine pg_dump version"
  printf '%s\n' "${version%%.*}"
}

postgres_server_version_number() {
  database="$1"
  psql \
    --no-psqlrc \
    --tuples-only \
    --no-align \
    --set=ON_ERROR_STOP=1 \
    --dbname="$database" \
    --command='SHOW server_version_num;' | tr -d '[:space:]'
}

postgres_server_version() {
  database="$1"
  psql \
    --no-psqlrc \
    --tuples-only \
    --no-align \
    --set=ON_ERROR_STOP=1 \
    --dbname="$database" \
    --command='SHOW server_version;' | sed -n '1{s/^[[:space:]]*//;s/[[:space:]]*$//;p;}'
}

postgres_validate_database() {
  database="$1"
  client_major="$2"
  server_version_number="$(postgres_server_version_number "$database")"

  case "$server_version_number" in
    ''|*[!0-9]*) postgres_die "database $database returned an invalid server version" ;;
  esac

  server_major="$((server_version_number / 10000))"
  if postgres_matching_major_required && [ "$client_major" -ne "$server_major" ]; then
    postgres_die "database $database uses PostgreSQL $server_major but pg_dump is PostgreSQL $client_major"
  fi

  postgres_log "connection verified: database=$database server_major=$server_major client_major=$client_major"
}

postgres_validate_configuration() {
  postgres_enabled || return 0

  postgres_require_command pg_dump
  postgres_require_command pg_restore
  postgres_require_command psql
  postgres_require_command jq

  [ -n "${PGHOST:-}" ] || postgres_die "PGHOST is required when POSTGRES_DATABASES is set"
  [ -n "${PGUSER:-}" ] || postgres_die "PGUSER is required when POSTGRES_DATABASES is set"
  case "$PGPORT" in
    ''|*[!0-9]*) postgres_die "PGPORT must be a positive integer" ;;
    0) postgres_die "PGPORT must be a positive integer" ;;
  esac
  if [ -n "${PGPASSFILE:-}" ] && [ ! -r "$PGPASSFILE" ]; then
    postgres_die "PGPASSFILE is not readable: $PGPASSFILE"
  fi

  # Validate the boolean even when the client and server versions happen to match.
  if postgres_matching_major_required; then
    :
  else
    case "$POSTGRES_REQUIRE_MATCHING_MAJOR" in
      0|false|FALSE|no|NO|off|OFF) ;;
      *) return 1 ;;
    esac
  fi

  client_major="$(postgres_client_major)"
  database_count=0
  while IFS= read -r database || [ -n "$database" ]; do
    [ -n "$database" ] || continue
    database_count="$((database_count + 1))"
    postgres_validate_database "$database" "$client_major"
  done <<EOF
$POSTGRES_DATABASES
EOF
  [ "$database_count" -gt 0 ] || postgres_die "POSTGRES_DATABASES does not contain a database name"
}
