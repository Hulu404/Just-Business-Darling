"""Prepare the gateway's selected stand schema after migrations have been applied."""
from __future__ import annotations

import argparse
import os
import sys

from store import GatewayStore, StoreError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    try:
        store = GatewayStore(os.environ.get("GATEWAY_DATABASE_URL", ""), os.environ.get("GATEWAY_DB_SCHEMA", ""))
        try:
            store.verify_schema()
            if not args.keep:
                store.clear_working()
            store.seed_catalog(os.environ.get("GATEWAY_HOME_CLINIC", "clinic-central"))
            if not args.keep:
                store.generate_slots(os.environ.get("GATEWAY_HOME_CLINIC", "clinic-central"))
        finally:
            store.close()
    except StoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
