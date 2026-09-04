from __future__ import annotations

import os
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import textwrap
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "sqlite-backup"


class BackupSidecarTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.stage = self.root / "stage"
        self.state = self.root / "state"
        self.cache = self.root / "cache"
        self.capture = self.root / "capture"
        self.restore_root = self.root / "restore"
        self.fake_bin = self.root / "bin"
        self.pre_hooks = self.root / "hooks" / "pre-backup.d"
        self.post_hooks = self.root / "hooks" / "post-backup.d"
        self.failure_hooks = self.root / "hooks" / "failure.d"
        self.doctor_hooks = self.root / "hooks" / "doctor.d"
        self.verify_hooks = self.root / "hooks" / "verify.d"
        self.hook_log = self.root / "hook.log"
        for directory in (
            self.source,
            self.stage,
            self.state,
            self.cache,
            self.restore_root,
            self.fake_bin,
            self.pre_hooks,
            self.post_hooks,
            self.failure_hooks,
            self.doctor_hooks,
            self.verify_hooks,
        ):
            directory.mkdir(parents=True)

        self.database = self.source / "application data" / "application.db"
        self._create_database(self.database, "events")

        (self.source / "uploads").mkdir()
        (self.source / "uploads" / "report 2026.txt").write_text("completed\n")
        (self.source / "cache").mkdir()
        (self.source / "cache" / "rebuildable.txt").write_text("skip\n")
        self._write_fake_commands()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _create_database(path: Path, table: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(f"INSERT INTO {table}(value) VALUES ('initial')")
            connection.commit()

    def _write_fake_commands(self) -> None:
        restic = self.fake_bin / "restic"
        restic.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                set -eu
                command_name="$1"
                shift
                case "$command_name" in
                  cat) exit "${FAKE_RESTIC_CAT_STATUS:-0}" ;;
                  init) exit 0 ;;
                  backup)
                    rm -rf "$FAKE_RESTIC_CAPTURE"
                    mkdir -p "$FAKE_RESTIC_CAPTURE"
                    cp -R . "$FAKE_RESTIC_CAPTURE"/
                    printf '%s\\n' '{"message_type":"summary","snapshot_id":"0123456789abcdef"}'
                    ;;
                  snapshots)
                    tag=""
                    json=false
                    while [ "$#" -gt 0 ]; do
                      case "$1" in
                        --tag) shift; tag="$1" ;;
                        --json) json=true ;;
                      esac
                      shift
                    done
                    available=false
                    case "$tag" in
                      sqlite-backup:*|backup-sidecar:*) [ "${FAKE_RESTIC_NEW_SNAPSHOTS:-true}" = true ] && available=true ;;
                    esac
                    if [ "$json" = true ]; then
                      if [ "$available" = true ]; then
                        printf '%s\\n' '[{"id":"0123456789abcdef"}]'
                      else
                        printf '%s\\n' '[]'
                      fi
                    elif [ "$available" = true ]; then
                      printf '%s\\n' '01234567 fake snapshot'
                    fi
                    ;;
                  forget|prune|check) exit 0 ;;
                  restore)
                    target=""
                    tag=""
                    while [ "$#" -gt 0 ]; do
                      case "$1" in
                        --target) shift; target="$1" ;;
                        --tag) shift; tag="$1" ;;
                      esac
                      shift
                    done
                    [ -n "$target" ]
                    printf '%s\\n' "$tag" > "$FAKE_RESTIC_SELECTED_TAG"
                    mkdir -p "$target"
                    cp -R "$FAKE_RESTIC_CAPTURE"/. "$target"/
                    ;;
                  *)
                    echo "unsupported fake restic command: $command_name" >&2
                    exit 2
                    ;;
                esac
                """
            )
        )
        restic.chmod(0o755)

        flock = self.fake_bin / "flock"
        flock.write_text("#!/bin/sh\nexit 0\n")
        flock.chmod(0o755)

    def _environment(self, **overrides: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.fake_bin}:{ROOT / 'bin'}:{environment['PATH']}",
                "BACKUP_NAME": "test-application",
                "BACKUP_SOURCE_DIR": str(self.source),
                "BACKUP_STAGE_ROOT": str(self.stage),
                "BACKUP_STATE_DIR": str(self.state),
                "BACKUP_CACHE_DIR": str(self.cache),
                "BACKUP_EXCLUDES": "/cache/",
                "SQLITE_DATABASES": str(self.database),
                "RESTIC_REPOSITORY": "fake:test",
                "RESTIC_PASSWORD": "test-password",
                "RESTORE_ROOT": str(self.restore_root),
                "BACKUP_HOOK_PRE_DIR": str(self.pre_hooks),
                "BACKUP_HOOK_POST_DIR": str(self.post_hooks),
                "BACKUP_HOOK_FAILURE_DIR": str(self.failure_hooks),
                "BACKUP_HOOK_DOCTOR_DIR": str(self.doctor_hooks),
                "BACKUP_HOOK_VERIFY_DIR": str(self.verify_hooks),
                "FAKE_RESTIC_CAPTURE": str(self.capture),
                "FAKE_RESTIC_SELECTED_TAG": str(self.root / "selected-tag"),
                "HOOK_LOG": str(self.hook_log),
                "BACKUP_MAX_AGE_SECONDS": "3600",
            }
        )
        environment.update(overrides)
        return environment

    def _run(
        self,
        *arguments: str,
        check: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), *arguments],
            env=environment or self._environment(),
            check=check,
            capture_output=True,
            text=True,
        )

    def _write_hook(self, directory: Path, name: str, body: str) -> None:
        hook = directory / name
        hook.write_text(f"#!/bin/sh\nset -eu\n{body}\n")
        hook.chmod(0o755)

    def _write_fake_rsync(self) -> None:
        real_rsync = shutil.which("rsync")
        self.assertIsNotNone(real_rsync)
        fake_rsync = self.fake_bin / "rsync"
        fake_rsync.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                {shlex.quote(real_rsync or '')} "$@"
                real_status="$?"
                [ "$real_status" -eq 0 ] || exit "$real_status"
                forced_status="${{FAKE_RSYNC_STATUS:-0}}"
                [ "$forced_status" -eq 24 ] && printf '%s\n' 'file has vanished: fake temporary file' >&2
                exit "$forced_status"
                """
            )
        )
        fake_rsync.chmod(0o755)

    def test_shell_syntax(self) -> None:
        result = subprocess.run(
            ["sh", "-n", str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)

    def test_version(self) -> None:
        result = self._run("version")
        self.assertEqual("0.2.0\n", result.stdout)

    def test_live_wal_backup_and_restore(self) -> None:
        stop = threading.Event()

        def write_continuously() -> None:
            counter = 0
            while not stop.is_set():
                try:
                    with closing(sqlite3.connect(self.database, timeout=1)) as connection:
                        connection.execute(
                            "INSERT INTO events(value) VALUES (?)", (f"event-{counter}",)
                        )
                        connection.commit()
                    counter += 1
                except sqlite3.OperationalError:
                    time.sleep(0.005)

        writer = threading.Thread(target=write_continuously, daemon=True)
        writer.start()
        try:
            result = self._run("run")
        finally:
            stop.set()
            writer.join(timeout=2)

        self.assertIn("0123456789abcdef", result.stderr)
        captured_database = self.capture / "application data" / "application.db"
        self.assertTrue(captured_database.is_file())
        with closing(sqlite3.connect(captured_database)) as connection:
            self.assertEqual("ok", connection.execute("PRAGMA quick_check").fetchone()[0])
            self.assertGreaterEqual(
                connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1
            )

        self.assertEqual(
            "completed\n", (self.capture / "uploads" / "report 2026.txt").read_text()
        )
        self.assertFalse((self.capture / "cache").exists())
        self.assertFalse((captured_database.parent / "application.db-wal").exists())
        self.assertTrue((self.capture / ".sqlite-backup" / "manifest").is_file())
        self.assertIn(
            "snapshot_id=0123456789abcdef", (self.state / "last-success").read_text()
        )

        health = self._run("health")
        self.assertIn("Backup health is current", health.stderr)

        restored = self.restore_root / "rehearsal"
        restore_result = self._run("restore-latest", str(restored))
        self.assertIn("Restore verification completed", restore_result.stderr)
        self.assertTrue((restored / "application data" / "application.db").is_file())

    def test_multiple_databases_and_volume_subdirectories(self) -> None:
        second = self.source / "audit volume" / "audit.sqlite"
        self._create_database(second, "audit_events")
        environment = self._environment(
            SQLITE_DATABASES=f"{self.database}\n{second}",
        )

        self._run("run", environment=environment)

        for database, table in (
            (self.capture / "application data" / "application.db", "events"),
            (self.capture / "audit volume" / "audit.sqlite", "audit_events"),
        ):
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(1, connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        sqlite_paths = (self.capture / ".sqlite-backup" / "sqlite-paths").read_text()
        self.assertIn("application data/application.db", sqlite_paths)
        self.assertIn("audit volume/audit.sqlite", sqlite_paths)

    def test_file_only_backup(self) -> None:
        self._run("run", environment=self._environment(SQLITE_DATABASES=""))
        self.assertTrue((self.capture / "application data" / "application.db").is_file())
        self.assertEqual("", (self.capture / ".sqlite-backup" / "sqlite-paths").read_text())

    def test_restic_tag_prefix_can_select_a_variant_namespace(self) -> None:
        environment = self._environment(RESTIC_TAG_PREFIX="backup-sidecar")
        self._run("run", environment=environment)
        restored = self.restore_root / "generic-tag"
        self._run("restore-latest", str(restored), environment=environment)
        self.assertEqual(
            "backup-sidecar:test-application\n",
            (self.root / "selected-tag").read_text(),
        )

    def test_vanished_source_files_warn_and_allow_backup(self) -> None:
        self._write_fake_rsync()

        result = self._run(
            "run",
            environment=self._environment(FAKE_RSYNC_STATUS="24"),
        )

        self.assertIn("source files vanished while staging", result.stderr)
        self.assertTrue((self.capture / "uploads" / "report 2026.txt").is_file())
        self.assertTrue((self.state / "last-success").is_file())
        self.assertFalse((self.state / "last-failure").exists())

    def test_other_rsync_errors_fail_backup(self) -> None:
        self._write_fake_rsync()

        result = self._run(
            "run",
            check=False,
            environment=self._environment(FAKE_RSYNC_STATUS="23"),
        )

        self.assertEqual(23, result.returncode)
        self.assertFalse(self.capture.exists())
        self.assertIn("exit_code=23", (self.state / "last-failure").read_text())
        self.assertFalse((self.state / "last-success").exists())

    def test_doctor_accepts_backend_credentials_managed_by_restic(self) -> None:
        environment = self._environment(RESTIC_REPOSITORY="s3:https://example.test/bucket")
        environment.pop("AWS_ACCESS_KEY_ID", None)
        environment.pop("AWS_SECRET_ACCESS_KEY", None)
        result = self._run("doctor", environment=environment)
        self.assertIn("Configuration check completed", result.stderr)

    def test_hooks_run_in_order_and_receive_context(self) -> None:
        self._write_hook(
            self.pre_hooks,
            "20-second",
            'printf "pre-20:%s\\n" "$BACKUP_RUN_DIR" >> "$HOOK_LOG"',
        )
        self._write_hook(
            self.pre_hooks,
            "10-first",
            'printf "pre-10:%s\\n" "$BACKUP_RUN_DIR" >> "$HOOK_LOG"',
        )
        self._write_hook(
            self.post_hooks,
            "10-complete",
            'printf "post:%s\\n" "$BACKUP_SNAPSHOT_ID" >> "$HOOK_LOG"',
        )

        self._run("run")

        lines = self.hook_log.read_text().splitlines()
        self.assertTrue(lines[0].startswith("pre-10:"))
        self.assertTrue(lines[1].startswith("pre-20:"))
        self.assertEqual("post:0123456789abcdef", lines[2])

    def test_doctor_and_verify_hooks_receive_context(self) -> None:
        self._write_hook(
            self.doctor_hooks,
            "10-doctor",
            'printf "doctor\n" >> "$HOOK_LOG"',
        )
        self._write_hook(
            self.verify_hooks,
            "10-verify",
            'printf "verify:%s\n" "$BACKUP_RESTORE_DIR" >> "$HOOK_LOG"',
        )

        self._run("doctor")
        self._run("run")
        restored = self.restore_root / "hook-rehearsal"
        self._run("restore-latest", str(restored))

        self.assertEqual(
            ["doctor", f"verify:{restored}"],
            self.hook_log.read_text().splitlines(),
        )

    def test_pre_hook_payload_is_not_replaced_by_source_metadata(self) -> None:
        source_metadata = self.source / ".backup-sidecar"
        source_metadata.mkdir()
        (source_metadata / "generated.txt").write_text("source\n")
        self._write_hook(
            self.pre_hooks,
            "10-generate",
            'mkdir -p "$BACKUP_PAYLOAD_DIR/.backup-sidecar"; '
            'printf "hook\\n" > "$BACKUP_PAYLOAD_DIR/.backup-sidecar/generated.txt"',
        )

        self._run("run")

        self.assertEqual(
            "hook\n",
            (self.capture / ".backup-sidecar" / "generated.txt").read_text(),
        )

    def test_failed_run_invokes_failure_hook(self) -> None:
        self._write_hook(
            self.failure_hooks,
            "10-record",
            'printf "failure:%s\\n" "$BACKUP_EXIT_CODE" >> "$HOOK_LOG"',
        )
        missing = self.source / "missing.db"
        result = self._run(
            "run",
            check=False,
            environment=self._environment(SQLITE_DATABASES=str(missing)),
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(f"failure:{result.returncode}\n", self.hook_log.read_text())
        self.assertTrue((self.state / "last-failure").is_file())
        self.assertFalse((self.state / "last-success").exists())

    def test_stale_health_is_rejected(self) -> None:
        (self.state / "last-success-epoch").write_text("1\n")
        result = self._run("health", check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("last successful backup is", result.stderr)

    def test_corrupt_restore_is_rejected(self) -> None:
        target = self.restore_root / "corrupt"
        metadata = target / ".sqlite-backup"
        database = target / "data" / "application.db"
        metadata.mkdir(parents=True)
        database.parent.mkdir(parents=True)
        (metadata / "manifest").write_text("format_version=2\n")
        (metadata / "sqlite-paths").write_text("data/application.db\n")
        database.write_bytes(b"not a sqlite database")

        result = self._run("verify", str(target), check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("restored SQLite quick_check failed", result.stderr)

    def test_restore_refuses_nonempty_target(self) -> None:
        target = self.restore_root / "nonempty"
        target.mkdir()
        (target / "existing.txt").write_text("preserve me\n")
        result = self._run("restore-latest", str(target), check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("restore target must be empty", result.stderr)


@unittest.skipUnless(shutil.which("restic") and shutil.which("flock"), "restic and flock required")
class RealResticIntegrationTest(unittest.TestCase):
    def test_local_repository_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            database = source / "application.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
                connection.execute("INSERT INTO records VALUES ('restored')")
                connection.commit()

            paths = {
                name: root / name
                for name in ("stage", "state", "cache", "restore", "repository")
            }
            for path in paths.values():
                path.mkdir()

            environment = os.environ.copy()
            environment.update(
                {
                    "BACKUP_NAME": "real-restic-test",
                    "BACKUP_SOURCE_DIR": str(source),
                    "BACKUP_STAGE_ROOT": str(paths["stage"]),
                    "BACKUP_STATE_DIR": str(paths["state"]),
                    "BACKUP_CACHE_DIR": str(paths["cache"]),
                    "SQLITE_DATABASES": str(database),
                    "RESTIC_REPOSITORY": str(paths["repository"]),
                    "RESTIC_PASSWORD": "integration-test-password",
                    "RESTORE_ROOT": str(paths["restore"]),
                }
            )
            subprocess.run([str(SCRIPT), "run"], env=environment, check=True)
            target = paths["restore"] / "rehearsal"
            subprocess.run(
                [str(SCRIPT), "restore-latest", str(target)],
                env=environment,
                check=True,
            )

            with closing(sqlite3.connect(target / "application.db")) as connection:
                value = connection.execute("SELECT value FROM records").fetchone()[0]
            self.assertEqual("restored", value)


if __name__ == "__main__":
    unittest.main()
