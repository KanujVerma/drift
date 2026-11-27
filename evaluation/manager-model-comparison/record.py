"""Apply one saved proposal JSON to one comparison ledger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from drift.manager.models import InvestmentProposal
from drift.manager.service import PortfolioManager

ROOT = Path(__file__).resolve().parent


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: record.py MODEL CASE", file=sys.stderr)
        return 2
    model, case = sys.argv[1], sys.argv[2]
    ledger = ROOT / "out" / "ledgers" / model / f"{case}.sqlite"
    proposal_path = ROOT / "out" / "responses" / model / f"{case}.json"
    proposal = InvestmentProposal.model_validate_json(
        proposal_path.read_text(encoding="utf-8")
    )
    manager = PortfolioManager.recover(ledger)
    result = manager.propose(proposal)
    destination = ROOT / "out" / "ledger-results" / model / f"{case}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"case": case, "model": model, "status": result["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
