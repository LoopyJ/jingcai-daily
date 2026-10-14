"""Regression tests for the non-positive-EV delivery contract (Rule AD, v1.3.28).

Rule AD made one explicit direction per market mandatory and retired `abstain` as
a final direction. A market whose two sides both have non-positive EV keeps its
direction, its probability and both sides' EVs; only staking is blocked. These
tests pin that contract and the version gate that keeps pre-Rule-AD history
readable.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_run.py"
_spec = importlib.util.spec_from_file_location("validate_run", SCRIPT)
validate_run = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(validate_run)


def negative_ev_payload(*, direction: str = "over") -> dict:
    """A payload shaped like a real negative-EV OU delivery."""
    return {
        "schema_version": "1.0",
        "analysis_version": "soccer-predict v1.8.0",
        "shadow_forecast": {
            "ou": {
                "direction": direction,
                "base_model_direction": direction,
                "post_gate_direction": direction,
                "base_model_probability": 0.5508,
                "model_probability": 0.5508,
                "probability_semantics": "profit_probability=full_win+half_win",
                "ev": -0.0196,
                "formal_status": "direction_only",
                "nonformal_reason": "negative_ev",
            }
        },
        "ou_model": {
            "markets": {
                "over": {"profit_probability": 0.5508, "ev": -0.0196},
                "under": {"profit_probability": 0.4492, "ev": -0.0926},
            }
        },
    }


class NegativeEvDeliveryTests(unittest.TestCase):
    def check(self, payload: dict) -> list[str]:
        errors: list[str] = []
        validate_run.validate_negative_ev_delivery(payload, errors=errors, label="m")
        return errors

    def test_both_sides_negative_ev_delivers_a_direction(self) -> None:
        payload = negative_ev_payload()
        payload["action_status"] = "direction_only"
        payload["stars"] = 0
        payload["stake_cap"] = 0
        payload["formal_recommendation"] = False
        self.assertEqual(self.check(payload), [])

    def test_both_side_evs_must_survive(self) -> None:
        payload = negative_ev_payload()
        del payload["ou_model"]["markets"]["under"]["ev"]
        errors = self.check(payload)
        self.assertTrue(
            any("markets.under.ev" in error for error in errors),
            errors,
        )

    def test_abstain_is_not_a_delivered_direction(self) -> None:
        payload = negative_ev_payload(direction="abstain")
        errors = self.check(payload)
        self.assertTrue(
            any("must name over or under" in error for error in errors),
            errors,
        )

    def test_model_probability_cannot_be_nulled(self) -> None:
        payload = negative_ev_payload()
        payload["shadow_forecast"]["ou"]["model_probability"] = None
        errors = self.check(payload)
        self.assertTrue(
            any("model_probability must survive" in error for error in errors),
            errors,
        )

    def test_post_gate_direction_must_equal_the_delivered_direction(self) -> None:
        payload = negative_ev_payload()
        payload["shadow_forecast"]["ou"]["post_gate_direction"] = "under"
        errors = self.check(payload)
        self.assertTrue(
            any("post_gate_direction must equal" in error for error in errors),
            errors,
        )

    def test_missing_ou_shadow_is_reported(self) -> None:
        payload = negative_ev_payload()
        del payload["shadow_forecast"]
        errors = self.check(payload)
        self.assertTrue(any("shadow_forecast.ou is required" in error for error in errors), errors)


class DirectionVersionGateTests(unittest.TestCase):
    """`abstain` stays readable for pre-Rule-AD artifacts and is rejected after."""

    def snapshot(self, model_version: str, ou_direction: str) -> dict:
        return {
            "snapshot_schema_version": "prediction-snapshot.v2",
            "match_id": "3073093",
            "timestamp_valid": True,
            "frozen_at": "2026-10-14T00:23:52+08:00",
            "retrieved_at": "2026-10-14T00:23:52+08:00",
            "model_version": model_version,
            "match": {
                "match_id": "3073093",
                "league": "欧冠杯",
                "home": "国际米兰",
                "away": "布鲁日",
                "kickoff": "2026-10-14T03:00:00+08:00",
            },
            "decision": {
                "primary_direction": {"market": "AH", "direction": "home"},
                "markets": {"AH": {"direction": "home"}, "OU": {"direction": ou_direction}},
            },
            "score_scenarios": {},
        }

    def direction_errors(self, snapshot: dict) -> list[str]:
        errors: list[str] = []
        validate_run.validate_modern_snapshot(
            snapshot,
            expected_match_id="3073093",
            candidate={"kickoff_time": "2026-10-14T03:00:00+08:00"},
            errors=errors,
            label="m",
        )
        return [error for error in errors if "direction is invalid" in error]

    def test_abstain_is_rejected_for_a_rule_ad_model_version(self) -> None:
        self.assertTrue(self.direction_errors(self.snapshot("soccer-predict v1.7.4", "abstain")))

    def test_abstain_stays_readable_for_a_pre_rule_ad_artifact(self) -> None:
        self.assertEqual(self.direction_errors(self.snapshot("soccer-predict v1.3.9", "abstain")), [])

    def test_explicit_directions_pass(self) -> None:
        self.assertEqual(self.direction_errors(self.snapshot("soccer-predict v1.8.0", "over")), [])


class VersionGateBoundaryTests(unittest.TestCase):
    def test_boundary_is_rule_ad(self) -> None:
        self.assertEqual(validate_run.MANDATORY_DIRECTION_SINCE, (1, 3, 28))

    def test_unknown_version_is_held_to_the_current_contract(self) -> None:
        self.assertTrue(validate_run.requires_explicit_direction(None))

    def test_known_legacy_version_keeps_the_waiver(self) -> None:
        self.assertFalse(validate_run.requires_explicit_direction("soccer-predict v1.3.9"))

    def test_max_of_several_versions_wins(self) -> None:
        self.assertTrue(validate_run.requires_explicit_direction("v1.3.9", "v1.8.0"))


if __name__ == "__main__":
    unittest.main()
