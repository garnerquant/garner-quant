from __future__ import annotations
import json
from pathlib import Path

def opening_snapshot_status(root=Path("data/opening_snapshot_candidates")):
    try:
        root=Path(root);candidates=sorted((p for p in root.iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime) if root.exists() else []
        if not candidates:return {"status":"PENDING","candidate_id":None,"candidate_hash":None,"cut_off":None,"manifest":"PENDING","completeness":"PENDING","cash":"PENDING","positions":"PENDING","lots":"PENDING","attribution":None,"fx":None,"exceptions":0,"largest_difference":None,"approval":"UNAPPROVED","inactive":True,"pointer":"ABSENT","readiness":"NOT_READY","validated_at":None}
        path=candidates[-1];candidate=json.loads((path/"candidate.json").read_text(encoding="utf-8"));reconciliation=json.loads((path/"reconciliation.json").read_text(encoding="utf-8"))
        differences=reconciliation.get("differences",[]);blocking=any(item.get("blocking") for item in differences)
        return {"status":candidate.get("lifecycle_status"),"candidate_id":candidate.get("candidate_id"),"candidate_hash":candidate.get("candidate_hash"),"cut_off":candidate.get("cut_off",{}).get("cut_off_timestamp"),"manifest":"VALID","completeness":"COMPLETE","cash":"RECONCILED" if not blocking else "ERROR","positions":"RECONCILED" if not blocking else "ERROR","lots":"RECONCILED" if not blocking else "ERROR","attribution":candidate.get("strategy_attribution_coverage"),"fx":candidate.get("fx_evidence_coverage"),"exceptions":len(candidate.get("unresolved_items",[])),"largest_difference":max((item.get("absolute_difference","0") for item in differences),default="0"),"approval":"PRESENT" if (path/"approval.json").exists() else candidate.get("approval_status","UNAPPROVED"),"inactive":candidate.get("active") is False,"pointer":"ABSENT","readiness":"NOT_READY","validated_at":candidate.get("creation_timestamp")}
    except Exception as exc:return {"status":"ERROR","error":str(exc),"readiness":"NOT_READY","inactive":True,"pointer":"UNKNOWN"}
