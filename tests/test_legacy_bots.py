import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LegacyBotSupportTest(unittest.TestCase):
    def test_legacy_shim_prefers_java11_and_probes_selected_runtime_for_old_api(self) -> None:
        script = (ROOT / "scripts/run-battle.sh").read_text(encoding="utf-8")

        self.assertIn("LEGACY_JAVA11_BIN", script)
        self.assertIn("ROBOCODE_LEGACY_JAVA11_BIN", script)
        self.assertIn('export JAVA_BIN="\\$legacy_java11_bin"', script)
        self.assertIn('"\\$java_probe_bin" --enable-final-field-mutation=ALL-UNNAMED -version', script)
        self.assertIn("--enable-final-field-mutation=ALL-UNNAMED", script)
        self.assertIn("-Djava.awt.headless=true", script)
















if __name__ == "__main__":
    unittest.main()
