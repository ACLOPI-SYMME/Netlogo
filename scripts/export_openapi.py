"""Write the API's OpenAPI document to contracts/openapi.json (the contract for Línea A).

    python scripts/export_openapi.py          # write the file
    python scripts/export_openapi.py --check  # exit 1 if the committed file is out of date

Does not start any worker: the document is generated from the FastAPI app definition.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from aclopi.api import Settings, create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi.json"

logger = logging.getLogger("export_openapi")


def render() -> str:
    app = create_app(Settings())
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only compare with the committed file")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = CONTRACT.read_text(encoding="utf-8") if CONTRACT.exists() else ""
        if current != text:
            logger.error("%s is out of date; run python scripts/export_openapi.py", CONTRACT)
            return 1
        logger.info("%s is up to date", CONTRACT)
        return 0
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_text(text, encoding="utf-8", newline="\n")
    logger.info("Wrote %s (%d paths)", CONTRACT, len(json.loads(text)["paths"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
