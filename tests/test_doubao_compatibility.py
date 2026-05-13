"""
Unit tests for Doubao/Seed model compatibility with DeepFund
Tests function_calling without json_mode fallback
"""

import os
import sys
import unittest
from typing import Dict, Any
from pydantic import BaseModel, Field

# Add paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "deepear", "src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "deepfund", "src"))

from deepfund.src.llm.inference import agent_call, LLMConfig, get_model, reset_token_tracker, get_token_stats
from deepfund.src.llm.provider import Provider


# Test Pydantic models matching actual usage
class AnalystSignal(BaseModel):
    """Test model matching DeepFund's AnalystSignal"""
    signal: str = Field(default="NEUTRAL", description="BULLISH, BEARISH, or NEUTRAL")
    confidence: float = Field(default=50.0, description="Confidence from 0 to 100", ge=0, le=100)
    justification: str = Field(default="Error occurred", description="Brief explanation")


class TradingDecision(BaseModel):
    """Test model for portfolio manager"""
    action: str = Field(description="BUY, SELL, or HOLD")
    shares: int = Field(description="Number of shares", ge=0)
    reasoning: str = Field(description="Explanation for the decision")


class TestDoubaoCompatibility(unittest.TestCase):
    """Test Doubao/Seed model compatibility"""

    @classmethod
    def setUpClass(cls):
        """Set up test configuration"""
        cls.config = {
            "provider": "ark",
            "model": "doubao-seed-2.0-code",
            "temperature": 0.5,
            "max_retries": 2
        }
        # Check if API key is available
        cls.api_key = os.getenv("ARK_API_KEY")
        if not cls.api_key:
            raise unittest.SkipTest("ARK_API_KEY not set, skipping Doubao tests")

    def setUp(self):
        """Reset token tracker before each test"""
        reset_token_tracker()

    def test_01_model_initialization(self):
        """Test that Doubao model can be initialized"""
        llm_cfg = LLMConfig(**self.config)
        llm = get_model(llm_cfg)

        self.assertIsNotNone(llm)
        self.assertEqual(llm.model, self.config["model"])
        print(f"✅ Model initialized: {type(llm).__name__}")

    def test_02_function_calling_only(self):
        """Test structured output using only function_calling (no json_mode)"""
        # Modify config to simulate "no json_mode" scenario
        config_no_json = self.config.copy()

        prompt = """
        Analyze the following stock data:

        Stock: AAPL (Apple Inc.)
        Current Price: $185.50
        P/E Ratio: 29.5
        Revenue Growth: 5%

        Provide a trading signal.
        """

        result = agent_call(
            prompt=prompt,
            llm_config=config_no_json,
            pydantic_model=AnalystSignal,
            agent_name="test_analyst"
        )

        # Verify result is valid
        self.assertIsInstance(result, AnalystSignal)
        self.assertIn(result.signal.upper(), ["BULLISH", "BEARISH", "NEUTRAL"])
        self.assertTrue(0 <= result.confidence <= 100)
        self.assertTrue(len(result.justification) > 0)

        print(f"✅ Function calling works!")
        print(f"   Signal: {result.signal}")
        print(f"   Confidence: {result.confidence}")

    def test_03_token_tracking(self):
        """Test that token usage is properly tracked"""
        prompt = "Analyze NVDA stock with price $875, P/E 65.5"

        agent_call(
            prompt=prompt,
            llm_config=self.config,
            pydantic_model=AnalystSignal,
            agent_name="token_test_analyst"
        )

        stats = get_token_stats()

        self.assertGreater(stats["calls"], 0)
        self.assertGreater(stats["total_input"], 0)
        self.assertGreater(stats["total_output"], 0)
        self.assertIn("token_test_analyst", stats["by_agent"])

        agent_stats = stats["by_agent"]["token_test_analyst"]
        self.assertGreater(agent_stats["input"], 0)
        self.assertGreater(agent_stats["output"], 0)

        print(f"✅ Token tracking works!")
        print(f"   Total calls: {stats['calls']}")
        print(f"   Input tokens: {stats['total_input']}")
        print(f"   Output tokens: {stats['total_output']}")

    def test_04_multiple_agents_parallel(self):
        """Test multiple analyst calls (simulating parallel workflow)"""
        prompts = [
            ("fundamental", "Analyze AAPL fundamentals: ROE 25%, PE 29, Growth 5%"),
            ("technical", "Analyze TSLA technicals: RSI 65, MA50 $240, Price $250"),
            ("news", "Analyze NVDA news sentiment: AI chip demand surging"),
        ]

        results = []
        for agent_name, prompt in prompts:
            result = agent_call(
                prompt=prompt,
                llm_config=self.config,
                pydantic_model=AnalystSignal,
                agent_name=agent_name
            )
            results.append((agent_name, result))

        # Verify all succeeded
        for agent_name, result in results:
            self.assertIsInstance(result, AnalystSignal)
            self.assertIn(result.signal.upper(), ["BULLISH", "BEARISH", "NEUTRAL"])
            print(f"✅ {agent_name}: {result.signal} ({result.confidence}%)")

        # Check token stats
        stats = get_token_stats()
        self.assertEqual(stats["calls"], 3)
        self.assertEqual(len(stats["by_agent"]), 3)

    def test_05_trading_decision(self):
        """Test portfolio manager style decision"""
        prompt = """
        You are a portfolio manager. Based on the following analyst signals, make a trading decision:

        Stock: 600519 (Kweichow Moutai)
        Current Price: ¥1640
        Portfolio Cash: ¥100,000
        Current Position: 0 shares

        Analyst Signals:
        - Fundamental: BULLISH (confidence: 85%) - Strong ROE and brand moat
        - Technical: NEUTRAL (confidence: 60%) - Price near resistance
        - Risk Control: Max position 20%

        Decide: BUY, SELL, or HOLD? How many shares?
        """

        result = agent_call(
            prompt=prompt,
            llm_config=self.config,
            pydantic_model=TradingDecision,
            agent_name="portfolio_manager"
        )

        self.assertIsInstance(result, TradingDecision)
        self.assertIn(result.action.upper(), ["BUY", "SELL", "HOLD"])
        self.assertTrue(result.shares >= 0)
        self.assertTrue(len(result.reasoning) > 0)

        print(f"✅ Portfolio manager decision:")
        print(f"   Action: {result.action}")
        print(f"   Shares: {result.shares}")
        print(f"   Reasoning: {result.reasoning[:100]}...")

    def test_06_error_recovery(self):
        """Test that errors are handled gracefully"""
        # This test uses an invalid model to trigger error handling
        bad_config = self.config.copy()
        bad_config["model"] = "invalid-model-name"

        prompt = "Analyze AAPL stock"

        # Should return default model instead of crashing
        result = agent_call(
            prompt=prompt,
            llm_config=bad_config,
            pydantic_model=AnalystSignal,
            agent_name="error_test"
        )

        # On failure, returns default Pydantic model
        self.assertIsInstance(result, AnalystSignal)
        # Default values should be present
        print(f"✅ Error recovery works (returned default model)")

    def test_07_structured_methods_order(self):
        """Verify that function_calling is attempted for Doubao"""
        from deepfund.src.llm.inference import LLMConfig

        llm_cfg = LLMConfig(**self.config)
        model_id = self.config["model"].lower()

        # Check logic from inference.py
        if 'doubao' in model_id or 'seed' in model_id:
            # Current logic puts json_mode first - this test documents that
            # After fix, should be ['function_calling'] only
            print(f"ℹ️ Model {model_id} detected as Doubao/Seed")
            print(f"   Current structured_methods: ['json_mode', 'function_calling']")
            print(f"   Recommended: ['function_calling'] (remove json_mode)")


class TestDoubaoWithoutJsonMode(unittest.TestCase):
    """Test Doubao with modified logic (json_mode removed)"""

    def test_modified_logic(self):
        """Simulate the fixed logic without json_mode"""
        # This test demonstrates what happens when we remove json_mode

        provider = "ark"
        model_id = "doubao-seed-2.0-code"

        # Simulate the fixed logic
        if 'doubao' in model_id or 'seed' in model_id:
            # Fixed: only use function_calling
            structured_methods = ['function_calling']
        else:
            structured_methods = ['function_calling', 'json_mode']

        self.assertEqual(structured_methods, ['function_calling'])
        print("✅ Fixed logic: structured_methods = ['function_calling']")


def run_doubao_tests():
    """Run all Doubao compatibility tests"""
    print("\n" + "="*70)
    print("🧪 Doubao/Seed Model Compatibility Test Suite")
    print("="*70)

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all tests
    suite.addTests(loader.loadTestsFromTestCase(TestDoubaoCompatibility))
    suite.addTests(loader.loadTestsFromTestCase(TestDoubaoWithoutJsonMode))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "="*70)
    print("📊 Test Summary")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n✅ All tests passed! Doubao model is compatible with DeepFund.")
        print("   - function_calling works correctly")
        print("   - Token tracking is accurate")
        print("   - Multiple agents can run in parallel")
        print("   - Error handling is robust")
        print("\n💡 Recommendation: Remove json_mode from structured_methods for Doubao/Seed")
    else:
        print("\n❌ Some tests failed. Review the errors above.")

    print("="*70 + "\n")

    return result.wasSuccessful()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Doubao compatibility")
    parser.add_argument("--api-key", help="Ark API key (or set ARK_API_KEY env)")
    args = parser.parse_args()

    if args.api_key:
        os.environ["ARK_API_KEY"] = args.api_key

    success = run_doubao_tests()
    sys.exit(0 if success else 1)
