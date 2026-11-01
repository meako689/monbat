"""Summarize recovery timing without printing identifying log fields."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import re
from statistics import median
import sys


def main(path: Path) -> None:
    text = path.read_text()
    rows: list[tuple[datetime, bool, str]] = []
    pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4}).*"
        r"Background collection completed retry_only=(True|False) saved=(\S+)"
    )
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            rows.append((
                datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S %z"),
                match[2] == "True",
                match[3],
            ))
    if not rows:
        raise ValueError("No background collection summaries found")
    normal = [row for row in rows if not row[1]]
    retry = [row for row in rows if row[1]]
    print(f"normal_passes={len(normal)} saved_counts={dict(Counter(r[2] for r in normal))}")
    print(f"retry_passes={len(retry)} saved_counts={dict(Counter(r[2] for r in retry))}")
    for battery in ("bat-1", "bat-2"):
        times: list[float] = []
        for index, (start, _, saved) in enumerate(normal):
            if saved != "none":
                continue
            end = normal[index + 1][0] if index + 1 < len(normal) else rows[-1][0]
            saves = [
                (timestamp - start).total_seconds()
                for timestamp, _, ids in retry
                if start < timestamp <= end and battery in ids.split(",")
            ]
            if saves:
                times.append(saves[0])
        if times:
            print(
                f"{battery}: n={len(times)} "
                f"min/median/max={min(times):.0f}/{median(times):.0f}/{max(times):.0f}s"
            )
    print(f"first_missing_objects={text.count('BlueZ device object missing for')}")
    print(f"repeated_missing_objects={text.count('remains unavailable: BlueZ device object is missing')}")
    print(f"EBADF={text.count('Bad file descriptor')}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
