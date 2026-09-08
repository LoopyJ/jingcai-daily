from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import adapt_prediction
import validate_run


class AdaptPredictionTests(unittest.TestCase):
    def snapshot(self) -> dict:
        return {
            "snapshot_schema_version": "prediction-snapshot.v2",
            "match_id": "9001",
            "model_version": "soccer-predict v1.7.4",
            "timestamp_valid": True,
            "frozen_at": "2026-09-08T20:00:00+08:00",
            "retrieved_at": "2026-09-08T20:00:00+08:00",
            "match": {
                "match_id": "9001",
                "league": "测试联赛",
                "home": "主队",
                "away": "客队",
                "kickoff": "2026-09-09T00:45:00+08:00",
            },
            "decision": {
                "action_status": "direction_only",
                "stars": 0,
                "stake_cap_u": 0.0,
                "primary_direction": {
                    "market": "AH",
                    "direction": "away",
                    "post_gate_direction": "away",
                    "line": 0.5,
                    "selected_line": -0.5,
                    "model_probability": 0.52,
                    "base_ev": -0.01,
                },
                "markets": {
                    "AH": {"direction": "away"},
                    "OU": {
                        "direction": "over",
                        "post_gate_direction": "over",
                        "base_model_direction": "over",
                        "line": 2.75,
                        "model_probability": 0.56,
                        "base_ev": -0.02,
                        "action_status": "direction_only",
                        "feature_coverage": 0.68,
                        "frozen_estimate": {
                            "market_implied_lambda": 2.7,
                            "lambda": {"total": 2.8, "home": 1.4, "away": 1.4},
                            "feature_coverage": {
                                "ratio": 0.68,
                                "missing_value_policy": "neutral_zero_signal",
                            },
                            "feature_contributions": [],
                        },
                        "markets": {
                            "over": {"profit_probability": 0.56, "ev": -0.02},
                            "under": {"profit_probability": 0.44, "ev": -0.03},
                        },
                    },
                },
            },
            "score_scenarios": {
                "unconditional_mode": {"score": "1-1", "probability": 0.12},
                "primary_market_mode": {
                    "market": "AH",
                    "market_type": "asian_handicap",
                    "selection": "away",
                    "line": 0.5,
                    "selected_line": -0.5,
                    "branches": {
                        "full_win": {
                            "probability": 0.52,
                            "representative_score": {
                                "score": "0-1",
                                "probability": 0.10,
                                "settlement": "full_win",
                            },
                        },
                        "full_loss": {
                            "probability": 0.48,
                            "representative_score": {
                                "score": "1-1",
                                "probability": 0.12,
                                "settlement": "full_loss",
                            },
                        },
                    },
                },
                "displayed_markets": [
                    {
                        "market": "AH",
                        "market_type": "asian_handicap",
                        "selection": "away",
                        "line": 0.5,
                        "selected_line": -0.5,
                        "branches": {
                            "full_win": {
                                "probability": 0.52,
                                "representative_score": {"score": "0-1", "probability": 0.10},
                            },
                            "full_loss": {
                                "probability": 0.48,
                                "representative_score": {"score": "1-1", "probability": 0.12},
                            },
                        },
                    },
                    {
                        "market": "OU",
                        "market_type": "over_under",
                        "selection": "over",
                        "line": 2.75,
                        "branches": {
                            "full_win": {
                                "probability": 0.30,
                                "representative_score": {"score": "2-2", "probability": 0.06},
                            },
                            "half_win": {
                                "probability": 0.25,
                                "representative_score": {"score": "1-2", "probability": 0.09},
                            },
                            "full_loss": {
                                "probability": 0.45,
                                "representative_score": {"score": "1-1", "probability": 0.12},
                            },
                        },
                    },
                ],
                "joint_full_win_mode": {
                    "status": "available",
                    "representative_score": {"score": "1-3", "probability": 0.05},
                },
            },
        }

    def test_projects_selected_side_line_and_ou_payload(self) -> None:
        result = adapt_prediction.build_result(
            self.snapshot(),
            business_date="2026-09-08",
            artifact_action="generated",
            report_path="soccer-prediction-journal/reports/2026-09-09/match-9001.md",
        )
        self.assertEqual(result["match_id"], "9001")
        self.assertEqual(result["primary_direction"], "AH 客-0.5")
        self.assertEqual(result["score_scenarios"]["primary_market_mode"]["line"], -0.5)
        self.assertEqual(
            result["score_scenarios"]["unconditional_mode"]["primary_market_settlement"],
            "full_loss",
        )
        self.assertEqual(result["ou_model"]["feature_coverage"]["ratio"], 0.68)
        self.assertEqual(result["shadow_forecast"]["ou"]["model_probability"], 0.56)
        self.assertFalse(result["formal_recommendation"])
        errors: list[str] = []
        validate_run.validate_result_json(
            result,
            expected_business_date="2026-09-08",
            expected_match_id="9001",
            expected_status="success",
            expected_artifact_action="generated",
            expected_report_path="soccer-prediction-journal/reports/2026-09-09/match-9001.md",
            errors=errors,
            label="adapted result",
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
