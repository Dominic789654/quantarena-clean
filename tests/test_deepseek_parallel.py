"""
Parallel test for DeepSeek-v3.2 model compatibility
Compares performance with Doubao
"""

import os
import sys
import time
import concurrent.futures
from typing import Any, List
from dataclasses import dataclass
from pydantic import BaseModel, Field

# Add paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "deepear", "src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "deepfund", "src"))

from deepfund.src.llm.inference import agent_call, LLMConfig, get_model, reset_token_tracker, get_token_stats


@dataclass
class TestResult:
    """Result of a single test"""
    name: str
    success: bool
    duration: float
    error: str = ""
    data: Any = None


class AnalystSignal(BaseModel):
    """Test model matching DeepFund's AnalystSignal"""
    signal: str = Field(default="NEUTRAL", description="BULLISH, BEARISH, or NEUTRAL")
    confidence: float = Field(default=50.0, description="Confidence from 0 to 100", ge=0, le=100)
    justification: str = Field(default="Error occurred", description="Brief explanation")


class TradingDecision(BaseModel):
    """Test model for portfolio manager"""
    action: str = Field(default="HOLD", description="BUY, SELL, or HOLD")
    shares: int = Field(default=0, description="Number of shares", ge=0)
    reasoning: str = Field(default="Default reasoning", description="Explanation for the decision")


class DeepSeekParallelTester:
    """Parallel test runner for DeepSeek-v3.2 compatibility"""

    def __init__(self, api_key: str, provider: str = "ark"):
        self.api_key = api_key
        self.provider = provider
        self.config = {
            "provider": provider,
            "model": "deepseek-v3.2",
            "temperature": 0.5,
            "max_retries": 2
        }

    def test_model_init(self) -> TestResult:
        """Test 1: Model initialization"""
        start_time = time.time()
        try:
            llm_cfg = LLMConfig(**self.config)
            llm = get_model(llm_cfg)

            assert llm is not None
            assert llm.model == self.config["model"]

            return TestResult(
                name="Model Initialization",
                success=True,
                duration=time.time() - start_time,
                data={"model_type": type(llm).__name__}
            )
        except Exception as e:
            return TestResult(
                name="Model Initialization",
                success=False,
                duration=time.time() - start_time,
                error=str(e)
            )

    def test_function_calling(self) -> TestResult:
        """Test 2: Function calling"""
        start_time = time.time()
        try:
            prompt = "Analyze AAPL stock with price $185, PE 29.5, growth 5%"

            result = agent_call(
                prompt=prompt,
                llm_config=self.config,
                pydantic_model=AnalystSignal,
                agent_name="deepseek_test_1"
            )

            assert isinstance(result, AnalystSignal)
            assert result.signal.upper() in ["BULLISH", "BEARISH", "NEUTRAL"]
            assert 0 <= result.confidence <= 100

            return TestResult(
                name="Function Calling",
                success=True,
                duration=time.time() - start_time,
                data={"signal": result.signal, "confidence": result.confidence}
            )
        except Exception as e:
            return TestResult(
                name="Function Calling",
                success=False,
                duration=time.time() - start_time,
                error=str(e)
            )

    def test_json_mode(self) -> TestResult:
        """Test 3: JSON mode (if supported)"""
        start_time = time.time()
        try:
            prompt = """
            Analyze the following fundamentals:

            Company: Kweichow Moutai (600519)
            ROE: 26.37%, ROA: 29.41%, PE: 21.59
            Revenue Growth: 17.9%, Net Margin: 52.7%

            Provide a signal in JSON format.
            """

            result = agent_call(
                prompt=prompt,
                llm_config=self.config,
                pydantic_model=AnalystSignal,
                agent_name="deepseek_json_test"
            )

            return TestResult(
                name="JSON Mode",
                success=True,
                duration=time.time() - start_time,
                data={"signal": result.signal, "confidence": result.confidence}
            )
        except Exception as e:
            return TestResult(
                name="JSON Mode",
                success=False,
                duration=time.time() - start_time,
                error=str(e)
            )

    def test_analyst_fundamental(self) -> TestResult:
        """Test 4: Fundamental analyst"""
        start_time = time.time()
        try:
            prompt = """
            Analyze the following fundamentals:

            Company: Kweichow Moutai (600519)
            ROE: 26.37%, ROA: 29.41%, PE: 21.59
            Revenue Growth: 17.9%, Net Margin: 52.7%

            Provide a signal.
            """

            result = agent_call(
                prompt=prompt,
                llm_config=self.config,
                pydantic_model=AnalystSignal,
                agent_name="fundamental"
            )

            return TestResult(
                name="Fundamental Analyst",
                success=True,
                duration=time.time() - start_time,
                data={"signal": result.signal, "confidence": result.confidence}
            )
        except Exception as e:
            return TestResult(
                name="Fundamental Analyst",
                success=False,
                duration=time.time() - start_time,
                error=str(e)
            )

    def test_analyst_technical(self) -> TestResult:
        """Test 5: Technical analyst"""
        start_time = time.time()
        try:
            prompt = """
            Analyze the following technicals:

            Stock: NVDA
            Price: $875, RSI: 68, MA50: $820, MA200: $650
            Volume: 2.5M (above average)

            Provide a signal.
            """

            result = agent_call(
                prompt=prompt,
                llm_config=self.config,
                pydantic_model=AnalystSignal,
                agent_name="technical"
            )

            return TestResult(
                name="Technical Analyst",
                success=True,
                duration=time.time() - start_time,
                data={"signal": result.signal, "confidence": result.confidence}
            )
        except Exception as e:
            return TestResult(
                name="Technical Analyst",
                success=False,
                duration=time.time() - start_time,
                error=str(e)
            )

    def test_portfolio_decision(self) -> TestResult:
        """Test 6: Portfolio manager decision"""
        start_time = time.time()
        try:
            prompt = """
            As a portfolio manager, decide:

            Stock: 600519 at ¥1640
            Cash: ¥100,000, Position: 0 shares
            Signals: Bullish (85%), Neutral (60%)
            Risk limit: 20% position

            Make a trading decision.
            """

            result = agent_call(
                prompt=prompt,
                llm_config=self.config,
                pydantic_model=TradingDecision,
                agent_name="portfolio_manager"
            )

            return TestResult(
                name="Portfolio Decision",
                success=True,
                duration=time.time() - start_time,
                data={"action": result.action, "shares": result.shares}
            )
        except Exception as e:
            return TestResult(
                name="Portfolio Decision",
                success=False,
                duration=time.time() - start_time,
                error=str(e)
            )

    def test_token_tracking(self) -> TestResult:
        """Test 7: Token tracking"""
        start_time = time.time()
        try:
            reset_token_tracker()

            prompt = "Test token tracking for NVDA analysis"

            agent_call(
                prompt=prompt,
                llm_config=self.config,
                pydantic_model=AnalystSignal,
                agent_name="token_tracker"
            )

            stats = get_token_stats()

            assert stats["calls"] > 0
            assert "token_tracker" in stats["by_agent"]

            return TestResult(
                name="Token Tracking",
                success=True,
                duration=time.time() - start_time,
                data={"calls": stats["calls"], "tokens": stats["total_output"]}
            )
        except Exception as e:
            return TestResult(
                name="Token Tracking",
                success=False,
                duration=time.time() - start_time,
                error=str(e)
            )

    def run_parallel(self, max_workers: int = 4) -> List[TestResult]:
        """Run all tests in parallel"""
        print(f"\n🚀 Running {max_workers} tests in parallel...")

        # Define test functions to run
        test_functions = [
            self.test_model_init,
            self.test_function_calling,
            self.test_json_mode,
            self.test_analyst_fundamental,
            self.test_analyst_technical,
            self.test_portfolio_decision,
            self.test_token_tracking,
        ]

        results = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tests
            future_to_test = {
                executor.submit(func): func.__name__
                for func in test_functions
            }

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_test):
                test_name = future_to_test[future]
                try:
                    result = future.result(timeout=60)  # 60 second timeout per test
                    results.append(result)
                    status = "✅" if result.success else "❌"
                    print(f"{status} {result.name}: {result.duration:.2f}s")
                except concurrent.futures.TimeoutError:
                    results.append(TestResult(
                        name=test_name,
                        success=False,
                        duration=60.0,
                        error="Timeout after 60 seconds"
                    ))
                    print(f"❌ {test_name}: TIMEOUT (60s)")
                except Exception as e:
                    results.append(TestResult(
                        name=test_name,
                        success=False,
                        duration=0.0,
                        error=str(e)
                    ))
                    print(f"❌ {test_name}: ERROR ({e})")

        return results

    def run_sequential(self) -> List[TestResult]:
        """Run all tests sequentially (for comparison)"""
        print("\n🐢 Running tests sequentially...")

        test_functions = [
            self.test_model_init,
            self.test_function_calling,
            self.test_json_mode,
            self.test_analyst_fundamental,
            self.test_analyst_technical,
            self.test_portfolio_decision,
            self.test_token_tracking,
        ]

        results = []
        for func in test_functions:
            start_time = time.time()
            try:
                result = func()
                results.append(result)
                status = "✅" if result.success else "❌"
                print(f"{status} {result.name}: {result.duration:.2f}s")
            except Exception as e:
                results.append(TestResult(
                    name=func.__name__,
                    success=False,
                    duration=time.time() - start_time,
                    error=str(e)
                ))
                print(f"❌ {func.__name__}: ERROR ({e})")

        return results


def print_summary(results: List[TestResult], mode: str):
    """Print test summary"""
    print(f"\n{'='*70}")
    print(f"📊 {mode} Test Summary")
    print('='*70)

    total_time = sum(r.duration for r in results)
    successful = sum(1 for r in results if r.success)

    print(f"{'Test':<30} {'Status':<10} {'Time':<8} {'Details':<20}")
    print('-'*70)

    for result in results:
        status = "PASS" if result.success else "FAIL"
        time_str = f"{result.duration:.2f}s"

        if result.success and result.data:
            details = str(result.data)[:30] + "..."
        else:
            details = result.error[:30] + "..." if result.error else ""

        print(f"{result.name:<30} {status:<10} {time_str:<8} {details:<20}")

    print('-'*70)
    print(f"Total: {successful}/{len(results)} passed in {total_time:.2f}s")
    print('='*70)


def main():
    """Main function"""
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        print("❌ ARK_API_KEY not set. Set environment variable or use --api-key")
        return

    print("\n" + "="*70)
    print("🧪 DeepSeek-v3.2 Parallel Compatibility Test Suite")
    print("="*70)

    tester = DeepSeekParallelTester(api_key, provider="ark")

    # Run sequential first (baseline)
    seq_results = tester.run_sequential()
    print_summary(seq_results, "Sequential")

    # Run parallel
    par_results = tester.run_parallel(max_workers=6)
    print_summary(par_results, "Parallel (6 workers)")

    # Compare performance
    seq_time = sum(r.duration for r in seq_results)
    par_time = sum(r.duration for r in par_results)

    print("\n📈 Performance Comparison:")
    print(f"  Sequential: {seq_time:.2f}s")
    print(f"  Parallel:   {par_time:.2f}s")
    if par_time > 0:
        print(f"  Speedup:    {seq_time/par_time:.2f}x")

    # Check success rates
    seq_success = sum(1 for r in seq_results if r.success)
    par_success = sum(1 for r in par_results if r.success)

    if seq_success == len(seq_results) and par_success == len(par_results):
        print("\n🎉 All tests passed! DeepSeek-v3.2 is compatible with parallel execution.")
    else:
        print(f"\n⚠️  Some tests failed. Sequential: {seq_success}/{len(seq_results)}, Parallel: {par_success}/{len(par_results)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parallel test for DeepSeek compatibility")
    parser.add_argument("--api-key", help="API key (or set ARK_API_KEY env)")
    parser.add_argument("--provider", default="ark", help="Provider: ark or yizhan")
    parser.add_argument("--sequential-only", action="store_true", help="Run sequential only")
    parser.add_argument("--parallel-only", action="store_true", help="Run parallel only")
    parser.add_argument("--workers", type=int, default=6, help="Number of parallel workers")

    args = parser.parse_args()

    if args.api_key:
        os.environ["ARK_API_KEY"] = args.api_key

    if args.sequential_only:
        # Run only sequential
        api_key = os.getenv("ARK_API_KEY")
        tester = DeepSeekParallelTester(api_key, provider=args.provider)
        seq_results = tester.run_sequential()
        print_summary(seq_results, "Sequential")
    elif args.parallel_only:
        # Run only parallel
        api_key = os.getenv("ARK_API_KEY")
        tester = DeepSeekParallelTester(api_key, provider=args.provider)
        par_results = tester.run_parallel(max_workers=args.workers)
        print_summary(par_results, f"Parallel ({args.workers} workers)")
    else:
        # Run both
        main()
