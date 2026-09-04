from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "variants" / "postgres" / "lib" / "postgresql.sh"
DOCTOR_HOOK = ROOT / "variants" / "postgres" / "hooks" / "doctor.d" / "10-postgresql"
BACKUP_HOOK = ROOT / "variants" / "postgres" / "hooks" / "pre-backup.d" / "10-postgresql"
VERIFY_HOOK = ROOT / "variants" / "postgres" / "hooks" / "verify.d" / "10-postgresql"


class PostgresHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.payload = self.root / "payload"
        self.bin.mkdir()
        self.payload.mkdir()
        self.command_log = self.root / "commands.log"
        self._write_fake_commands()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_command(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)

    def _write_fake_commands(self) -> None:
        self._write_command(
            "pg_dump",
            textwrap.dedent(
                """\
                if [ "${1:-}" = "--version" ]; then
                  printf '%s\n' 'pg_dump (PostgreSQL) 16.11'
                  exit 0
                fi
                [ "${FAKE_PG_DUMP_FAIL:-false}" != true ] || exit 9
                output=""
                database=""
                for argument in "$@"; do
                  case "$argument" in
                    --file=*) output="${argument#--file=}" ;;
                    --dbname=*) database="${argument#--dbname=}" ;;
                  esac
                done
                [ -n "$output" ]
                [ -n "$database" ]
                printf 'valid-dump:%s\n' "$database" > "$output"
                printf 'pg_dump:%s\n' "$database" >> "$FAKE_COMMAND_LOG"
                """
            ),
        )
        self._write_command(
            "pg_restore",
            textwrap.dedent(
                """\
                [ "${1:-}" = "--list" ]
                grep '^valid-dump:' "$2" >/dev/null
                printf 'pg_restore:%s\n' "$2" >> "$FAKE_COMMAND_LOG"
                """
            ),
        )
        self._write_command(
            "psql",
            textwrap.dedent(
                """\
                database=""
                command=""
                for argument in "$@"; do
                  case "$argument" in
                    --dbname=*) database="${argument#--dbname=}" ;;
                    --command=*) command="${argument#--command=}" ;;
                  esac
                done
                printf 'psql:%s\n' "$database" >> "$FAKE_COMMAND_LOG"
                case "$command" in
                  'SHOW server_version_num;') printf '%s\n' "${FAKE_SERVER_VERSION_NUM:-160011}" ;;
                  'SHOW server_version;') printf '%s\n' "${FAKE_SERVER_VERSION:-16.11}" ;;
                  *) exit 8 ;;
                esac
                """
            ),
        )

    def _environment(self, **overrides: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin}:{environment['PATH']}",
                "POSTGRES_HELPER_FILE": str(HELPER),
                "POSTGRES_DATABASES": "protocolpal",
                "PGHOST": "database.internal",
                "PGPORT": "5432",
                "PGUSER": "backup_user",
                "PGPASSWORD": "never-print-this-password",
                "BACKUP_PAYLOAD_DIR": str(self.payload),
                "BACKUP_RESTORE_DIR": str(self.payload),
                "FAKE_COMMAND_LOG": str(self.command_log),
            }
        )
        environment.update(overrides)
        return environment

    def _run(
        self,
        hook: Path,
        *,
        check: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(hook)],
            env=environment or self._environment(),
            check=check,
            capture_output=True,
            text=True,
        )

    def test_doctor_validates_each_database_without_printing_password(self) -> None:
        result = self._run(
            DOCTOR_HOOK,
            environment=self._environment(POSTGRES_DATABASES="primary\naudit database"),
        )

        self.assertIn("database=primary", result.stderr)
        self.assertIn("database=audit database", result.stderr)
        self.assertNotIn("never-print-this-password", result.stderr)

    def test_backup_creates_verified_custom_dumps_and_json_metadata(self) -> None:
        self._run(
            BACKUP_HOOK,
            environment=self._environment(POSTGRES_DATABASES="primary\naudit database"),
        )

        metadata_dir = self.payload / ".backup-sidecar" / "postgresql"
        records = [json.loads(line) for line in (metadata_dir / "databases.jsonl").read_text().splitlines()]
        self.assertEqual(["primary", "audit database"], [record["database"] for record in records])
        self.assertEqual(
            [
                ".backup-sidecar/postgresql/0001.dump",
                ".backup-sidecar/postgresql/0002.dump",
            ],
            [record["path"] for record in records],
        )
        for record in records:
            self.assertTrue((self.payload / record["path"]).is_file())

        self._run(VERIFY_HOOK)

    def test_version_mismatch_fails_by_default_and_can_be_allowed(self) -> None:
        mismatch = self._run(
            DOCTOR_HOOK,
            check=False,
            environment=self._environment(FAKE_SERVER_VERSION_NUM="170001", FAKE_SERVER_VERSION="17.1"),
        )
        self.assertNotEqual(0, mismatch.returncode)
        self.assertIn("uses PostgreSQL 17 but pg_dump is PostgreSQL 16", mismatch.stderr)

        allowed = self._run(
            DOCTOR_HOOK,
            environment=self._environment(
                FAKE_SERVER_VERSION_NUM="150013",
                FAKE_SERVER_VERSION="15.13",
                POSTGRES_REQUIRE_MATCHING_MAJOR="false",
            ),
        )
        self.assertEqual(0, allowed.returncode)

    def test_failed_dump_does_not_produce_a_complete_archive(self) -> None:
        result = self._run(
            BACKUP_HOOK,
            check=False,
            environment=self._environment(FAKE_PG_DUMP_FAIL="true"),
        )

        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.payload / ".backup-sidecar" / "postgresql" / "0001.dump").exists())

    def test_empty_database_list_disables_all_postgres_hooks(self) -> None:
        environment = self._environment(POSTGRES_DATABASES="")
        self._run(DOCTOR_HOOK, environment=environment)
        self._run(BACKUP_HOOK, environment=environment)
        self._run(VERIFY_HOOK, environment=environment)
        self.assertFalse((self.payload / ".backup-sidecar").exists())


if __name__ == "__main__":
    unittest.main()
