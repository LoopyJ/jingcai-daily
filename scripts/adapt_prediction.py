#!/usr/bin/env python3
"""Adapt a soccer-predict v2 snapshot to the jingcai batch result contract.

The prediction engine owns the modern, reviewable snapshot.  This adapter only
projects already-frozen values into the orchestration contract; it never
recalculates a probability, EV, lambda, or direction.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ACTION_STATUSES = {"formal_standard", "formal_cautious", "direction_only"}
SETTLEMENTS = {"full_win", "half_win", "push", "half_loss", "full_loss"}


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return value


def _text(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _selected_line(market: dict[str, Any]) -> Any:
    """Return the line in selected-side settlement semantics."""
    if market.get("market") == "AH":
        return market.get("selected_line", market.get("line"))
    return market.get("line")


def _is_quarter_line(value: Any) -> bool:
    number = _number(value)
    return number is not None and abs(float(number) * 4 - round(float(number) * 4)) < 1e-9 and round(float(number) * 4) % 2 != 0


def _settle_score(market_type: Any, selection: Any, line: Any, score: Any) -> str | None:
    if not isinstance(score, str) or score.count("-") != 1:
        return None
    try:
        home_goals, away_goals = (int(part) for part in score.split("-"))
    except ValueError:
        return None

    if market_type in {"spf", "one_x_two"}:
        actual = "home" if home_goals > away_goals else "away" if home_goals < away_goals else "draw"
        return "full_win" if selection == actual else "full_loss"
    if market_type == "jingcai_rqspf":
        number = _number(line)
        if number is None or selection not in {"home", "draw", "away"}:
            return None
        adjusted = home_goals + float(number) - away_goals
        actual = "home" if adjusted > 1e-9 else "away" if adjusted < -1e-9 else "draw"
        return "full_win" if selection == actual else "full_loss"
    if market_type not in {"asian_handicap", "over_under"}:
        return None
    number = _number(line)
    if number is None:
        return None
    legs = [float(number)]
    if _is_quarter_line(number):
        legs = [float(number) - 0.25, float(number) + 0.25]

    outcomes: list[str] = []
    for leg in legs:
        if market_type == "asian_handicap":
            if selection == "home":
                value = home_goals - away_goals + leg
            elif selection == "away":
                value = away_goals - home_goals + leg
            else:
                return None
        else:
            total = home_goals + away_goals
            if selection == "over":
                value = total - leg
            elif selection == "under":
                value = leg - total
            else:
                return None
        outcomes.append("win" if value > 1e-9 else "loss" if value < -1e-9 else "push")

    wins = outcomes.count("win")
    pushes = outcomes.count("push")
    losses = outcomes.count("loss")
    if wins == len(outcomes):
        return "full_win"
    if wins and pushes:
        return "half_win"
    if pushes == len(outcomes):
        return "push"
    if losses and pushes:
        return "half_loss"
    if losses == len(outcomes):
        return "full_loss"
    return None


def _representative(branch: dict[str, Any]) -> dict[str, Any] | None:
    value = branch.get("representative_score") if isinstance(branch, dict) else None
    if not isinstance(value, dict):
        return None
    score = _text(value.get("score"))
    if not score:
        return None
    return {
        "score": score,
        "probability": _number(value.get("probability")),
        "settlement": _text(value.get("settlement")),
    }


def _conditional(joint: Any, branch: Any) -> float | None:
    joint_number = _number(joint)
    branch_number = _number(branch)
    if joint_number is None or branch_number is None or float(branch_number) <= 0:
        return None
    return max(0.0, min(1.0, float(joint_number) / float(branch_number)))


def _normalise_market(market: dict[str, Any]) -> dict[str, Any]:
    market_name = _text(market.get("market"))
    line = _selected_line(market)
    result: dict[str, Any] = {
        "market": market_name,
        "market_type": _text(market.get("market_type")),
        "selection": _text(market.get("selection")),
        "line": line,
        "full_win_mode": {},
    }
    if _text(market.get("display_label")):
        result["display_label"] = market["display_label"]
    for key in ("home_line", "selected_line"):
        if key in market:
            result[key] = market[key]

    branches = market.get("branches") if isinstance(market.get("branches"), dict) else {}
    normalised_branches: dict[str, Any] = {}
    for condition, branch in branches.items():
        if condition not in SETTLEMENTS or not isinstance(branch, dict):
            continue
        representative = _representative(branch)
        if representative is None:
            continue
        branch_probability = _number(branch.get("probability"))
        entry = {
            "branch_probability": branch_probability,
            "joint_probability": representative.get("probability"),
            "conditional_probability": _conditional(
                representative.get("probability"), branch_probability
            ),
            "score": representative.get("score"),
        }
        normalised_branches[condition] = entry

    full_win = normalised_branches.get("full_win")
    if full_win is not None:
        result["full_win_mode"] = {
            "score": full_win["score"],
            "joint_probability": full_win["joint_probability"],
            "conditional_probability": full_win["conditional_probability"],
        }
    result["branches"] = normalised_branches
    return result


def _normalise_score_scenarios(snapshot: dict[str, Any], primary: dict[str, Any] | None) -> dict[str, Any]:
    source = snapshot.get("score_scenarios") if isinstance(snapshot.get("score_scenarios"), dict) else {}
    unconditional_source = source.get("unconditional_mode") if isinstance(source.get("unconditional_mode"), dict) else {}
    primary_source = source.get("primary_market_mode") if isinstance(source.get("primary_market_mode"), dict) else None

    primary_market = _normalise_market(primary_source) if primary_source is not None else None
    if primary_market is not None:
        full_win_mode = primary_market.get("full_win_mode")
        if isinstance(full_win_mode, dict) and full_win_mode.get("score"):
            primary_market.update(
                {
                    "condition": "full_win",
                    "score": full_win_mode.get("score"),
                    "joint_probability": full_win_mode.get("joint_probability"),
                    "conditional_probability": full_win_mode.get("conditional_probability"),
                }
            )
    primary_line = primary_market.get("line") if primary_market else None
    primary_selection = primary_market.get("selection") if primary_market else None
    primary_type = primary_market.get("market_type") if primary_market else None
    unconditional_score = _text(unconditional_source.get("score"))
    unconditional = {
        "score": unconditional_score,
        "probability": _number(unconditional_source.get("probability")),
        "primary_market_settlement": _settle_score(
            primary_type, primary_selection, primary_line, unconditional_score
        ) if primary_market else None,
    }

    settlement_scenarios: list[dict[str, Any]] = []
    if primary_market:
        for condition, branch in primary_market.get("branches", {}).items():
            if not isinstance(branch, dict):
                continue
            branch_probability = branch.get("branch_probability")
            if _number(branch_probability) is None or float(branch_probability) <= 0:
                continue
            settlement_scenarios.append(
                {
                    "condition": condition,
                    "branch_probability": branch_probability,
                    "score": branch.get("score"),
                    "joint_probability": branch.get("joint_probability"),
                    "conditional_probability": branch.get("conditional_probability"),
                }
            )

    displayed_source = source.get("displayed_markets")
    displayed = []
    if isinstance(displayed_source, list):
        displayed = [_normalise_market(item) for item in displayed_source if isinstance(item, dict)]

    joint_mode = None
    conflict = None
    joint_source = source.get("joint_full_win_mode")
    if isinstance(joint_source, dict) and joint_source.get("status") == "available":
        representative = joint_source.get("representative_score")
        if isinstance(representative, dict) and _text(representative.get("score")):
            joint_mode = {
                "score": representative["score"],
                "probability": _number(representative.get("probability")),
                "settlements": [
                    {"market": item.get("market"), "condition": "full_win"}
                    for item in displayed
                ],
            }
    if joint_mode is None:
        conflict = "no common full-win score was supplied by the prediction engine"

    result: dict[str, Any] = {
        "unconditional_mode": unconditional,
        "primary_market_mode": primary_market,
        "settlement_scenarios": settlement_scenarios,
        "displayed_markets": displayed,
        "joint_market_mode": joint_mode,
        "market_conflict": conflict,
    }
    return result


def _display_direction(primary: dict[str, Any], primary_mode: dict[str, Any] | None) -> str:
    if primary_mode and _text(primary_mode.get("display_label")):
        return primary_mode["display_label"]
    market = _text(primary.get("market"))
    direction = _text(primary.get("post_gate_direction") or primary.get("direction"))
    direction_label = {
        "home": "主",
        "away": "客",
        "draw": "平",
        "over": "大",
        "under": "小",
        "abstain": "不投注",
    }.get(direction, direction)
    line = primary.get("selected_line", primary.get("line"))
    return f"{market} {direction_label}{line}".strip()


def _ou_model(snapshot: dict[str, Any], ou: dict[str, Any]) -> dict[str, Any]:
    frozen = ou.get("frozen_estimate") if isinstance(ou.get("frozen_estimate"), dict) else {}
    coverage_source = frozen.get("feature_coverage") if isinstance(frozen.get("feature_coverage"), dict) else {}
    markets = ou.get("markets") if isinstance(ou.get("markets"), dict) else {}
    feature_coverage = {
        "ratio": ou.get("feature_coverage", coverage_source.get("ratio")),
        "missing_value_policy": coverage_source.get("missing_value_policy"),
    }
    for field in ("eligible_nonmarket_weight", "coverage_provenance"):
        if field in coverage_source:
            feature_coverage[field] = coverage_source[field]
    return {
        "model_version": _text(snapshot.get("model_version")),
        "market_implied_lambda": frozen.get("market_implied_lambda"),
        "lambda": frozen.get("lambda") if isinstance(frozen.get("lambda"), dict) else {},
        "feature_coverage": feature_coverage,
        "feature_contributions": (
            frozen.get("feature_contributions")
            if isinstance(frozen.get("feature_contributions"), list)
            else ou.get("feature_contributions", [])
        ),
        "markets": markets,
    }


def build_result(
    snapshot: dict[str, Any],
    *,
    business_date: str,
    artifact_action: str,
    report_path: str,
) -> dict[str, Any]:
    if snapshot.get("snapshot_schema_version") != "prediction-snapshot.v2":
        raise ValueError("snapshot_schema_version must be prediction-snapshot.v2")
    match = snapshot.get("match") if isinstance(snapshot.get("match"), dict) else {}
    match_id = _text(snapshot.get("match_id") or match.get("match_id"))
    kickoff = _text(match.get("kickoff") or match.get("time"))
    retrieved = _text(snapshot.get("frozen_at") or snapshot.get("retrieved_at"))
    if not match_id or not kickoff or not retrieved:
        raise ValueError("snapshot is missing match_id, kickoff, or frozen time")

    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    markets = decision.get("markets") if isinstance(decision.get("markets"), dict) else {}
    ah = markets.get("AH") if isinstance(markets.get("AH"), dict) else {}
    ou = markets.get("OU") if isinstance(markets.get("OU"), dict) else {}
    primary = decision.get("primary_direction") if isinstance(decision.get("primary_direction"), dict) else None
    if primary is None:
        raise ValueError("snapshot decision.primary_direction is missing")

    score_scenarios = _normalise_score_scenarios(snapshot, primary)
    primary_mode = score_scenarios.get("primary_market_mode")
    action_status = _text(decision.get("action_status"), "direction_only")
    if action_status not in ACTION_STATUSES:
        raise ValueError(f"unsupported action_status: {action_status!r}")
    stars = _number(decision.get("stars"))
    stake_cap = _number(decision.get("stake_cap_u"))
    if stake_cap is None:
        raw_stake = decision.get("stake_cap")
        if isinstance(raw_stake, str):
            try:
                stake_cap = float(raw_stake.rstrip("uU"))
            except ValueError:
                stake_cap = None
    if stars is None:
        stars = 0
    if stake_cap is None:
        stake_cap = 0.0

    primary_probability = _number(primary.get("model_probability"))
    unconditional_score = (score_scenarios.get("unconditional_mode") or {}).get("score", "")
    predicted_score = (
        (primary_mode or {}).get("score", unconditional_score)
        if action_status in {"formal_standard", "formal_cautious"}
        else unconditional_score
    )
    result = {
        "schema_version": "1.0",
        "business_date": business_date,
        "match_id": match_id,
        "kickoff_time": kickoff,
        "league": _text(match.get("league")),
        "home_team": _text(match.get("home")),
        "away_team": _text(match.get("away")),
        "analysis_status": "success",
        "artifact_action": artifact_action,
        "odds_snapshot_at": retrieved,
        "analysis_version": _text(snapshot.get("model_version")),
        "recommendation": _display_direction(primary, primary_mode),
        "probability": primary_probability,
        "primary_direction": _display_direction(primary, primary_mode),
        "action_status": action_status,
        "stars": stars,
        "stake_cap": stake_cap,
        "predicted_score": predicted_score,
        "score_scenarios": score_scenarios,
        "formal_recommendation": action_status in {"formal_standard", "formal_cautious"},
        "ou_model": _ou_model(snapshot, ou),
        "shadow_forecast": {
            "ou": {
                "direction": ou.get("direction"),
                "base_model_direction": ou.get("base_model_direction"),
                "post_gate_direction": ou.get("post_gate_direction"),
                "base_model_probability": ou.get("model_probability"),
                "model_probability": ou.get("model_probability"),
                "probability_semantics": "profit_probability=full_win+half_win",
                "ev": ou.get("base_ev"),
                "formal_status": _text(ou.get("action_status"), "direction_only"),
                "nonformal_reason": _text(
                    ou.get("primary_blocking_reason") or ou.get("shadow_numeric_exclusion_reason"),
                    "none",
                ),
            }
        },
        "report_path": report_path,
        "missing_data": [],
        "error": "",
        "snapshot_schema_version": snapshot.get("snapshot_schema_version"),
        "source_snapshot_hash": snapshot.get("snapshot_content_sha256"),
    }
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--artifact-action", choices=("generated", "refreshed", "not_run"), default="generated")
    parser.add_argument("--report-path", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise SystemExit("snapshot must be a JSON object")
    result = build_result(
        snapshot,
        business_date=args.business_date,
        artifact_action=args.artifact_action,
        report_path=args.report_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
