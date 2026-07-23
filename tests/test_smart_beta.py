#!/usr/bin/env python
"""
Smart Beta Integration Test
===========================

Tests the Smart Beta index enhancement system components:
1. Factor calculation engine
2. Portfolio optimizer
3. Macro state analyzer
4. News freeze mechanism
5. Full allocator integration
"""

import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

print(f"Project root: {PROJECT_ROOT}")
print("Python path updated")


def test_config():
    """Test Smart Beta configuration."""
    print("\n" + "=" * 60)
    print("TEST: Smart Beta Configuration")
    print("=" * 60)

    try:
        from smart_beta.config import SmartBetaConfig

        # Test default config
        config = SmartBetaConfig()
        print("✓ Default config created")
        print(f"  - Index code: {config.index_code}")
        print(f"  - Rebalance frequency: {config.rebalance_frequency}")
        print(f"  - Lookback days: {config.lookback_days}")
        print(f"  - IVOL percentile: {config.ivol_percentile}")
        print(f"  - Tracking error limit: {config.tracking_error_limit}")

        # Validate config
        config.validate()
        print("✓ Configuration validated")

        # Test beta target by macro state
        for state in ["expansion", "slowdown", "recession", "recovery"]:
            beta = config.get_beta_target(state)
            print(f"  - {state}: beta = {beta}")

        return True

    except Exception as e:
        print(f"✗ Configuration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_factor_engine():
    """Test factor calculation engine."""
    print("\n" + "=" * 60)
    print("TEST: Factor Calculation Engine")
    print("=" * 60)

    try:
        from smart_beta.factor_engine import FactorEngine

        engine = FactorEngine()
        print("✓ Factor engine initialized")

        # Create synthetic test data
        np.random.seed(42)
        n_days = 100

        dates = pd.date_range(end=datetime.now(), periods=n_days, freq='D')

        # Stock returns (slightly correlated with market)
        market_returns = np.random.normal(0.0005, 0.02, n_days)
        stock_returns = market_returns * 1.1 + np.random.normal(0, 0.01, n_days)

        stock_data = pd.DataFrame({
            'close': 100 * np.cumprod(1 + stock_returns),
            'volume': np.random.randint(1000000, 10000000, n_days)
        }, index=dates)

        market_data = pd.DataFrame({
            'close': 100 * np.cumprod(1 + market_returns)
        }, index=dates)

        print(f"  - Stock data shape: {stock_data.shape}")
        print(f"  - Market data shape: {market_data.shape}")

        # Test Dimson Beta
        dimson_beta = engine.calculate_dimson_beta(
            pd.Series(stock_returns, index=dates),
            pd.Series(market_returns, index=dates)
        )
        print(f"  - Dimson Beta: {dimson_beta:.4f}" if dimson_beta else "  - Dimson Beta: None")

        # Test Downside Beta
        downside_beta = engine.calculate_downside_beta(
            pd.Series(stock_returns, index=dates),
            pd.Series(market_returns, index=dates)
        )
        print(f"  - Downside Beta: {downside_beta:.4f}" if downside_beta else "  - Downside Beta: None")

        # Test IVOL
        ivol = engine.calculate_ivol(
            pd.Series(stock_returns, index=dates),
            pd.Series(market_returns, index=dates)
        )
        print(f"  - IVOL: {ivol:.4f}" if ivol else "  - IVOL: None")

        # Test Amihud
        amihud = engine.calculate_amihud(
            pd.Series(stock_returns, index=dates),
            stock_data['volume']
        )
        print(f"  - Amihud: {amihud:.6f}" if amihud else "  - Amihud: None")

        # Test full factor calculation
        factor_data = engine.calculate_all_factors(
            ticker="TEST001",
            stock_data=stock_data,
            market_data=market_data,
            trade_date=datetime.now()
        )
        print(f"✓ Full factor calculation: {factor_data}")

        return True

    except Exception as e:
        print(f"✗ Factor engine test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_optimizer():
    """Test portfolio optimizer."""
    print("\n" + "=" * 60)
    print("TEST: Portfolio Optimizer")
    print("=" * 60)

    try:
        from smart_beta.optimizer import SmartBetaOptimizer
        from smart_beta.factor_engine import FactorData

        optimizer = SmartBetaOptimizer()
        print("✓ Optimizer initialized")

        # Create test data
        tickers = ["STOCK_A", "STOCK_B", "STOCK_C", "STOCK_D", "STOCK_E"]

        benchmark_weights = {t: 1/len(tickers) for t in tickers}
        print(f"  - Benchmark weights: equal weight ({1/len(tickers):.2%} each)")

        # Create synthetic factor data
        np.random.seed(42)
        factor_data = {}
        for t in tickers:
            factor_data[t] = FactorData(
                ticker=t,
                trade_date=datetime.now(),
                dimson_beta=np.random.uniform(0.8, 1.2),
                downside_beta=np.random.uniform(0.7, 1.1),
                ivol=np.random.uniform(0.15, 0.35),
                amihud=np.random.uniform(0.001, 0.01),
                factor_score=np.random.uniform(0.3, 0.7),
                is_valid=True
            )

        # Run optimization
        result = optimizer.optimize(
            tickers=tickers,
            benchmark_weights=benchmark_weights,
            factor_data=factor_data
        )

        print("✓ Optimization result:")
        print(f"  - Success: {result.success}")
        print(f"  - Message: {result.message}")
        print(f"  - Tracking error: {result.tracking_error:.6f}")
        print(f"  - Turnover: {result.turnover:.4f}")

        if result.weights:
            print("  - Weights:")
            for t, w in sorted(result.weights.items(), key=lambda x: x[1], reverse=True):
                print(f"      {t}: {w:.4f}")

        # Test negative screening
        passed = optimizer.negative_screening(tickers, factor_data)
        print(f"  - Stocks passing negative screening: {len(passed)}/{len(tickers)}")

        return True

    except Exception as e:
        print(f"✗ Optimizer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_macro_analyzer():
    """Test macro state analyzer."""
    print("\n" + "=" * 60)
    print("TEST: Macro State Analyzer")
    print("=" * 60)

    try:
        from smart_beta.macro_analyzer import MacroStateAnalyzer

        analyzer = MacroStateAnalyzer()
        print("✓ Macro analyzer initialized")

        # Test with expansion indicators
        expansion_indicators = {
            "gdp_growth": 0.065,
            "cpi_yoy": 0.022,
            "pmi": 52.5,
            "m2_growth": 0.11,
            "unemployment_rate": 0.038
        }

        result = analyzer.analyze(expansion_indicators, datetime.now())
        print("  - Expansion scenario:")
        print(f"      State: {result.state.value}")
        print(f"      Score: {result.score:.4f}")
        print(f"      Beta adjustment: {result.beta_adjustment:.4f}")
        print(f"      Confidence: {result.confidence:.2%}")

        # Test with recession indicators
        recession_indicators = {
            "gdp_growth": 0.015,
            "cpi_yoy": 0.001,
            "pmi": 45.0,
            "m2_growth": 0.04,
            "unemployment_rate": 0.07
        }

        result = analyzer.analyze(recession_indicators, datetime.now())
        print("  - Recession scenario:")
        print(f"      State: {result.state.value}")
        print(f"      Score: {result.score:.4f}")
        print(f"      Beta adjustment: {result.beta_adjustment:.4f}")
        print(f"      Confidence: {result.confidence:.2%}")

        return True

    except Exception as e:
        print(f"✗ Macro analyzer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_news_freeze():
    """Test news freeze mechanism."""
    print("\n" + "=" * 60)
    print("TEST: News Freeze Mechanism")
    print("=" * 60)

    try:
        from smart_beta.news_freeze import NewsFreezeMechanism

        freeze = NewsFreezeMechanism()
        print("✓ News freeze mechanism initialized")

        # Test with normal market
        decision = freeze.check(
            market_volatility=18.0,
            market_return=0.01,
            news_items=None,
            current_date=datetime.now()
        )
        print("  - Normal market:")
        print(f"      Status: {decision.status.value}")
        print(f"      Reason: {decision.reason.value}")
        print(f"      Confidence: {decision.confidence:.2f}")

        # Test with high volatility
        decision = freeze.check(
            market_volatility=35.0,
            market_return=-0.02,
            news_items=None,
            current_date=datetime.now()
        )
        print("  - High volatility (VIX=35):")
        print(f"      Status: {decision.status.value}")
        print(f"      Reason: {decision.reason.value}")
        print(f"      Confidence: {decision.confidence:.2f}")
        print(f"      Triggers: {decision.triggers}")

        # Test with market crash
        freeze2 = NewsFreezeMechanism()  # Fresh instance
        decision = freeze2.check(
            market_volatility=25.0,
            market_return=-0.07,
            news_items=[
                {"title": "Market crashes amid crisis concerns", "content": "..."}
            ],
            current_date=datetime.now()
        )
        print("  - Market crash (-7%):")
        print(f"      Status: {decision.status.value}")
        print(f"      Reason: {decision.reason.value}")
        print(f"      Confidence: {decision.confidence:.2f}")
        print(f"      Triggers: {decision.triggers}")
        print(f"      Is active: {decision.is_active}")
        print(f"      Days remaining: {decision.days_remaining()}")

        return True

    except Exception as e:
        print(f"✗ News freeze test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_allocator():
    """Test Smart Beta allocator integration."""
    print("\n" + "=" * 60)
    print("TEST: Smart Beta Allocator Integration")
    print("=" * 60)

    try:
        from smart_beta.smart_beta_allocator import SmartBetaAllocator

        allocator = SmartBetaAllocator()
        print("✓ Smart Beta allocator initialized")

        # Create synthetic test data
        np.random.seed(42)
        n_days = 100
        dates = pd.date_range(end=datetime.now(), periods=n_days, freq='D')

        tickers = ["STOCK_A", "STOCK_B", "STOCK_C", "STOCK_D", "STOCK_E"]

        stock_data = {}
        for ticker in tickers:
            returns = np.random.normal(0.0005, 0.02, n_days)
            stock_data[ticker] = pd.DataFrame({
                'close': 100 * np.cumprod(1 + returns),
                'volume': np.random.randint(1000000, 10000000, n_days)
            }, index=dates)

        market_returns = np.random.normal(0.0004, 0.015, n_days)
        market_data = pd.DataFrame({
            'close': 100 * np.cumprod(1 + market_returns)
        }, index=dates)

        # Current portfolio
        current_portfolio = {t: 100 for t in tickers[:3]}  # Only first 3 stocks

        # Prices
        prices = {t: stock_data[t]['close'].iloc[-1] for t in tickers}

        # Macro indicators
        macro_indicators = {
            "gdp_growth": 0.05,
            "cpi_yoy": 0.025,
            "pmi": 51.0
        }

        # Run allocation
        result = allocator.allocate(
            trade_date=datetime.now(),
            stock_data=stock_data,
            market_data=market_data,
            current_portfolio=current_portfolio,
            prices=prices,
            macro_indicators=macro_indicators
        )

        print("✓ Allocation result:")
        print(f"  - Success: {result.success}")
        print(f"  - Message: {result.message}")
        print(f"  - Tracking error: {result.tracking_error:.6f}")
        print(f"  - Macro adjustment: {result.macro_adjustment:.4f}")
        print(f"  - Turnover: {result.turnover:.4f}")

        if result.weights:
            print("  - Top 5 weights:")
            sorted_weights = sorted(result.weights.items(), key=lambda x: x[1], reverse=True)[:5]
            for t, w in sorted_weights:
                print(f"      {t}: {w:.4f}")

        # Test trading decisions
        decisions = allocator.get_trading_decisions(
            allocation=result,
            current_portfolio=current_portfolio,
            prices=prices,
            total_capital=100000
        )

        print(f"  - Trading decisions ({len(decisions)} trades):")
        for d in decisions[:3]:
            print(f"      {d['action']} {d['shares']} {d['ticker']} @ {d['price']:.2f}")

        return True

    except Exception as e:
        print(f"✗ Allocator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_metrics():
    """Test Smart Beta performance metrics."""
    print("\n" + "=" * 60)
    print("TEST: Smart Beta Performance Metrics")
    print("=" * 60)

    try:
        from backtest.metrics import PerformanceMetrics
        import pandas as pd
        import numpy as np

        # Create synthetic returns
        np.random.seed(42)
        n_days = 100

        # Portfolio slightly outperforms benchmark
        benchmark_returns = pd.Series(np.random.normal(0.05, 2, n_days))
        portfolio_returns = benchmark_returns + np.random.normal(0.1, 0.5, n_days)  # Small alpha

        # Calculate metrics
        te = PerformanceMetrics.tracking_error(portfolio_returns, benchmark_returns)
        ir = PerformanceMetrics.information_ratio(portfolio_returns, benchmark_returns)
        beta = PerformanceMetrics.beta(portfolio_returns, benchmark_returns)
        alpha = PerformanceMetrics.alpha(portfolio_returns, benchmark_returns)
        excess = PerformanceMetrics.excess_return(portfolio_returns, benchmark_returns)

        print("✓ Smart Beta metrics calculated:")
        print(f"  - Tracking Error: {te:.4f}%")
        print(f"  - Information Ratio: {ir:.4f}")
        print(f"  - Beta: {beta:.4f}")
        print(f"  - Alpha: {alpha:.4f}%")
        print(f"  - Excess Return: {excess:.4f}%")

        # Test all metrics at once
        all_metrics = PerformanceMetrics.calculate_smart_beta_metrics(
            portfolio_returns, benchmark_returns
        )
        print(f"  - All metrics: {all_metrics}")

        return True

    except Exception as e:
        print(f"✗ Metrics test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SMART BETA INTEGRATION TEST SUITE")
    print("=" * 60)

    results = {}

    # Run tests
    results["Config"] = test_config()
    results["Factor Engine"] = test_factor_engine()
    results["Optimizer"] = test_optimizer()
    results["Macro Analyzer"] = test_macro_analyzer()
    results["News Freeze"] = test_news_freeze()
    results["Allocator"] = test_allocator()
    results["Metrics"] = test_metrics()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All Smart Beta components are working correctly!")
        return 0
    else:
        print("\n⚠️ Some tests failed. Check the output above for details.")
        return 1


if __name__ == "__main__":
    exit(main())
