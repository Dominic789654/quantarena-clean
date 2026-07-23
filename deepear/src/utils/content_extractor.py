import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
import os
import time
import json
import threading
from typing import Optional
from loguru import logger


class ContentExtractor:
    """内容提取工具 - 主要接入 Jina Reader API"""
    
    JINA_BASE_URL = "https://r.jina.ai/"
    
    # 速率限制配置 (无 API Key 时：20 次/分钟)
    _rate_limit_no_key = 20  # 每分钟最大请求数
    _rate_window = 60.0  # 时间窗口（秒）
    _min_interval = 3.0  # 请求最小间隔（秒）
    
    # 类级别的速率限制状态
    _request_times = []
    _last_request_time = 0.0
    _lock = threading.Lock()

    @classmethod
    def _wait_for_rate_limit(cls, has_api_key: bool) -> None:
        """等待以满足速率限制要求"""
        if has_api_key:
            # 有 API Key 时，只需保持最小间隔
            time.sleep(0.5)
            return
        
        with cls._lock:
            current_time = time.time()
            
            # 1. 清理过期的请求记录
            cls._request_times = [t for t in cls._request_times if current_time - t < cls._rate_window]
            
            # 2. 检查是否达到速率限制
            if len(cls._request_times) >= cls._rate_limit_no_key:
                # 需要等待最旧的请求过期
                oldest = cls._request_times[0]
                wait_time = cls._rate_window - (current_time - oldest) + 1.0
                if wait_time > 0:
                    logger.warning(f"⏳ Jina rate limit reached, waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    current_time = time.time()
                    cls._request_times = [t for t in cls._request_times if current_time - t < cls._rate_window]
            
            # 3. 确保请求间隔不太快
            time_since_last = current_time - cls._last_request_time
            if time_since_last < cls._min_interval:
                sleep_time = cls._min_interval - time_since_last
                time.sleep(sleep_time)
            
            # 4. 记录本次请求
            cls._request_times.append(time.time())
            cls._last_request_time = time.time()

    @classmethod
    def extract_with_jina(cls, url: str, timeout: int = 30) -> Optional[str]:
        """
        使用 Jina Reader 提取网页正文内容 (Markdown 格式)
        
        无 API Key 时自动限速：每分钟最多 20 次请求，每次间隔至少 3 秒
        """
        if not url or not url.startswith("http"):
            return None
            
        logger.info(f"🕸️ Extracting content from: {url} via Jina...")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        
        # 使用统一的 JINA_API_KEY
        api_key = os.getenv("JINA_API_KEY")
        has_api_key = bool(api_key and api_key.strip())
        
        if has_api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # 等待速率限制
        cls._wait_for_rate_limit(has_api_key)

        try:
            # Jina Reader API
            full_url = f"{cls.JINA_BASE_URL}{url}"
            response = requests.get(full_url, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    # Jina JSON 响应格式通常在 data.content
                    if isinstance(data, dict) and "data" in data:
                        return data["data"].get("content", "")
                    return data.get("content", response.text)
                except (json.JSONDecodeError, TypeError):
                    return response.text
            elif response.status_code == 429:
                # 触发速率限制，等待后重试一次
                logger.warning("⚠️ Jina rate limit (429), waiting 60s before retry...")
                time.sleep(60)
                return cls.extract_with_jina(url, timeout)
            else:
                logger.warning(f"Jina extraction failed (Status {response.status_code}) for {url}")
                return None
                
        except Timeout:
            logger.error(f"Timeout during Jina extraction for {url}")
            return None
        except ConnectionError:
            logger.error(f"Connection error during Jina extraction for {url}")
            return None
        except RequestException as e:
            logger.error(f"Request error during Jina extraction: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Jina extraction: {e}")
            return None
