import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LegacyBotAliasTest(unittest.TestCase):
    def test_basic_gf_surfer_alias_prefers_fixed_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            legacy_root = repo / "legacy-bots"
            fixed = self._legacy_bot(legacy_root, "wiki.BasicGFSurferFixed_1.02")
            self._legacy_bot(legacy_root, "wiki.BasicGFSurfer_1.02")

            resolved = self._bash(repo, 'legacy_bot_dir "$1" basic-gf-surfer')

            self.assertEqual(str(fixed), resolved)

    def test_basic_gf_surfer_alias_falls_back_to_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            original = self._legacy_bot(repo / "legacy-bots", "wiki.BasicGFSurfer_1.02")

            resolved = self._bash(repo, 'legacy_bot_dir "$1" basic-gf-surfer')

            self.assertEqual(str(original), resolved)

    def test_original_alias_selects_unpatched_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            legacy_root = repo / "legacy-bots"
            self._legacy_bot(legacy_root, "wiki.BasicGFSurferFixed_1.02")
            original = self._legacy_bot(legacy_root, "wiki.BasicGFSurfer_1.02")

            resolved = self._bash(repo, 'legacy_bot_dir "$1" basic-gf-surfer-original')

            self.assertEqual(str(original), resolved)

    def test_list_legacy_bots_uses_original_alias_only_when_fixed_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._legacy_bot(repo / "legacy-bots", "wiki.BasicGFSurfer_1.02")

            listed = self._bash(repo, 'list_legacy_bots "$1"')

            self.assertIn("basic-gf-surfer\t", listed)
            self.assertNotIn("basic-gf-surfer-original\t", listed)

    def test_list_legacy_bots_keeps_original_available_when_fixed_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            legacy_root = repo / "legacy-bots"
            self._legacy_bot(legacy_root, "wiki.BasicGFSurferFixed_1.02")
            self._legacy_bot(legacy_root, "wiki.BasicGFSurfer_1.02")

            listed = self._bash(repo, 'list_legacy_bots "$1"')

            self.assertIn("basic-gf-surfer\t", listed)
            self.assertIn("basic-gf-surfer-original\t", listed)

    @staticmethod
    def _legacy_bot(legacy_root: Path, name: str) -> Path:
        bot = legacy_root / name
        bot.mkdir(parents=True)
        (bot / f"{name}.json").write_text("{}\n", encoding="utf-8")
        script = bot / "run.sh"
        script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | 0o111)
        return bot

    @staticmethod
    def _bash(repo: Path, command: str) -> str:
        env = os.environ.copy()
        env.pop("ROBOCODE_LEGACY_BOTS_ROOT", None)
        result = subprocess.run(
            [
                "bash",
                "-lc",
                f"source {ROOT / 'scripts/lib/bots.sh'}; {command}",
                "bash",
                str(repo),
            ],
            check=True,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()


if __name__ == "__main__":
    unittest.main()
