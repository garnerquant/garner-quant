from __future__ import annotations

from decimal import Decimal

from canonical_accounting.snapshot import CanonicalPortfolioSnapshot


FIELDS = ("cash", "realised_pnl", "unrealised_pnl", "total_equity", "gross_exposure", "net_exposure")


def compare_legacy_to_canonical(legacy_state: dict, snapshot: CanonicalPortfolioSnapshot, *, tolerance=Decimal("0.01")):
    tolerance = Decimal(str(tolerance)); differences = []
    for field in FIELDS:
        canonical = Decimal(str(getattr(snapshot, field)))
        legacy_value = legacy_state.get(field)
        if legacy_value is None:
            differences.append({"field": field, "legacy": None, "canonical": str(canonical), "difference": None, "status": "UNAVAILABLE"})
            continue
        legacy = Decimal(str(legacy_value)); delta = canonical - legacy
        differences.append({"field": field, "legacy": str(legacy), "canonical": str(canonical),
                            "difference": str(delta), "status": "MATCH" if abs(delta) <= tolerance else "DIFFERENT"})
    legacy_positions = {str(key): Decimal(str(value)) for key, value in (legacy_state.get("positions") or {}).items()}
    canonical_positions = {item.instrument: item.quantity for item in snapshot.positions}
    for symbol in sorted(set(legacy_positions) | set(canonical_positions)):
        legacy = legacy_positions.get(symbol, Decimal("0")); canonical = canonical_positions.get(symbol, Decimal("0")); delta = canonical-legacy
        differences.append({"field": f"position:{symbol}", "legacy": str(legacy), "canonical": str(canonical),
                            "difference": str(delta), "status": "MATCH" if abs(delta) <= tolerance else "DIFFERENT"})
    return {"generation_id": snapshot.generation_id, "differences": differences,
            "matches": all(item["status"] == "MATCH" for item in differences),
            "automatic_corrections": 0}
