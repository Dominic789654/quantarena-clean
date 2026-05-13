from backtest.fof_allocator import FOFAllocator, SleeveSnapshot


def test_fof_allocator_bear_regime_boosts_defensive_sleeves_and_caps_stock_weights():
    allocator = FOFAllocator()
    sleeves = {
        "conservative": SleeveSnapshot(
            personality="conservative",
            target_weights={"AAA": 0.5, "BBB": 0.5},
            metrics={"gross_exposure": 1.0},
        ),
        "balanced": SleeveSnapshot(
            personality="balanced",
            target_weights={"AAA": 0.6, "CCC": 0.4},
            metrics={"gross_exposure": 1.0},
        ),
        "aggressive": SleeveSnapshot(
            personality="aggressive",
            target_weights={"AAA": 1.0},
            metrics={"gross_exposure": 1.0},
        ),
        "passive": SleeveSnapshot(
            personality="passive",
            target_weights={"BBB": 0.5, "CCC": 0.5},
            metrics={"gross_exposure": 1.0},
        ),
    }

    result = allocator.allocate(
        sleeves=sleeves,
        market_context={
            "regime": "bear",
            "signal_bias": -0.4,
            "avg_signal_consistency": 0.7,
        },
    )

    assert result.diagnostics["regime"] == "bear"
    assert result.sleeve_weights["conservative"] > result.sleeve_weights["aggressive"]
    assert result.sleeve_weights["passive"] >= 0.20
    assert sum(result.sleeve_weights.values()) == 1.0
    assert max(result.final_stock_weights.values()) <= 0.15


def test_fof_allocator_normalizes_available_sleeves_only():
    allocator = FOFAllocator(config={"base_weights": {"balanced": 0.7, "passive": 0.3}})
    sleeves = {
        "balanced": SleeveSnapshot("balanced", {"AAA": 0.7, "BBB": 0.3}),
        "passive": SleeveSnapshot("passive", {"AAA": 0.2, "CCC": 0.8}),
    }

    result = allocator.allocate(sleeves=sleeves, market_context={"regime": "neutral"})

    assert set(result.sleeve_weights) == {"balanced", "passive"}
    assert abs(sum(result.sleeve_weights.values()) - 1.0) < 1e-9
    assert set(result.final_stock_weights) == {"AAA", "BBB", "CCC"}
