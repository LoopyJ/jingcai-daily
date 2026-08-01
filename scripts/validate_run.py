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


def check_html(path: Path | None, label: str, errors: list[str]) -> None:
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
    lowered = text.lower()
    for marker in ("<!doctype html", "<html", "<head", "<body"):
        if marker not in lowered:
            errors.append(f"{label} is missing {marker!r}: {path}")


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
        canonical_report_rel = f"soccer-prediction-journal/reports/{business_date}/match-{match_id}.html"
        attempt_result_rel = (
            f"soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.json"
        )
        attempt_report_rel = (
            f"soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.html"
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
                check_html(attempt_report, f"{label} attempt HTML", errors)

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
            check_html(canonical_report, f"{label} canonical HTML", errors)

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
