"""
Usage Statistics Tracker

Tracks token usage and API call counts across the system.
"""

import threading
from typing import Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger


@dataclass
class APICallStats:
    """API 调用统计"""
    count: int = 0
    success: int = 0
    failed: int = 0
    total_time_ms: float = 0.0


@dataclass
class TokenStats:
    """Token 使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


class UsageStats:
    """
    全局使用统计追踪器

    线程安全的单例模式，用于追踪整个工作流的资源使用情况。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.start_time: datetime = datetime.now()

        # Token 统计（按提供商分类）
        self._token_stats: Dict[str, TokenStats] = {}
        self._token_lock = threading.Lock()

        # API 调用统计（按类别分类）
        self._api_stats: Dict[str, APICallStats] = {}
        self._api_lock = threading.Lock()

        # 默认初始化常见类别
        self._init_categories()

    def _init_categories(self):
        """初始化统计类别"""
        # LLM 提供商
        llm_providers = ['deepseek', 'dashscope', 'openai', 'ollama', 'openrouter']
        for provider in llm_providers:
            self._token_stats[provider] = TokenStats()

        # API 类别
        api_categories = [
            # 搜索 API
            'search_tavily',
            'search_jina',
            'search_ddg',
            'search_baidu',
            # 股票数据 API
            'tushare',
            'tushare_cache_hit',  # 新增：Tushare 缓存命中统计
            'alpha_vantage',
            'yfinance',
            # 新闻 API
            'news_fetch',
            # 内容提取
            'jina_reader',
        ]
        for category in api_categories:
            self._api_stats[category] = APICallStats()

    def reset(self):
        """重置所有统计"""
        self.start_time = datetime.now()
        with self._token_lock:
            for key in self._token_stats:
                self._token_stats[key] = TokenStats()
        with self._api_lock:
            for key in self._api_stats:
                self._api_stats[key] = APICallStats()

    # ==================== Token 统计 ====================

    def record_tokens(self, provider: str, input_tokens: int, output_tokens: int,
                      cached_tokens: int = 0):
        """
        记录 Token 使用

        Args:
            provider: LLM 提供商 (deepseek, dashscope, etc.)
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            cached_tokens: 缓存 token 数
        """
        with self._token_lock:
            if provider not in self._token_stats:
                self._token_stats[provider] = TokenStats()

            stats = self._token_stats[provider]
            stats.input_tokens += input_tokens
            stats.output_tokens += output_tokens
            stats.total_tokens += input_tokens + output_tokens
            stats.cached_tokens += cached_tokens

    # ==================== API 调用统计 ====================

    def record_api_call(self, category: str, success: bool = True, time_ms: float = 0.0):
        """
        记录 API 调用

        Args:
            category: API 类别 (search_tavily, tushare, etc.)
            success: 是否成功
            time_ms: 调用耗时（毫秒）
        """
        with self._api_lock:
            if category not in self._api_stats:
                self._api_stats[category] = APICallStats()

            stats = self._api_stats[category]
            stats.count += 1
            if success:
                stats.success += 1
            else:
                stats.failed += 1
            stats.total_time_ms += time_ms

    # ==================== 报告生成 ====================

    def get_summary(self) -> Dict[str, Any]:
        """获取统计摘要"""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        # Token 统计汇总
        total_input = 0
        total_output = 0
        total_cached = 0
        token_by_provider = {}

        with self._token_lock:
            for provider, stats in self._token_stats.items():
                if stats.total_tokens > 0:
                    token_by_provider[provider] = {
                        'input': stats.input_tokens,
                        'output': stats.output_tokens,
                        'total': stats.total_tokens,
                        'cached': stats.cached_tokens
                    }
                    total_input += stats.input_tokens
                    total_output += stats.output_tokens
                    total_cached += stats.cached_tokens

        # API 调用统计汇总
        api_calls = {}
        total_calls = 0
        total_success = 0
        total_failed = 0

        with self._api_lock:
            for category, stats in self._api_stats.items():
                if stats.count > 0:
                    api_calls[category] = {
                        'count': stats.count,
                        'success': stats.success,
                        'failed': stats.failed,
                        'avg_time_ms': stats.total_time_ms / stats.count if stats.count > 0 else 0
                    }
                    total_calls += stats.count
                    total_success += stats.success
                    total_failed += stats.failed

        return {
            'duration_seconds': duration,
            'tokens': {
                'total_input': total_input,
                'total_output': total_output,
                'total': total_input + total_output,
                'cached': total_cached,
                'by_provider': token_by_provider
            },
            'api_calls': {
                'total': total_calls,
                'success': total_success,
                'failed': total_failed,
                'by_category': api_calls
            }
        }

    def print_report(self):
        """打印统计报告"""
        summary = self.get_summary()

        print("\n")
        print("=" * 60)
        print("📊 Usage Statistics Report")
        print("=" * 60)

        # 时间统计
        duration = summary['duration_seconds']
        print(f"\n⏱️  Duration: {duration:.1f}s ({duration/60:.1f} min)")

        # Token 统计
        tokens = summary['tokens']
        print(f"\n📝 Token Usage:")
        print(f"   Input:    {tokens['total_input']:,}")
        print(f"   Output:   {tokens['total_output']:,}")
        print(f"   Total:    {tokens['total']:,}")
        if tokens['cached'] > 0:
            print(f"   Cached:   {tokens['cached']:,}")

        if tokens['by_provider']:
            print(f"\n   By Provider:")
            for provider, stats in tokens['by_provider'].items():
                print(f"     {provider}: {stats['total']:,} tokens")

        # API 调用统计
        api = summary['api_calls']
        print(f"\n🔌 API Calls:")
        print(f"   Total:    {api['total']}")
        print(f"   Success:  {api['success']}")
        print(f"   Failed:   {api['failed']}")

        if api['by_category']:
            print(f"\n   By Category:")
            for category, stats in api['by_category'].items():
                status = "✅" if stats['failed'] == 0 else f"⚠️ {stats['failed']} failed"
                print(f"     {category}: {stats['count']} calls {status}")

        # 费用估算
        print(f"\n💰 Cost Estimation:")
        # DeepSeek 价格: ¥1/百万 input, ¥2/百万 output
        # DashScope 价格: 约相同
        input_cost = tokens['total_input'] / 1_000_000 * 1  # ¥1/百万
        output_cost = tokens['total_output'] / 1_000_000 * 2  # ¥2/百万
        total_cost = input_cost + output_cost
        print(f"   Estimated: ¥{total_cost:.4f} (¥{input_cost:.4f} input + ¥{output_cost:.4f} output)")

        print("\n" + "=" * 60 + "\n")

        # 同时记录到日志
        logger.info(f"Usage Stats: {tokens['total']:,} tokens, {api['total']} API calls, ¥{total_cost:.4f} estimated cost")


# 全局单例
stats = UsageStats()


def get_stats() -> UsageStats:
    """获取全局统计实例"""
    return stats
