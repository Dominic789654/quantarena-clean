import os
import time
from typing import Dict, List, Union, Optional
import json
from loguru import logger
from agno.agent import Agent
from deepear.src.utils.llm.factory import get_model
from deepear.src.utils.database_manager import DatabaseManager
from deepear.src.utils.stats import get_stats

# 从环境变量读取默认情绪分析模式
DEFAULT_SENTIMENT_MODE = os.getenv("SENTIMENT_MODE", "auto")  # auto, bert, llm

class SentimentTools:
    """
    情绪分析工具 - 支持 LLM 和 BERT 两种模式
    
    模式说明:
    - "auto": 自动选择，优先使用 BERT（速度快），不可用时回退到 LLM
    - "bert": 强制使用 BERT 模型（需要 transformers 库）
    - "llm": 强制使用 LLM（更准确但较慢）
    
    可通过环境变量 SENTIMENT_MODE 设置默认模式。
    """
    
    def __init__(self, db: DatabaseManager, mode: Optional[str] = None,
                 model_provider: Optional[str] = None, model_id: Optional[str] = None):
        """
        初始化情绪分析工具。

        Args:
            db: 数据库管理器实例
            mode: 分析模式，可选 "auto", "bert", "llm"。None 则使用环境变量默认值。
            model_provider: LLM 提供商，None 则从环境变量读取 REASONING_MODEL_PROVIDER
            model_id: 模型标识符，None 则从环境变量读取 REASONING_MODEL_ID
        """
        self.db = db
        self.mode = mode or DEFAULT_SENTIMENT_MODE
        self.llm_model = None
        self.bert_pipeline = None

        # Initialize LLM - use unified model config from environment
        try:
            provider = model_provider or os.getenv("REASONING_MODEL_PROVIDER", "deepseek")
            m_id = model_id or os.getenv("REASONING_MODEL_ID", "deepseek-v4-flash")
            self.llm_model = get_model(provider, m_id)
            logger.info(f"✅ Sentiment LLM initialized: {provider}/{m_id}")
        except Exception as e:
            logger.warning(f"LLM initialization skipped: {e}")

        # Initialize BERT if needed
        if self.mode in ["bert", "auto"]:
            try:
                from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
                from transformers.utils import logging as transformers_logging
                transformers_logging.set_verbosity_error() # 减少冗余日志
                
                bert_model = os.getenv("BERT_SENTIMENT_MODEL", "uer/roberta-base-finetuned-chinanews-chinese")
                
                # 优先使用本地缓存
                try:
                    tokenizer = AutoTokenizer.from_pretrained(bert_model, local_files_only=True)
                    model = AutoModelForSequenceClassification.from_pretrained(bert_model, local_files_only=True)
                    
                    self.bert_pipeline = pipeline(
                        "sentiment-analysis", 
                        model=model,
                        tokenizer=tokenizer,
                        device=-1
                    )
                    logger.info(f"✅ BERT pipeline loaded from local cache: {bert_model}")
                except (OSError, ValueError, ImportError):
                    # 本地没有，则从网络下载
                    logger.info(f"📡 Downloading BERT model: {bert_model}...")
                    tokenizer = AutoTokenizer.from_pretrained(bert_model)
                    model = AutoModelForSequenceClassification.from_pretrained(bert_model)
                    
                    self.bert_pipeline = pipeline(
                        "sentiment-analysis", 
                        model=model,
                        tokenizer=tokenizer,
                        device=-1
                    )
                    logger.info(f"✅ BERT Sentiment pipeline ({bert_model}) initialized.")
            except ImportError:
                logger.warning("Transformers library not installed. BERT sentiment analysis disabled.")
            except Exception as e:
                if self.mode == "bert":
                    logger.error(f"BERT mode requested but failed: {e}")
                else:
                    logger.warning(f"BERT unavailable, using LLM only. Error: {e}")
                self.bert_pipeline = None


    def analyze_sentiment(self, text: str) -> Dict[str, Union[float, str]]:
        """
        分析文本的情绪极性。根据初始化时的 mode 自动选择分析方法。
        
        Args:
            text: 需要分析的文本内容，如新闻标题或摘要。
        
        Returns:
            包含以下字段的字典:
            - score: 情绪分值，范围 -1.0（极度负面）到 1.0（极度正面），0.0 为中性
            - label: 情绪标签，"positive"/"negative"/"neutral"
            - reason: 分析理由（仅 LLM 模式提供详细理由）
        """
        if self.mode == "bert" and self.bert_pipeline:
            results = self.analyze_sentiment_bert([text])
            return results[0] if results else {"score": 0.0, "label": "error"}
        elif self.mode == "llm" or (self.mode == "auto" and not self.bert_pipeline):
            return self.analyze_sentiment_llm(text)
        else:
            # auto mode with BERT available
            results = self.analyze_sentiment_bert([text])
            return results[0] if results else {"score": 0.0, "label": "error"}

    def analyze_sentiment_llm(self, text: str) -> Dict[str, Union[float, str]]:
        """
        使用 LLM 进行深度情绪分析，可获得详细的分析理由。

        Args:
            text: 需要分析的文本，最多处理前 1000 字符。

        Returns:
            包含 score, label, reason 的字典。
        """
        if not self.llm_model:
            return {"score": 0.0, "label": "neutral", "error": "LLM not initialized"}

        analyzer = Agent(model=self.llm_model, markdown=False)
        prompt = f"""请分析以下金融/新闻文本的情绪极性。
        返回严格的 JSON 格式:
        {{"score": <float: -1.0到1.0>, "label": "<positive/negative/neutral>", "reason": "<简短理由>"}}

        文本: {text[:1000]}"""

        start_time = time.time()
        try:
            response = analyzer.run(prompt)
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            # Track usage stats
            elapsed_ms = (time.time() - start_time) * 1000
            get_stats().record_api_call("sentiment_llm", success=True, time_ms=elapsed_ms)

            # Track token usage if available
            if hasattr(response, 'messages') and response.messages:
                for msg in response.messages:
                    if hasattr(msg, 'usage') and msg.usage:
                        get_stats().record_tokens(
                            provider=os.getenv("REASONING_MODEL_PROVIDER", "unknown"),
                            input_tokens=getattr(msg.usage, 'prompt_tokens', 0) or 0,
                            output_tokens=getattr(msg.usage, 'completion_tokens', 0) or 0
                        )
                        break

            return json.loads(content)
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            get_stats().record_api_call("sentiment_llm", success=False, time_ms=elapsed_ms)
            logger.error(f"LLM sentiment failed: {e}")
            return {"score": 0.0, "label": "error", "reason": str(e)}

    def analyze_sentiment_bert(self, texts: List[str]) -> List[Dict]:
        """
        使用 BERT 进行批量高速情绪分析。
        
        Args:
            texts: 需要分析的文本列表。
        
        Returns:
            与输入列表等长的分析结果列表。
        """
        if not self.bert_pipeline:
            return [{"score": 0.0, "label": "error", "reason": "BERT not available"}] * len(texts)
        
        try:
            results = self.bert_pipeline(texts, truncation=True, max_length=512)
            processed = []
            for r in results:
                label = r['label'].lower()
                score = r['score']
                
                # 标准化不同模型的标签格式
                if 'negative' in label or 'neg' in label:
                    score = -score
                elif 'neutral' in label or 'neu' in label:
                    score = 0.0
                
                processed.append({
                    "score": float(round(score, 3)),
                    "label": "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral"),
                    "reason": "BERT automated analysis"
                })
            return processed
        except Exception as e:
            logger.error(f"BERT analysis failed: {e}")
            return [{"score": 0.0, "label": "error", "reason": str(e)}] * len(texts)

    def batch_update_news_sentiment(self, source: Optional[str] = None, limit: int = 50, use_bert: Optional[bool] = None):
        """
        批量更新数据库中新闻的情绪分数。
        
        Args:
            source: 筛选特定新闻源，如 "wallstreetcn"。None 则处理所有来源。
            limit: 最多处理的新闻数量。
            use_bert: 是否使用 BERT。None 则根据初始化模式自动决定。
        
        Returns:
            成功更新的新闻数量。
        """
        news_items = self.db.get_daily_news(source=source, limit=limit)
        to_analyze = [item for item in news_items if not item.get('sentiment_score')]
        
        if not to_analyze:
            return 0

        # 决定使用哪种方法
        should_use_bert = use_bert if use_bert is not None else (self.bert_pipeline is not None and self.mode != "llm")

        updated_count = 0
        cursor = self.db.conn.cursor()
        
        if should_use_bert and self.bert_pipeline:
            logger.info(f"🚀 Using BERT for batch analysis of {len(to_analyze)} items...")
            titles = [item['title'] for item in to_analyze]
            results = self.analyze_sentiment_bert(titles)
            
            for item, analysis in zip(to_analyze, results):
                cursor.execute("""
                    UPDATE daily_news 
                    SET sentiment_score = ?, meta_data = json_set(COALESCE(meta_data, '{}'), '$.sentiment_reason', ?)
                    WHERE id = ?
                """, (analysis['score'], analysis['reason'], item['id']))
                updated_count += 1
        else:
            logger.info(f"🚶 Using LLM for analysis of {len(to_analyze)} items...")
            for item in to_analyze:
                analysis = self.analyze_sentiment_llm(item['title'])
                cursor.execute("""
                    UPDATE daily_news 
                    SET sentiment_score = ?, meta_data = json_set(COALESCE(meta_data, '{}'), '$.sentiment_reason', ?)
                    WHERE id = ?
                """, (analysis.get('score', 0.0), analysis.get('reason', ''), item['id']))
                updated_count += 1
        
        self.db.conn.commit()
        return updated_count
