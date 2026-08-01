from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate_run.py"
BUSINESS_DATE = "2026-08-01"
RUN_ID = "20260801T201500+0800"
MATCH_ID = "2908672"


class ValidateRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.date_dir = (
            self.project_root
            / "soccer-prediction-journal"
            / "reports"
            / BUSINESS_DATE
        )
        self.run_dir = self.date_dir / "runs" / RUN_ID
        self.run_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def write_html(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "<!DOCTYPE html><html><head><title>test</title></head><body>ok</body></html>",
            encoding="utf-8",
        )

    def result_json(
        self,
        *,
        status: str = "success",
        artifact_action: str = "generated",
    ) -> dict:
        return {
            "schema_version": "1.0",
            "business_date": BUSINESS_DATE,
            "match_id": MATCH_ID,
            "kickoff_time": "2026-08-02T07:30:00+08:00",
            "league": "美职业",
            "home_team": "国际迈阿密",
            "away_team": "哥伦布机员",
            "analysis_status": status,
            "artifact_action": artifact_action,
            "odds_snapshot_at": "2026-08-01T20:15:00+08:00",
            "analysis_version": "soccer-predict v1.3.9",
            "recommendation": "主胜" if status == "success" else "数据不足，不投注",
            "probability": 0.56 if status == "success" else None,
            "predicted_score": "2-1" if status == "success" else "",
            "formal_recommendation": status == "success",
            "report_path": (
                f"soccer-prediction-journal/reports/{BUSINESS_DATE}/match-{MATCH_ID}.html"
                if status == "success"
                else ""
            ),
            "missing_data": [] if status == "success" else ["lineup"],
            "error": "" if status == "success" else "lineup verification failed",
        }

    def manifest_result(
        self,
        *,
        status: str = "success",
        run_action: str = "generated",
        previous_success_retained: bool = False,
    ) -> dict:
        run_prefix = f"soccer-prediction-journal/reports/{BUSINESS_DATE}/runs/{RUN_ID}"
        canonical_prefix = f"soccer-prediction-journal/reports/{BUSINESS_DATE}"
        result = {
            "match_id": MATCH_ID,
            "analysis_status": status,
            "run_action": run_action,
            "attempt_result_path": "",
            "attempt_report_path": "",
            "canonical_result_path": f"{canonical_prefix}/match-{MATCH_ID}.json",
            "canonical_report_path": f"{canonical_prefix}/match-{MATCH_ID}.html",
            "previous_success_retained": previous_success_retained,
            "error": "" if status == "success" else "lineup verification failed",
        }
        if run_action != "reused":
            result["attempt_result_path"] = f"{run_prefix}/match-{MATCH_ID}.json"
            if status == "success":
                result["attempt_report_path"] = f"{run_prefix}/match-{MATCH_ID}.html"
        return result

    def manifest(self, result: dict, *, window_start: str | None = None) -> dict:
        return {
            "schema_version": "1.0",
            "business_date": BUSINESS_DATE,
            "business_window": {
                "start": window_start or "2026-08-01T11:00:00+08:00",
                "end": (
                    "2026-08-02T00:00:00+08:00"
                    if window_start
                    else "2026-08-02T11:00:00+08:00"
                ),
            },
            "run_id": RUN_ID,
            "created_at": "2026-08-01T20:15:00+08:00",
            "candidates": [
                {
                    "match_id": MATCH_ID,
                    "kickoff_time": "2026-08-02T07:30:00+08:00",
                    "league": "美职业",
                    "home_team": "国际迈阿密",
                    "away_team": "哥伦布机员",
                }
            ],
            "excluded": [],
            "results": [result],
        }

    def run_validator(self, phase: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(VALIDATOR),
                "--project-root",
                str(self.project_root),
                "--manifest",
                str(self.run_dir / "run-manifest.json"),
                "--phase",
                phase,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_cross_midnight_generated_attempt_and_final_are_valid(self) -> None:
        attempt_json = self.run_dir / f"match-{MATCH_ID}.json"
        attempt_html = self.run_dir / f"match-{MATCH_ID}.html"
        self.write_json(attempt_json, self.result_json())
        self.write_html(attempt_html)
        self.write_json(
            self.run_dir / "run-manifest.json",
            self.manifest(self.manifest_result()),
        )

        attempt = self.run_validator("attempt")
        self.assertEqual(attempt.returncode, 0, attempt.stdout + attempt.stderr)

        shutil.copy2(attempt_json, self.date_dir / f"match-{MATCH_ID}.json")
        shutil.copy2(attempt_html, self.date_dir / f"match-{MATCH_ID}.html")
        final = self.run_validator("final")
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

    def test_reused_result_keeps_original_artifact_action(self) -> None:
        self.write_json(
            self.date_dir / f"match-{MATCH_ID}.json",
            self.result_json(artifact_action="generated"),
        )
        self.write_html(self.date_dir / f"match-{MATCH_ID}.html")
        self.write_json(
            self.run_dir / "run-manifest.json",
            self.manifest(self.manifest_result(run_action="reused")),
        )

        attempt = self.run_validator("attempt")
        final = self.run_validator("final")
        self.assertEqual(attempt.returncode, 0, attempt.stdout + attempt.stderr)
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

    def test_failed_refresh_can_retain_previous_success(self) -> None:
        self.write_json(
            self.date_dir / f"match-{MATCH_ID}.json",
            self.result_json(artifact_action="generated"),
        )
        self.write_html(self.date_dir / f"match-{MATCH_ID}.html")
        self.write_json(
            self.run_dir / f"match-{MATCH_ID}.json",
            self.result_json(status="failed", artifact_action="refreshed"),
        )
        self.write_json(
            self.run_dir / "run-manifest.json",
            self.manifest(
                self.manifest_result(
                    status="failed",
                    run_action="refreshed",
                    previous_success_retained=True,
                )
            ),
        )

        attempt = self.run_validator("attempt")
        final = self.run_validator("final")
        self.assertEqual(attempt.returncode, 0, attempt.stdout + attempt.stderr)
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

    def test_natural_day_window_is_rejected(self) -> None:
        self.write_json(
            self.run_dir / f"match-{MATCH_ID}.json",
            self.result_json(),
        )
        self.write_html(self.run_dir / f"match-{MATCH_ID}.html")
        self.write_json(
            self.run_dir / "run-manifest.json",
            self.manifest(
                self.manifest_result(),
                window_start="2026-08-01T00:00:00+08:00",
            ),
        )

        result = self.run_validator("attempt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("business_date 11:00 through next-day 11:00", result.stdout)


if __name__ == "__main__":
    unittest.main()
