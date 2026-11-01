import asyncio
import sys


def main() -> None:
    match sys.argv[1:]:
        case ["discover"]:
            from monbat.discover import run_discover

            asyncio.run(run_discover())
        case ["serve"] | []:
            from monbat.app import serve

            serve()
        case ["serve", "--log-level", level] | ["--log-level", level]:
            from monbat.app import serve

            serve(log_level=level)
        case _:
            print("Usage: monbat [discover|serve [--log-level LEVEL]]")
