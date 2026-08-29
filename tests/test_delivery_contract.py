import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeliveryContractTests(unittest.TestCase):
    def test_skill_uses_markdown_for_all_new_report_types(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("match-{match_id}.md", skill)
        self.assertIn("daily-summary.md", skill)
        self.assertIn("review-summary.md", skill)
        self.assertIn("只提供文件链接视为交付未完成", skill)

    def test_result_contract_uses_markdown_paths(self) -> None:
        contract = (ROOT / "references" / "result-contract.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("match-2912225.md", contract)
        self.assertIn("JSON/Markdown", contract)
        self.assertIn("soccer-predict v1.3.25", contract)
        self.assertIn("primary_direction", contract)
        self.assertIn("formal_cautious", contract)


if __name__ == "__main__":
    unittest.main()
