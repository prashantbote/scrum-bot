"""`make openapi`: write backend/openapi.json (the contract the frontend generates its client from).

uv run python scripts/export_openapi.py          # write
uv run python scripts/export_openapi.py --check  # CI: fail if the committed file is stale
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> int:
    os.environ.setdefault("SCRUM_TEMPORAL_ENABLED", "false")
    from scrum_api.main import create_app

    spec = create_app().openapi()
    text = json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("openapi.json is stale: run `make openapi` and commit it.", file=sys.stderr)
            return 1
        print("openapi.json is up to date.")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(spec['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
