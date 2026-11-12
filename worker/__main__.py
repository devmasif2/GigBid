"""Run one local saved-search worker tick."""

import argparse
import json
import time

from worker.scheduler import SearchStore, run_due


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/local/worker.sqlite3")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit.")
    args = parser.parse_args()
    store = SearchStore(args.db)
    try:
        def search(query: str) -> list[dict[str, object]]:
            # The production adapter is injected by the API process; this CLI is a safe local hook.
            return [{"query": query, "status": "queued"}]

        while True:
            print(json.dumps({"completed": run_due(store, search)}))
            if args.once:
                return
            time.sleep(1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
