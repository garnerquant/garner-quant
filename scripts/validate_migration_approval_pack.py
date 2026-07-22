from __future__ import annotations
import ast,hashlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));PROTECTED=("trade_ledger_v1.csv","paper_portfolio_v3.csv","holdings_report.csv","broker_account.csv","paper_30_day_tracker.csv")
FORBIDDEN=("SuccessorGenerationWriter","publish_prepared","freeze_inactive_candidate","build_candidate","submit_order","place_order","broker_adapter","write_text(","write_bytes(","open(\"w")
def hashes():return {x:hashlib.sha256((ROOT/x).read_bytes()).hexdigest() for x in PROTECTED}
def check(v,l,issues):print(("PASS"if v else"FAIL")+": "+l);issues.append(l)if not v else None
def main():
 issues=[];before=hashes();pointer=ROOT/"data/accounting_generations/accounting_generation.json";candidate=ROOT/"data/opening_snapshot_candidates";gens=ROOT/"data/accounting_generations/generations";g0=sorted(x.name for x in gens.iterdir())if gens.exists()else[];c0=sorted(x.name for x in candidate.iterdir())if candidate.exists()else[]
 result=subprocess.run([sys.executable,"-m","unittest","tests.test_migration_approval_pack","-q"],cwd=ROOT);check(result.returncode==0,"migration pack tests",issues)
 source=(ROOT/"canonical_accounting/migration_approval.py").read_text();ast.parse(source);check(all(x not in source for x in FORBIDDEN),"governance subsystem has no persistence, candidate, generation, pointer, accounting, execution, or broker write path",issues)
 from canonical_accounting.evidence_pack import build_evidence_pack
 from canonical_accounting.migration_approval import build_migration_approval_pack
 now=datetime(2026,7,22,12,tzinfo=timezone.utc);e=build_evidence_pack(ROOT,as_of=now);p=build_migration_approval_pack(e,repository_commit="validator-fixture",created_at=now)
 check(p.pack_hash==build_migration_approval_pack(e,repository_commit="validator-fixture",created_at=now).pack_hash,"pack and proposal hashes are stable",issues);check(all(x.linked_gap_ids for x in p.proposals),"every proposal links evidence gaps",issues);check(p.readiness=="NOT_READY"and p.summary["PENDING"]==len(p.proposals),"pack remains pending and fail-closed",issues)
 dashboard=(ROOT/"pages/99_admin_health.py").read_text();section=dashboard[dashboard.index('Migration allocation and approval'):dashboard.index('Accounting observation envelopes')];check("button("not in section,"Operations migration section is read-only",issues)
 cfg=json.loads((ROOT/"runtime/live_runtime_config.json").read_text());check(cfg["mode"]=="monitor_only"and cfg["paper_execution_enabled"]is False,"runtime remains monitor_only and paper execution disabled",issues);check(not pointer.exists(),"production pointer remains absent",issues);check(g0==(sorted(x.name for x in gens.iterdir())if gens.exists()else[]),"no generation created",issues);check(c0==(sorted(x.name for x in candidate.iterdir())if candidate.exists()else[]),"no candidate created",issues);check(before==hashes(),"protected accounting files remain byte-identical",issues)
 if issues:raise SystemExit("Migration approval validation failed: "+"; ".join(issues))
 print("Migration allocation and approval pack validation passed.")
if __name__=="__main__":main()
