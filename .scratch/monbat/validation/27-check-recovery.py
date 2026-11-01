"""Judge one recorded physical cycle; no HTTP calls or collection triggers."""

from datetime import datetime
import json
from pathlib import Path
import re
import sys


def main() -> None:
    directory = Path(sys.argv[1])
    before = json.loads((directory / "latest-before.json").read_text())
    service = (directory / "service-after.log").read_text()
    match = re.search(
        r"(2026-10-28 22:31:04 \+0200).*Subscriber added count=1", service,
    )
    if match is None:
        raise SystemExit("Missing first post-resume Dashboard subscription")
    opened = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S %z").timestamp()
    samples = [json.loads(line) for line in (directory / "http.jsonl").read_text().splitlines()]
    if samples[-1]["observed_at"] < opened + 300:
        print("INCOMPLETE: five-minute post-subscription window still running")
        raise SystemExit(2)
    window = [sample for sample in samples if opened <= sample["observed_at"] <= opened + 305]
    results = {}
    for battery, view in before.items():
        timestamps = set()
        status = None
        for sample in window:
            latest = sample["latest"]
            if battery not in latest:
                continue
            reading = latest[battery]
            status = reading["status"]
            telemetry = reading["telemetry"]
            if telemetry and telemetry["timestamp"] > opened:
                timestamps.add(telemetry["timestamp"])
        results[battery] = {
            "baseline_timestamp": view["telemetry"]["timestamp"],
            "new_readings": len(timestamps),
            "first_saved_after_open_seconds": min(timestamps) - opened if timestamps else None,
            "last_status": status,
            "passed": len(timestamps) >= 3 and status not in (None, "offline", "no-reading-yet"),
        }
    print(json.dumps(results, indent=2))
    passed = all(result["passed"] for result in results.values())
    print("PASS" if passed else "FAIL: not every Battery resumed fresh saved Telemetry")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
