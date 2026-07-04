import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EnvScriptTest(unittest.TestCase):
    def test_load_repo_env_preserves_existing_process_env_over_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MIN=0.99",
                        "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MAX=0.44",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (root / ".env.guns").write_text(
                "\n".join(
                    [
                        "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MAX=0.22",
                        "ROBOCODE_GUN_MODE=linear",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MIN": "0.08",
            }
            script = (
                "set -euo pipefail; "
                f"source {ROOT / 'scripts/lib/env.sh'}; "
                f"load_repo_env {root}; "
                'printf "%s|%s|%s\\n" '
                '"$ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MIN" '
                '"$ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MAX" '
                '"$ROBOCODE_GUN_MODE"'
            )

            result = subprocess.run(
                ["bash", "-lc", script],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )

        self.assertEqual("0.08|0.22|linear", result.stdout.strip())

    def test_packaged_launcher_loads_dotenv_guns_without_repo_env_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bot_core").mkdir()
            shutil.copy(ROOT / "bots/bot_core/launcher_env.sh", root / "bot_core/launcher_env.sh")
            (root / ".env").write_text(
                "\n".join(
                    [
                        "ROBOCODE_GUN_MODE=linear",
                        "ROBOCODE_GUN_SET=linear",
                        "ROBOCODE_TELEMETRY=1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (root / ".env.guns").write_text(
                "\n".join(
                    [
                        "ROBOCODE_GUN_MODE=traditional_gf",
                        "ROBOCODE_GUN_SET=anti_surfer,dynamic_cluster",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "ROBOCODE_GUN_MODE": "head_on",
            }
            script = (
                "set -euo pipefail; "
                f"source {root / 'bot_core/launcher_env.sh'}; "
                f"load_repo_env_if_available {root}; "
                'printf "%s|%s|%s\\n" '
                '"$ROBOCODE_GUN_MODE" '
                '"$ROBOCODE_GUN_SET" '
                '"$ROBOCODE_TELEMETRY"'
            )

            result = subprocess.run(
                ["bash", "-lc", script],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )

        self.assertEqual("head_on|anti_surfer,dynamic_cluster|1", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
