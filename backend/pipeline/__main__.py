"""Run the whole pipeline once without a worker: python -m pipeline [ISO issued_at]."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

from ingestion.db import SessionLocal
from pipeline import runner


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    when = datetime.fromisoformat(argv[0].replace("Z", "+00:00")) if argv else None
    result = runner.run_all(SessionLocal, when)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
