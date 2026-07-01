import unittest

from tools.telemetry_schema_docs import build_markdown


class TelemetrySchemaDocsTest(unittest.TestCase):
    def test_generated_docs_include_contract_sections(self) -> None:
        markdown = build_markdown()

        self.assertIn("# Telemetry Event Schema", markdown)
        self.assertIn("## Canonical Dashboard Fields", markdown)
        self.assertIn("| `enemy.fire_detected` | `power`, `distance`, `evasion` |", markdown)
        self.assertIn("`target` from `bot_id`", markdown)


if __name__ == "__main__":
    unittest.main()
