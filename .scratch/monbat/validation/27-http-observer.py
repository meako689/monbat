"""Observe stored Telemetry; source the ignored .env.local for its Dashboard URL."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main() -> None:
    output = Path(sys.argv[1])
    dashboard_url = os.environ.get(
        "MONBAT_DASHBOARD_URL", "http://127.0.0.1:8000"
    ).rstrip("/")
    until = time.monotonic() + 1800
    previous: object = None
    print(f"Non-subscribing observer started: {output}", flush=True)
    with output.open("a") as stream:
        while time.monotonic() < until:
            sample: dict[str, object] = {"observed_at": time.time()}
            for endpoint in ("latest", "summary"):
                result = subprocess.run(
                    ["curl", "--max-time", "2", "--silent", "--show-error", "--fail",
                     f"{dashboard_url}/api/{endpoint}"],
                    capture_output=True, text=True,
                )
                if result.returncode:
                    sample[endpoint] = {"transport_error": result.stderr.strip()}
                else:
                    try:
                        sample[endpoint] = json.loads(result.stdout)
                    except json.JSONDecodeError:
                        sample[endpoint] = {"invalid_json": result.stdout}
            stream.write(json.dumps(sample) + "\n")
            stream.flush()
            latest = sample["latest"]
            if isinstance(latest, dict) and "transport_error" not in latest and "invalid_json" not in latest:
                state = {
                    battery: (view["status"], view["telemetry"]["timestamp"] if view["telemetry"] else None)
                    for battery, view in latest.items()
                }
            else:
                state = latest
            if state != previous:
                print(json.dumps({"observed_at": sample["observed_at"], "latest": state}), flush=True)
                previous = state
            time.sleep(2)


if __name__ == "__main__":
    main()
