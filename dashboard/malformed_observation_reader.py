"""Read-only diagnostics for rejected paper-challenge equity observations."""
from pathlib import Path

import pandas as pd

from config import STARTING_CASH
from dashboard.paper_challenge import build_paper_challenge_series


def malformed_equity_observation_status(path: str | Path = "paper_30_day_tracker.csv") -> dict:
    path = Path(path)
    try:
        tracker = pd.read_csv(path)
    except FileNotFoundError:
        return {"status": "CLEARED", "count": 0, "records": (), "source": str(path),
                "message": "No tracker artifact is available."}
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        return {"status": "UNRESOLVED", "count": None, "records": (), "source": str(path),
                "message": f"Tracker could not be read safely: {type(exc).__name__}."}
    result = build_paper_challenge_series(tracker, float(STARTING_CASH), 60, source=path.name)
    records = tuple({
        "Instrument": item.instrument, "Time": item.timestamp, "Source": item.source,
        "Record": item.source_record_id, "Failure Reason": item.failure_reason,
        "Classification": item.classification, "First Seen": item.first_seen,
        "Last Seen": item.last_seen, "Occurrences": item.occurrence_count,
        "Status": item.status, "Recommended Action": item.recommended_action,
    } for item in result.malformed_details)
    return {"status": "ACTIVE" if records else "CLEARED", "count": len(records),
            "records": records, "source": path.name,
            "message": "Invalid records remain excluded." if records else "No invalid equity records are present."}
