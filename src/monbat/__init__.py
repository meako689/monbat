import asyncio
import sys


def main() -> None:
    match sys.argv[1:]:
        case ["discover"]:
            from monbat.discover import run_discover

            asyncio.run(run_discover())
        case _:
            print("Usage: monbat discover")
