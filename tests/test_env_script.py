import os
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
            env = {
                **os.environ,
                "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MIN": "0.08",
            }
            script = (
                "set -euo pipefail; "
                f"source {ROOT / 'scripts/lib/env.sh'}; "
                f"load_repo_env {root}; "
                'printf "%s|%s\\n" "$ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MIN" "$ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MAX"'
            )

            result = subprocess.run(
                ["bash", "-lc", script],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )

        self.assertEqual("0.08|0.44", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
