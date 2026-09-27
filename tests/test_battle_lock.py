import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_LIB = ROOT / "scripts" / "lib" / "battle_lock.sh"


def _bash(script: str, lock_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "ROBOCODE_BATTLE_LOCK_PATH": str(lock_path), **env}
    return subprocess.run(
        ["bash", "-c", f"set -euo pipefail; source {LOCK_LIB}; {script}"],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


class BattleLockTest(unittest.TestCase):
    def test_acquire_and_release_removes_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "battle.lock"

            result = _bash(
                'acquire_battle_lock; [[ -f "$(battle_lock_path)/pid" ]] && echo held; release_battle_lock',
                lock_path,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("held", result.stdout)
            self.assertFalse(lock_path.exists())

    def test_stale_lock_from_dead_pid_is_taken_over(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "battle.lock"
            lock_path.mkdir()
            (lock_path / "pid").write_text("99999999\n", encoding="utf-8")

            result = _bash("acquire_battle_lock; cat \"$(battle_lock_path)/pid\"; release_battle_lock", lock_path)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("99999999", result.stdout)
            self.assertNotIn("Waiting", result.stderr)

    def test_waits_for_live_holder_then_acquires(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "battle.lock"
            # Detach the holder so it is reaped when it exits; a zombie child would still pass kill -0.
            holder_pid = int(
                subprocess.run(
                    ["bash", "-c", "sleep 3 >/dev/null 2>&1 & echo $!"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )
            lock_path.mkdir()
            (lock_path / "pid").write_text(f"{holder_pid}\n", encoding="utf-8")
            started = time.monotonic()

            result = _bash("acquire_battle_lock; release_battle_lock", lock_path)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("Waiting for another battle", result.stderr)
            self.assertGreaterEqual(time.monotonic() - started, 2.0)

    def test_disabled_lock_does_not_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "battle.lock"
            lock_path.mkdir()
            (lock_path / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

            result = _bash("acquire_battle_lock; echo done", lock_path, ROBOCODE_BATTLE_LOCK="0")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("done", result.stdout)
            self.assertTrue(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
