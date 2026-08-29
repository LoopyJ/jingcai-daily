#!/usr/bin/env python3
"""Validate a jingcai-daily run manifest and its per-match artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ANALYSIS_STATUSES = {"success", "waiting", "incomplete", "failed"}
RUN_ACTIONS = {"generated", "refreshed", "reused", "not_run"}
ARTIFACT_ACTIONS = {"generated", "refreshed", "not_run"}
MATCH_ID_RE = re.compile(r"^[0-9]+$")
SCORE_RE = re.compile(r"^(\d+)-(\d+)$")
SETTLEMENTS = {"full_win", "half_win", "push", "half_loss", "full_loss"}
ACTION_STATUSES = {"formal_standard", "formal_cautious", "direction_only"}


def is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def is_quarter_line(value: Any) -> bool:
    return is_number(value) and abs(value * 4 - round(value * 4)) < 1e-9 and round(value * 4) % 2 != 0


def settle_score(market_type: Any, selection: Any, line: Any, score: Any) -> str | None:
    """Return exact settlement for a displayed market and score."""
    match = SCORE_RE.fullmatch(str(score))
    if not match:
        return None
    home_goals, away_goals = map(int, match.groups())

    if market_type in {"spf", "one_x_two"}:
        actual = "home" if home_goals > away_goals else "away" if home_goals < away_goals else "draw"
        return "full_win" if selection == actual else "full_loss"

    if market_type == "jingcai_rqspf":
        if not is_number(line) or selection not in {"home", "draw", "away"}:
            return None
        adjusted = home_goals + float(line) - away_goals
        actual = "home" if adjusted > 1e-9 else "away" if adjusted < -1e-9 else "draw"
        return "full_win" if selection == actual else "full_loss"

    if market_type not in {"asian_handicap", "over_under"} or not is_number(line):
        return None
    legs = [float(line)]
    if is_quarter_line(line):
        legs = [float(line) - 0.25, float(line) + 0.25]

    results: list[str] = []
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
        results.append("win" if value > 1e-9 else "loss" if value < -1e-9 else "push")

    wins = results.count("win")
    pushes = results.count("push")
    losses = results.count("loss")
    if wins == len(results):
        return "full_win"
    if wins and pushes:
        return "half_win"
    if pushes == len(results):
        return "push"
    if losses and pushes:
        return "half_loss"
    if losses == len(results):
        return "full_loss"
    return None


def load_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{label} does not exist: {path}")
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid UTF-8 JSON: {path}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object: {path}")
        return None
    return value


def parse_iso(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label} must be a non-empty ISO 8601 string")
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        errors.append(f"{label} is not valid ISO 8601: {value!r}")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{label} must include a UTC offset: {value!r}")
        return None
    if parsed.utcoffset() != timedelta(hours=8):
        errors.append(f"{label} must use the +08:00 offset: {value!r}")
    return parsed


def resolve_relative_path(
    project_root: Path,
    value: Any,
    expected_root: Path,
    label: str,
    errors: list[str],
    *,
    required: bool,
) -> Path | None:
    if value in (None, ""):
        if required:
            errors.append(f"{label} is required")
        return None
    if not isinstance(value, str):
        errors.append(f"{label} must be a workspace-relative string")
        return None
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        errors.append(f"{label} must not be absolute or contain '..': {value!r}")
        return None
    resolved = (project_root / raw).resolve()
    try:
        resolved.relative_to(expected_root)
    except ValueError:
        errors.append(f"{label} escapes the business-date report directory: {value!r}")
        return None
    return resolved


def check_markdown(path: Path | None, label: str, errors: list[str]) -> None:
    if path is None:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"{label} does not exist: {path}")
        return
    except (OSError, UnicodeError) as exc:
        errors.append(f"{label} cannot be read as UTF-8: {path}: {exc}")
        return
    if path.suffix.lower() != ".md":
        errors.append(f"{label} must use the .md extension: {path}")
    stripped_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not stripped_lines:
        errors.append(f"{label} is empty: {path}")
        return
    if not stripped_lines[0].startswith("# "):
        errors.append(f"{label} must start with a level-1 Markdown heading: {path}")
    if sum(1 for line in stripped_lines if line.startswith("## ")) < 2:
        errors.append(f"{label} must contain at least two level-2 sections: {path}")
    lowered = text.lower()
    if "<!doctype html" in lowered or "<html" in lowered:
        errors.append(f"{label} must not contain an HTML document: {path}")


def validate_result_json(
    data: dict[str, Any] | None,
    *,
    expected_business_date: str,
    expected_match_id: str,
    expected_status: str,
    expected_artifact_action: str | None,
    expected_report_path: str | None,
    errors: list[str],
    label: str,
) -> None:
    if data is None:
        return
    required = {
        "schema_version",
        "business_date",
        "match_id",
        "kickoff_time",
        "league",
        "home_team",
        "away_team",
        "analysis_status",
        "artifact_action",
        "odds_snapshot_at",
        "analysis_version",
        "recommendation",
        "probability",
        "predicted_score",
        "formal_recommendation",
        "report_path",
        "missing_data",
        "error",
    }
    missing = sorted(required - data.keys())
    if missing:
        errors.append(f"{label} is missing fields: {', '.join(missing)}")
    if data.get("schema_version") != "1.0":
        errors.append(f"{label}.schema_version must be '1.0'")
    if data.get("business_date") != expected_business_date:
        errors.append(f"{label} business_date does not match manifest")
    if not isinstance(data.get("match_id"), str) or not MATCH_ID_RE.fullmatch(data.get("match_id", "")):
        errors.append(f"{label}.match_id must be a numeric string")
    if data.get("match_id") != expected_match_id:
        errors.append(f"{label} match_id does not match manifest")
    if data.get("analysis_status") != expected_status:
        errors.append(f"{label} analysis_status does not match manifest")
    if data.get("artifact_action") not in ARTIFACT_ACTIONS:
        errors.append(f"{label}.artifact_action is invalid: {data.get('artifact_action')!r}")
    if expected_artifact_action is not None and data.get("artifact_action") != expected_artifact_action:
        errors.append(f"{label} artifact_action does not match this attempt")
    parse_iso(data.get("kickoff_time"), f"{label}.kickoff_time", errors)
    parse_iso(data.get("odds_snapshot_at"), f"{label}.odds_snapshot_at", errors)
    probability = data.get("probability")
    if probability is not None and (
        isinstance(probability, bool)
        or not isinstance(probability, (int, float))
        or not 0 <= probability <= 1
    ):
        errors.append(f"{label}.probability must be null or a number from 0 to 1")
    if not isinstance(data.get("missing_data"), list):
        errors.append(f"{label}.missing_data must be an array")
    if not isinstance(data.get("error"), str):
        errors.append(f"{label}.error must be a string")
    if not isinstance(data.get("formal_recommendation"), bool):
        errors.append(f"{label}.formal_recommendation must be a boolean")
    if expected_status != "success" and data.get("formal_recommendation") is not False:
        errors.append(f"{label} cannot contain a formal recommendation when status is {expected_status}")
    version_match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(data.get("analysis_version", "")))
    if version_match and tuple(map(int, version_match.groups())) >= (1, 3, 25):
        primary_direction = data.get("primary_direction")
        action_status = data.get("action_status")
        stars = data.get("stars")
        stake_cap = data.get("stake_cap")
        if expected_status == "success" and (
            not isinstance(primary_direction, str) or not primary_direction.strip()
        ):
            errors.append(
                f"{label}.primary_direction must be a non-empty string for v1.3.25 success"
            )
        elif expected_status != "success" and primary_direction is not None and not isinstance(
            primary_direction, str
        ):
            errors.append(f"{label}.primary_direction must be null or a string")
        if action_status not in ACTION_STATUSES:
            errors.append(f"{label}.action_status is invalid: {action_status!r}")
        if not is_number(stars) or not 0 <= stars <= 5:
            errors.append(f"{label}.stars must be a number from 0 to 5")
        if not is_number(stake_cap) or stake_cap < 0:
            errors.append(f"{label}.stake_cap must be a non-negative number")
        if action_status == "formal_cautious":
            if is_number(stars) and stars > 1:
                errors.append(f"{label}.formal_cautious stars cannot exceed 1")
            if is_number(stake_cap) and stake_cap > 0.25:
                errors.append(f"{label}.formal_cautious stake_cap cannot exceed 0.25")
        if action_status == "direction_only":
            if stars != 0 or stake_cap != 0:
                errors.append(f"{label}.direction_only must use stars=0 and stake_cap=0")
            if data.get("formal_recommendation") is not False:
                errors.append(f"{label}.direction_only cannot be a formal recommendation")
        if action_status in {"formal_standard", "formal_cautious"} and data.get(
            "formal_recommendation"
        ) is not True:
            errors.append(f"{label}.{action_status} must set formal_recommendation=true")
        if expected_status != "success" and action_status != "direction_only":
            errors.append(f"{label} non-success results must use action_status=direction_only")
    if version_match and tuple(map(int, version_match.groups())) >= (1, 3, 17):
        scenarios = data.get("score_scenarios")
        if not isinstance(scenarios, dict):
            errors.append(f"{label}.score_scenarios is required for analysis_version >= 1.3.17")
        else:
            unconditional = scenarios.get("unconditional_mode")
            primary = scenarios.get("primary_market_mode")
            if not isinstance(unconditional, dict):
                errors.append(f"{label}.score_scenarios.unconditional_mode must be an object")
            else:
                if not SCORE_RE.fullmatch(str(unconditional.get("score", ""))):
                    errors.append(f"{label}.score_scenarios.unconditional_mode.score must use N-N")
                mode_probability = unconditional.get("probability")
                if (
                    isinstance(mode_probability, bool)
                    or not isinstance(mode_probability, (int, float))
                    or not 0 <= mode_probability <= 1
                ):
                    errors.append(
                        f"{label}.score_scenarios.unconditional_mode.probability must be from 0 to 1"
                    )
            if primary is not None:
                if not isinstance(primary, dict):
                    errors.append(f"{label}.score_scenarios.primary_market_mode must be null or an object")
                else:
                    for field in ("market", "condition", "score"):
                        if not isinstance(primary.get(field), str) or not primary.get(field):
                            errors.append(
                                f"{label}.score_scenarios.primary_market_mode.{field} must be a non-empty string"
                            )
                    if not SCORE_RE.fullmatch(str(primary.get("score", ""))):
                        errors.append(f"{label}.score_scenarios.primary_market_mode.score must use N-N")
                    for field in ("joint_probability", "conditional_probability"):
                        value = primary.get(field)
                        if (
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or not 0 <= value <= 1
                        ):
                            errors.append(
                                f"{label}.score_scenarios.primary_market_mode.{field} must be from 0 to 1"
                            )
                    if data.get("formal_recommendation") is True and data.get("predicted_score") != primary.get("score"):
                        errors.append(
                            f"{label}.predicted_score must equal primary_market_mode.score for a formal recommendation"
                        )
            if version_match and tuple(map(int, version_match.groups())) >= (1, 3, 18) and isinstance(primary, dict):
                for field in ("market_type", "selection"):
                    if not isinstance(primary.get(field), str) or not primary.get(field):
                        errors.append(
                            f"{label}.score_scenarios.primary_market_mode.{field} must be a non-empty string"
                        )
                line = primary.get("line")
                if line is not None and not is_number(line):
                    errors.append(f"{label}.score_scenarios.primary_market_mode.line must be null or numeric")
                if primary.get("condition") != "full_win":
                    errors.append(f"{label}.score_scenarios.primary_market_mode.condition must be full_win")

                market_type = primary.get("market_type")
                selection = primary.get("selection")
                primary_settlement = settle_score(market_type, selection, line, primary.get("score"))
                if market_type in {"asian_handicap", "over_under"} and primary_settlement != "full_win":
                    errors.append(
                        f"{label}.score_scenarios.primary_market_mode.score does not fully win its market"
                    )

                unconditional_settlement = unconditional.get("primary_market_settlement") if isinstance(unconditional, dict) else None
                if unconditional_settlement not in SETTLEMENTS:
                    errors.append(
                        f"{label}.score_scenarios.unconditional_mode.primary_market_settlement is invalid"
                    )
                computed_unconditional = settle_score(
                    market_type,
                    selection,
                    line,
                    unconditional.get("score") if isinstance(unconditional, dict) else None,
                )
                if computed_unconditional is not None and unconditional_settlement != computed_unconditional:
                    errors.append(
                        f"{label}.score_scenarios.unconditional_mode.primary_market_settlement does not match its score"
                    )

                settlement_scenarios = scenarios.get("settlement_scenarios")
                if not isinstance(settlement_scenarios, list):
                    errors.append(f"{label}.score_scenarios.settlement_scenarios must be an array")
                else:
                    seen_conditions: set[str] = set()
                    full_win_score = None
                    branch_probability_total = 0.0
                    for index, scenario in enumerate(settlement_scenarios):
                        scenario_label = f"{label}.score_scenarios.settlement_scenarios[{index}]"
                        if not isinstance(scenario, dict):
                            errors.append(f"{scenario_label} must be an object")
                            continue
                        condition = scenario.get("condition")
                        if condition not in SETTLEMENTS:
                            errors.append(f"{scenario_label}.condition is invalid")
                        elif condition in seen_conditions:
                            errors.append(f"{scenario_label}.condition is duplicated")
                        else:
                            seen_conditions.add(condition)
                        score = scenario.get("score")
                        if not SCORE_RE.fullmatch(str(score)):
                            errors.append(f"{scenario_label}.score must use N-N")
                        for field in ("branch_probability", "joint_probability", "conditional_probability"):
                            value = scenario.get(field)
                            if not is_number(value) or not 0 <= value <= 1:
                                errors.append(f"{scenario_label}.{field} must be from 0 to 1")
                        branch_probability = scenario.get("branch_probability")
                        joint_probability = scenario.get("joint_probability")
                        conditional_probability = scenario.get("conditional_probability")
                        if is_number(branch_probability):
                            branch_probability_total += branch_probability
                            if branch_probability <= 0:
                                errors.append(f"{scenario_label}.branch_probability must be positive")
                        if is_number(joint_probability) and is_number(branch_probability) and joint_probability > branch_probability + 1e-9:
                            errors.append(f"{scenario_label}.joint_probability cannot exceed branch_probability")
                        if (
                            is_number(joint_probability)
                            and is_number(branch_probability)
                            and branch_probability > 0
                            and is_number(conditional_probability)
                            and abs(conditional_probability - joint_probability / branch_probability) > 0.005
                        ):
                            errors.append(
                                f"{scenario_label}.conditional_probability does not match joint/branch probability"
                            )
                        computed = settle_score(market_type, selection, line, score)
                        if computed is not None and condition != computed:
                            errors.append(f"{scenario_label}.condition does not match its score")
                        if condition == "full_win":
                            full_win_score = score

                    if full_win_score is not None and primary.get("score") != full_win_score:
                        errors.append(
                            f"{label}.score_scenarios.primary_market_mode.score must match the full_win scenario"
                        )
                    if is_quarter_line(line) and market_type in {"asian_handicap", "over_under"}:
                        if "full_win" not in seen_conditions:
                            errors.append(f"{label}.score_scenarios.settlement_scenarios must include full_win")
                        if not ({"half_win", "half_loss"} & seen_conditions):
                            errors.append(
                                f"{label}.score_scenarios.settlement_scenarios must include a half-settlement branch for a quarter line"
                            )
                        if unconditional_settlement not in seen_conditions:
                            errors.append(
                                f"{label}.score_scenarios.settlement_scenarios must include the unconditional mode branch"
                            )
                        if abs(branch_probability_total - 1.0) > 0.005:
                            errors.append(
                                f"{label}.score_scenarios.settlement_scenarios branch probabilities must sum to 1"
                            )
            if version_match and tuple(map(int, version_match.groups())) >= (1, 3, 19) and isinstance(primary, dict):
                displayed_markets = scenarios.get("displayed_markets")
                descriptors: list[dict[str, Any]] = []
                displayed_names: set[str] = set()
                if not isinstance(displayed_markets, list) or not displayed_markets:
                    errors.append(f"{label}.score_scenarios.displayed_markets must be a non-empty array")
                else:
                    for index, displayed in enumerate(displayed_markets):
                        displayed_label = f"{label}.score_scenarios.displayed_markets[{index}]"
                        if not isinstance(displayed, dict):
                            errors.append(f"{displayed_label} must be an object")
                            continue
                        for field in ("market", "market_type", "selection"):
                            if not isinstance(displayed.get(field), str) or not displayed.get(field):
                                errors.append(f"{displayed_label}.{field} must be a non-empty string")
                        market_name = displayed.get("market")
                        if isinstance(market_name, str) and market_name:
                            if market_name in displayed_names:
                                errors.append(f"{displayed_label}.market is duplicated")
                            displayed_names.add(market_name)
                        displayed_line = displayed.get("line")
                        if displayed_line is not None and not is_number(displayed_line):
                            errors.append(f"{displayed_label}.line must be null or numeric")
                        full_win_mode = displayed.get("full_win_mode")
                        if not isinstance(full_win_mode, dict):
                            errors.append(f"{displayed_label}.full_win_mode must be an object")
                        else:
                            score = full_win_mode.get("score")
                            if not SCORE_RE.fullmatch(str(score)):
                                errors.append(f"{displayed_label}.full_win_mode.score must use N-N")
                            for field in ("joint_probability", "conditional_probability"):
                                value = full_win_mode.get(field)
                                if not is_number(value) or not 0 <= value <= 1:
                                    errors.append(f"{displayed_label}.full_win_mode.{field} must be from 0 to 1")
                            computed = settle_score(
                                displayed.get("market_type"),
                                displayed.get("selection"),
                                displayed_line,
                                score,
                            )
                            if computed != "full_win":
                                errors.append(f"{displayed_label}.full_win_mode.score does not fully win its market")
                        descriptors.append(displayed)

                primary_market_name = primary.get("market")
                if isinstance(displayed_markets, list) and primary_market_name not in displayed_names:
                    errors.append(f"{label}.score_scenarios.displayed_markets must include the primary market")

                common_full_win_exists = bool(descriptors) and any(
                    all(
                        settle_score(
                            displayed.get("market_type"),
                            displayed.get("selection"),
                            displayed.get("line"),
                            f"{home_goals}-{away_goals}",
                        ) == "full_win"
                        for displayed in descriptors
                    )
                    for home_goals in range(31)
                    for away_goals in range(31)
                )
                joint_market_mode = scenarios.get("joint_market_mode")
                market_conflict = scenarios.get("market_conflict")
                if common_full_win_exists:
                    if not isinstance(joint_market_mode, dict):
                        errors.append(
                            f"{label}.score_scenarios.joint_market_mode is required when displayed markets share a full-win score"
                        )
                    else:
                        joint_score = joint_market_mode.get("score")
                        if not SCORE_RE.fullmatch(str(joint_score)):
                            errors.append(f"{label}.score_scenarios.joint_market_mode.score must use N-N")
                        joint_probability = joint_market_mode.get("probability")
                        if not is_number(joint_probability) or not 0 <= joint_probability <= 1:
                            errors.append(
                                f"{label}.score_scenarios.joint_market_mode.probability must be from 0 to 1"
                            )
                        settlements = joint_market_mode.get("settlements")
                        settlement_names: set[str] = set()
                        if not isinstance(settlements, list) or len(settlements) != len(descriptors):
                            errors.append(
                                f"{label}.score_scenarios.joint_market_mode.settlements must cover every displayed market"
                            )
                        else:
                            descriptor_by_name = {
                                displayed.get("market"): displayed
                                for displayed in descriptors
                                if isinstance(displayed.get("market"), str)
                            }
                            for index, settlement in enumerate(settlements):
                                settlement_label = f"{label}.score_scenarios.joint_market_mode.settlements[{index}]"
                                if not isinstance(settlement, dict):
                                    errors.append(f"{settlement_label} must be an object")
                                    continue
                                market_name = settlement.get("market")
                                if market_name in settlement_names:
                                    errors.append(f"{settlement_label}.market is duplicated")
                                if isinstance(market_name, str):
                                    settlement_names.add(market_name)
                                displayed = descriptor_by_name.get(market_name)
                                if displayed is None:
                                    errors.append(f"{settlement_label}.market is not displayed")
                                    continue
                                computed = settle_score(
                                    displayed.get("market_type"),
                                    displayed.get("selection"),
                                    displayed.get("line"),
                                    joint_score,
                                )
                                if settlement.get("condition") != computed:
                                    errors.append(f"{settlement_label}.condition does not match the joint score")
                                if computed != "full_win":
                                    errors.append(f"{settlement_label} must be full_win for a joint market mode")
                            if settlement_names != displayed_names:
                                errors.append(
                                    f"{label}.score_scenarios.joint_market_mode.settlements must match displayed markets"
                                )
                    if market_conflict not in (None, ""):
                        errors.append(
                            f"{label}.score_scenarios.market_conflict must be null when a joint full-win score exists"
                        )
                else:
                    if joint_market_mode is not None:
                        errors.append(
                            f"{label}.score_scenarios.joint_market_mode must be null when displayed markets conflict"
                        )
                    if not isinstance(market_conflict, str) or not market_conflict.strip():
                        errors.append(
                            f"{label}.score_scenarios.market_conflict must explain incompatible displayed markets"
                        )
    if expected_status == "success" and data.get("report_path") != expected_report_path:
        errors.append(f"{label}.report_path must equal the canonical report path")


def validate_manifest(project_root: Path, manifest_path: Path, phase: str) -> list[str]:
    errors: list[str] = []
    manifest = load_json(manifest_path, errors, "manifest")
    if manifest is None:
        return errors
    if manifest.get("schema_version") != "1.0":
        errors.append("manifest.schema_version must be '1.0'")

    business_date = manifest.get("business_date")
    if not isinstance(business_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", business_date):
        errors.append("manifest.business_date must use YYYY-MM-DD")
        business_date = "invalid-date"
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        errors.append("manifest.run_id must be a non-empty string")
        run_id = "invalid-run"
    parse_iso(manifest.get("created_at"), "manifest.created_at", errors)

    expected_root = (project_root / "soccer-prediction-journal" / "reports" / business_date).resolve()
    expected_manifest = expected_root / "runs" / run_id / "run-manifest.json"
    if manifest_path.resolve() != expected_manifest:
        errors.append(f"manifest path must be {expected_manifest}")

    window = manifest.get("business_window")
    if not isinstance(window, dict):
        errors.append("manifest.business_window must be an object")
        start = end = None
    else:
        start = parse_iso(window.get("start"), "manifest.business_window.start", errors)
        end = parse_iso(window.get("end"), "manifest.business_window.end", errors)
        if start is not None and end is not None and not start < end:
            errors.append("manifest business window start must be before end")
        if start is not None and end is not None and business_date != "invalid-date":
            expected_start = datetime.fromisoformat(f"{business_date}T11:00:00+08:00")
            expected_end = expected_start + timedelta(days=1)
            if start != expected_start or end != expected_end:
                errors.append("manifest business window must be business_date 11:00 through next-day 11:00")

    candidates = manifest.get("candidates")
    results = manifest.get("results")
    if not isinstance(candidates, list):
        errors.append("manifest.candidates must be an array")
        candidates = []
    if not isinstance(results, list):
        errors.append("manifest.results must be an array")
        results = []
    if not isinstance(manifest.get("excluded"), list):
        errors.append("manifest.excluded must be an array")

    candidate_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        label = f"candidate[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{label} must be an object")
            continue
        raw_match_id = candidate.get("match_id")
        match_id = raw_match_id if isinstance(raw_match_id, str) else ""
        if not MATCH_ID_RE.fullmatch(match_id):
            errors.append(f"{label}.match_id must be a numeric string")
        candidate_ids.append(match_id)
        for field in ("league", "home_team", "away_team"):
            if not isinstance(candidate.get(field), str) or not candidate.get(field):
                errors.append(f"{label}.{field} must be a non-empty string")
        kickoff = parse_iso(candidate.get("kickoff_time"), f"{label}.kickoff_time", errors)
        if start is not None and end is not None and kickoff is not None and not (start <= kickoff < end):
            errors.append(f"{label}.kickoff_time is outside the business window")
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("manifest.candidates contains duplicate match IDs")

    result_ids: list[str] = []
    for index, result in enumerate(results):
        label = f"result[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{label} must be an object")
            continue
        raw_match_id = result.get("match_id")
        match_id = raw_match_id if isinstance(raw_match_id, str) else ""
        result_ids.append(match_id)
        if not MATCH_ID_RE.fullmatch(match_id):
            errors.append(f"{label}.match_id must be a numeric string")
        status = result.get("analysis_status")
        action = result.get("run_action")
        if status not in ANALYSIS_STATUSES:
            errors.append(f"{label}.analysis_status is invalid: {status!r}")
        if action not in RUN_ACTIONS:
            errors.append(f"{label}.run_action is invalid: {action!r}")
        if action == "reused" and status != "success":
            errors.append(f"{label}: reused results must have analysis_status=success")
        if not isinstance(result.get("previous_success_retained"), bool):
            errors.append(f"{label}.previous_success_retained must be a boolean")

        canonical_result_rel = f"soccer-prediction-journal/reports/{business_date}/match-{match_id}.json"
        canonical_report_rel = f"soccer-prediction-journal/reports/{business_date}/match-{match_id}.md"
        attempt_result_rel = (
            f"soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.json"
        )
        attempt_report_rel = (
            f"soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.md"
        )
        if result.get("attempt_result_path") not in (None, "", attempt_result_rel):
            errors.append(f"{label}.attempt_result_path must use the fixed run path")
        if result.get("attempt_report_path") not in (None, "", attempt_report_rel):
            errors.append(f"{label}.attempt_report_path must use the fixed run path")
        if result.get("canonical_result_path") not in (None, "", canonical_result_rel):
            errors.append(f"{label}.canonical_result_path must use the fixed match-ID path")
        if result.get("canonical_report_path") not in (None, "", canonical_report_rel):
            errors.append(f"{label}.canonical_report_path must use the fixed match-ID path")

        attempt_required = action in {"generated", "refreshed", "not_run"}
        attempt_result = resolve_relative_path(
            project_root,
            result.get("attempt_result_path"),
            expected_root,
            f"{label}.attempt_result_path",
            errors,
            required=attempt_required,
        )
        attempt_report = resolve_relative_path(
            project_root,
            result.get("attempt_report_path"),
            expected_root,
            f"{label}.attempt_report_path",
            errors,
            required=attempt_required and status == "success",
        )
        canonical_required = action == "reused" or (phase == "final" and status == "success")
        canonical_result = resolve_relative_path(
            project_root,
            result.get("canonical_result_path"),
            expected_root,
            f"{label}.canonical_result_path",
            errors,
            required=canonical_required,
        )
        canonical_report = resolve_relative_path(
            project_root,
            result.get("canonical_report_path"),
            expected_root,
            f"{label}.canonical_report_path",
            errors,
            required=canonical_required,
        )

        if action in {"generated", "refreshed", "not_run"}:
            attempt_data = load_json(attempt_result, errors, f"{label} attempt JSON") if attempt_result else None
            validate_result_json(
                attempt_data,
                expected_business_date=business_date,
                expected_match_id=match_id,
                expected_status=status if status in ANALYSIS_STATUSES else "",
                expected_artifact_action=action if action in ARTIFACT_ACTIONS else None,
                expected_report_path=canonical_report_rel if status == "success" else None,
                errors=errors,
                label=f"{label} attempt JSON",
            )
            if status == "success":
                check_markdown(attempt_report, f"{label} attempt Markdown", errors)

        if canonical_required:
            final_data = load_json(canonical_result, errors, f"{label} canonical JSON") if canonical_result else None
            validate_result_json(
                final_data,
                expected_business_date=business_date,
                expected_match_id=match_id,
                expected_status="success",
                expected_artifact_action=action if action in ARTIFACT_ACTIONS else None,
                expected_report_path=canonical_report_rel,
                errors=errors,
                label=f"{label} canonical JSON",
            )
            check_markdown(canonical_report, f"{label} canonical Markdown", errors)

    if len(result_ids) != len(set(result_ids)):
        errors.append("manifest.results contains duplicate match IDs")
    if set(candidate_ids) != set(result_ids):
        missing = sorted(set(candidate_ids) - set(result_ids))
        extra = sorted(set(result_ids) - set(candidate_ids))
        if missing:
            errors.append(f"manifest.results is missing candidate IDs: {', '.join(missing)}")
        if extra:
            errors.append(f"manifest.results contains unknown IDs: {', '.join(extra)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("attempt", "final"))
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = project_root / manifest_path
    errors = validate_manifest(project_root, manifest_path.resolve(), args.phase)
    if errors:
        print(f"INVALID ({len(errors)} error(s))")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"VALID: {manifest_path.resolve()} ({args.phase})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
