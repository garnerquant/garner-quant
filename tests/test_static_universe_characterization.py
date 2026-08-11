"""Characterization of retrospective use of the static current universe.

FIND-002/FIND-011 characterization

This test records the current behaviour in which the present hard-coded asset
universe is applied retrospectively across historical data without
valid-from/valid-to membership evidence. It demonstrates selection and
survivorship-bias risk, but does not estimate the magnitude of that bias. A
deliberately fixed prospective universe is a different, potentially valid
experiment when labelled explicitly.

The long-term replacement must require a versioned universe or an explicitly
named fixed-universe experiment with a declared inception date.
"""

import ast
import inspect
from datetime import date
from pathlib import Path

import config
from data import market_data


ROOT = Path(__file__).parents[1]
MAIN_SOURCE = (ROOT / "main_v2.py").read_text(encoding="utf-8")
MARKET_DATA_SOURCE = (ROOT / "data" / "market_data.py").read_text(encoding="utf-8")
MEMBERSHIP_FIELDS = {
    "valid_from", "valid_to", "effective_from", "effective_to",
    "membership_start", "membership_end", "delisting_date", "as_of", "available_at",
}


def _current_selection_for_historical_date(_historical_date):
    """Mirror the observed current-key selection without touching production code."""
    return tuple(config.ASSETS.keys())


def _call_nodes(source, function_name):
    tree = ast.parse(source)
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id == function_name)
             or (isinstance(node.func, ast.Attribute) and node.func.attr == function_name))
    ]


def test_current_assets_is_one_static_mapping_without_membership_fields():
    assert isinstance(config.ASSETS, dict)
    assert config.ASSETS
    assert all(isinstance(symbol, str) for symbol in config.ASSETS)
    assert not any(MEMBERSHIP_FIELDS.intersection(metadata) for metadata in config.ASSETS.values())
    assert not any(
        name in {"resolve_universe", "universe_for_date", "membership_for_date"}
        for name in dir(config)
    )


def test_active_historical_path_uses_current_asset_keys_and_multiperiod_data():
    tree = ast.parse(MAIN_SOURCE)
    asset_key_uses = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ASSETS"
        and node.attr == "keys"
    ]
    assert asset_key_uses

    download_calls = _call_nodes(MAIN_SOURCE, "download_market_data")
    assert len(download_calls) == 1
    tickers_argument = download_calls[0].args[0]
    assert isinstance(tickers_argument, ast.Name)
    assert tickers_argument.id == "tickers"

    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "tickers" for target in node.targets)
    ]
    assert assignments
    assert "ASSETS" in ast.unparse(assignments[0].value)
    assert "keys" in ast.unparse(assignments[0].value)

    period_defaults = [
        node for node in ast.walk(ast.parse(MARKET_DATA_SOURCE))
        if isinstance(node, ast.FunctionDef) and node.name == "download_market_data"
    ]
    assert len(period_defaults) == 1
    function = period_defaults[0]
    period_argument = next(
        default for argument, default in zip(function.args.args[-1:], function.args.defaults)
        if argument.arg == "period"
    )
    assert ast.literal_eval(period_argument) == "3y"

    # No historical-date loop or date-aware universe resolver is present in the selection path.
    assert not any("membership" in ast.unparse(node).lower() for node in ast.walk(tree))


def test_active_universe_interfaces_have_no_membership_time_context():
    main_tree = ast.parse(MAIN_SOURCE)
    main_functions = [node for node in ast.walk(main_tree) if isinstance(node, ast.FunctionDef)]
    selection_function = next(node for node in main_functions if node.name == "_run_main_unlocked")
    parameter_names = {argument.arg for argument in selection_function.args.args}
    assert "eligible_symbols" in parameter_names
    assert not parameter_names.intersection(MEMBERSHIP_FIELDS | {"membership_date", "information_cutoff", "universe_version"})

    signature = inspect.signature(market_data.download_market_data)
    assert set(signature.parameters).isdisjoint(MEMBERSHIP_FIELDS | {"membership_date", "information_cutoff", "universe_version"})
    assert "tickers" in signature.parameters
    assert "period" in signature.parameters


def test_same_current_ticker_set_is_used_for_separated_historical_dates():
    early = _current_selection_for_historical_date(date(2024, 1, 2))
    middle = _current_selection_for_historical_date(date(2024, 6, 3))
    late = _current_selection_for_historical_date(date(2025, 1, 2))
    assert early == middle == late == tuple(config.ASSETS.keys())
    assert len(early) == len(set(early))
    assert all(symbol in config.ASSETS for symbol in early)
