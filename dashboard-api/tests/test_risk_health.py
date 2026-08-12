import json
from app.evidence import risk_health

def test_risk_health_exposes_only_disabled_safety_state(tmp_path) -> None:
    (tmp_path / "live_runtime_config.json").write_text(json.dumps({"mode":"monitor_only", "paper_execution_enabled":False}))
    (tmp_path / "risk_config.json").write_text(json.dumps({"trading_enabled":False, "limits_approved":False, "maximum_order_notional_base":"999"}))
    result = risk_health(config_root=tmp_path)
    assert result.records[0].fields["trading_enabled"] == "false"
    assert "maximum_order_notional_base" not in result.records[0].fields
    assert result.records[0].fields["heartbeat"] is None

def test_risk_health_fails_closed_on_unsafe_state(tmp_path) -> None:
    (tmp_path / "live_runtime_config.json").write_text(json.dumps({"mode":"paper_execution", "paper_execution_enabled":True}))
    (tmp_path / "risk_config.json").write_text(json.dumps({"trading_enabled":False, "limits_approved":False}))
    assert risk_health(config_root=tmp_path).records == []
