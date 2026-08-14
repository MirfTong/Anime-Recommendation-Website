"""Gate scheduled GitHub Actions runs behind a successful-run interval."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


GITHUB_API_URL = "https://api.github.com"


def _github_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def should_run_scheduled_sync(
    successful_runs: list[dict[str, object]],
    *,
    now: datetime,
    minimum_hours: int,
) -> tuple[bool, str]:
    """Return whether the last successful scheduled run is old enough."""
    timestamps = []
    for run in successful_runs:
        timestamp = run.get("run_started_at") or run.get("created_at")
        if timestamp:
            timestamps.append(_github_datetime(str(timestamp)))
    if not timestamps:
        return True, "No previous successful scheduled run was found."

    last_success = max(timestamps)
    next_allowed = last_success + timedelta(hours=minimum_hours)
    if now >= next_allowed:
        return True, f"The last successful scheduled run was {last_success.isoformat()}."
    return (
        False,
        "The last successful scheduled run was "
        f"{last_success.isoformat()}; the next run is allowed after "
        f"{next_allowed.isoformat()}.",
    )


def _successful_scheduled_runs(
    *, repository: str, workflow: str, token: str
) -> list[dict[str, object]]:
    workflow_id = quote(workflow, safe="")
    query = urlencode({"event": "schedule", "status": "success", "per_page": 10})
    request = Request(
        f"{GITHUB_API_URL}/repos/{repository}/actions/workflows/"
        f"{workflow_id}/runs?{query}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "kyoquan-sync-guard",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    runs = payload.get("workflow_runs", [])
    if not isinstance(runs, list):
        raise RuntimeError("GitHub returned an invalid workflow-runs response")
    return [run for run in runs if isinstance(run, dict)]


def _write_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def _write_summary(should_run: bool, reason: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    decision = "run" if should_run else "skip"
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write("### Scheduled sync cadence\n\n")
        summary.write(f"Decision: **{decision}**\n\n{reason}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--minimum-hours", type=int, default=72)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.minimum_hours <= 0:
        raise SystemExit("--minimum-hours must be positive")

    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    if event_name == "workflow_dispatch":
        should_run = True
        reason = "Manual workflow dispatch bypasses the scheduled cadence guard."
    elif event_name == "schedule":
        repository = os.getenv("GITHUB_REPOSITORY", "")
        token = os.getenv("GITHUB_TOKEN", "")
        if not repository or not token:
            raise SystemExit(
                "GITHUB_REPOSITORY and GITHUB_TOKEN are required for scheduled runs"
            )
        try:
            runs = _successful_scheduled_runs(
                repository=repository,
                workflow=args.workflow,
                token=token,
            )
        except Exception as error:
            raise SystemExit(
                "Unable to verify the previous successful workflow run; "
                "refusing to start a database-writing sync "
                f"({type(error).__name__})."
            ) from None
        should_run, reason = should_run_scheduled_sync(
            runs,
            now=datetime.now(timezone.utc),
            minimum_hours=args.minimum_hours,
        )
    else:
        should_run = True
        reason = f"Event {event_name or 'unknown'} is not a scheduled run."

    _write_output("should_run", str(should_run).lower())
    _write_summary(should_run, reason)
    print(reason)


if __name__ == "__main__":
    main()
