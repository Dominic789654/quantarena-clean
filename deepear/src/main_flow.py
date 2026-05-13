import os
import json
import re
from typing import List, Dict, Optional, Union, Any
from loguru import logger
from dotenv import load_dotenv
from shared.utils.time_utils import now_utc
from shared.utils.run_id import generate_run_id

from deepear.src.utils.database_manager import DatabaseManager
from deepear.src.utils.llm.factory import get_model
from deepear.src.utils.llm.router import router
from deepear.src.utils.search_tools import SearchTools
from deepear.src.utils.json_utils import extract_json
from deepear.src.agents import TrendAgent, FinAgent, ReportAgent, IntentAgent
from deepear.src.utils.stock_tools import StockTools
from agno.agent import Agent
from deepear.src.prompts.trend_agent import get_news_filter_instructions
from deepear.src.utils.checkpointing import CheckpointManager, resolve_latest_run_id
from deepear.src.utils.logging_setup import setup_file_logging, make_run_id
from deepear.src.utils.md_to_html import save_report_as_html
from deepear.src.utils.stats import get_stats

class SignalFluxWorkflow:
    """
    DeepEar 主工作流
    
    流程:
    1. TrendAgent -> 扫描热点
    2. FinAgent -> 深度分析
    3. ReportAgent -> 生成研报
    
    支持 update_run: 基于旧版 Run 的信号，刷新行情并生成新版报告（对比分析）
    """
    
    def __init__(self, db_path: str = "data/signal_flux.db", isq_template_id: str = "default_isq_v1"):
        load_dotenv()
        self.isq_template_id = isq_template_id
        # 初始化数据库
        self.db = DatabaseManager(db_path)
        
        # 使用 ModelRouter 获取不同用途的模型
        self.reasoning_model = router.get_reasoning_model()
        self.tool_model = router.get_tool_model()
        
        # 初始化 Agents
        # TrendAgent 使用双模型：筛选使用 reasoning_model，采集使用 tool_model
        self.trend_agent = TrendAgent(self.db, self.reasoning_model, tool_model=self.tool_model, sentiment_mode="bert")
        # FinAgent 使用双模型：分析使用 reasoning_model，检索使用 tool_model，ISQ 模板可配置
        self.fin_agent = FinAgent(self.db, self.reasoning_model, tool_model=self.tool_model, isq_template_id=self.isq_template_id)
        # ReportAgent 支持双模型：写作使用 reasoning_model，检索使用 tool_model
        self.report_agent = ReportAgent(self.db, self.reasoning_model, tool_model=self.tool_model)
        # 意图分析主要是文本理解，使用推理模型
        self.intent_agent = IntentAgent(self.reasoning_model)
        self.search_tools = SearchTools(self.db)
        
        # 用于筛选的轻量 Agent（不带工具），使用推理模型
        self.filter_agent = Agent(model=self.reasoning_model, markdown=False, debug_mode=True)
        
        logger.info(f"🚀 DeepEar Workflow initialized with Dual-Model Routing (ISQ Template: {self.isq_template_id})")
    
    def _llm_filter_signals(self, news_list: List[Dict], depth: Union[int, str], query: Optional[str] = None) -> List[Dict]:
        """使用 LLM 智能筛选高价值信号
        
        使用 FilterResult schema 快速判断是否有有效信号，避免处理无效内容
        """
        if isinstance(depth, int) and len(news_list) <= depth and not query:
            return news_list
        
        # 构建新闻列表文本
        news_text = "\n".join([
            f"[ID: {n.get('id', i)}] {n['title']} (情绪: {n.get('sentiment_score', 'N/A')})"
            for i, n in enumerate(news_list)
        ])
        
        # 生成筛选 prompt (带 query)
        filter_instruction = get_news_filter_instructions(len(news_list), depth, query)
        self.filter_agent.instructions = [filter_instruction]
        
        try:
            response = self.filter_agent.run(f"请筛选以下新闻:\n{news_text}")
            content = response.content
            
            # 提取 JSON
            result = extract_json(content)
            
            # 检查是否有有效信号（减少 token 消耗）
            if result and not result.get("has_valid_signals", True):
                logger.warning(f"⚠️ No valid signals found: {result.get('reason', 'Unknown')}")
                return []
            if not result:
                logger.warning(f"Failed to parse LLM filter response: {content}")
                return news_list
            
            selected_ids = result.get("selected_ids", [])
            themes = result.get("themes", [])
            
            logger.info(f"🎯 LLM 筛选结果: {len(selected_ids)} 条, {len(themes)} 个主题")
            
            # 根据 ID 筛选新闻
            id_set = set(str(sid) for sid in selected_ids)
            filtered = [n for n in news_list if str(n.get('id', '')) in id_set]
            
            # 动态逻辑：
            # 1. 只有在 LLM 未选出任何内容且非特定查询时，才回退到默认前几条
            if not filtered and not query:
                 logger.warning("⚠️ LLM selected 0 items, falling back to top items")
                 return news_list
            
            # 2. 如果有 query，完全信任 LLM 的选择（数量可能少于或多于 depth）
            if query:
                return filtered
            
            # 3. 如果是通用扫描，限制最大返回数量
            return filtered
            
        except Exception as e:
            logger.warning(f"⚠️ LLM 筛选失败: {e}, 回退到全部返回")
            return news_list

    # 可用的新闻源（按类别）
    FINANCIAL_SOURCES = ["cls", "wallstreetcn", "xueqiu"]
    SOCIAL_SOURCES = ["weibo", "zhihu", "baidu", "toutiao", "douyin"]
    TECH_SOURCES = ["36kr", "ithome", "v2ex", "juejin", "hackernews"]
    ALL_SOURCES = FINANCIAL_SOURCES + SOCIAL_SOURCES + TECH_SOURCES
    
    def run(
        self,
        sources: List[str] = None,
        wide: int = 10,
        depth: Union[int, str] = 'auto',
        query: Optional[str] = None,
        run_id: Optional[str] = None,
        resume: bool = False,
        resume_from: str = "report",
        checkpoint_dir: str = "reports/checkpoints",
        user_id: Optional[str] = None,
        concurrency: int = 1,
    ) -> Optional[str]:
        """执行完整工作流
        
        Args:
            sources: 新闻来源列表，默认为 ["all"]
            wide:  新闻抓取广度（每个源抓取的数量）
            depth: 生成报告的深度，若为 'auto'，则由 LLM 总结判断，若为整数则限制最后生成的信号数量
            query:  用户查询意图（可选），如 "香港火灾"、"A股科技板块"
            concurrency: 信号分析并发数，默认为 1（串行）
            
        Returns:
            生成的报告文件路径，或 None（如果失败）
        """
        # Resolve run_id and checkpoint manager
        if resume and not run_id:
            run_id = resolve_latest_run_id(checkpoint_dir)
            if not run_id:
                logger.warning("⚠️ resume requested but no checkpoint runs found; starting fresh")
        run_id = run_id or generate_run_id()
        ckpt = CheckpointManager(base_dir=checkpoint_dir, run_id=run_id)
        os.makedirs(ckpt.run_dir, exist_ok=True)

        ckpt.save_json(
            "state.json",
            {
                "run_id": run_id,
                "resume": bool(resume),
                "resume_from": resume_from,
                "started_at": now_utc().isoformat(),
                "params": {"sources": sources, "wide": wide, "depth": depth, "query": query},
                "status": "running",
                "user_id": user_id,
            },
        )

        # Fast resume: regenerate report from analyzed_signals without rerunning Trend/Analysis.
        # Useful when you only want to validate report formatting after code changes.
        if resume and resume_from == "analysis" and ckpt.exists("analyzed_signals.json"):
            logger.info(f"♻️ Resuming from analysis checkpoint for run_id={run_id}: regenerating report...")
            analyzed_signals = ckpt.load_json("analyzed_signals.json", default=[])
            if not isinstance(analyzed_signals, list) or not analyzed_signals:
                logger.warning("⚠️ analyzed_signals.json missing/empty; falling back to full run")
            else:
                result = self.report_agent.generate_report(analyzed_signals, user_query=query)
                md_content = result.content if hasattr(result, "content") else str(result)
                ckpt.save_text("report.md", md_content)

                report_dir = "reports"
                os.makedirs(report_dir, exist_ok=True)
                timestamp = now_utc().strftime('%Y%m%d_%H%M')
                md_filename = f"{report_dir}/daily_report_{timestamp}.md"
                with open(md_filename, "w", encoding="utf-8") as f:
                    f.write(md_content)
                html_filename = save_report_as_html(md_filename)
                ckpt.save_json(
                    "state.json",
                    {
                        "run_id": run_id,
                        "status": "completed",
                        "resumed_from": "analyzed_signals.json",
                        "finished_at": now_utc().isoformat(),
                        "output": html_filename or md_filename,
                    },
                )
                return html_filename or md_filename

        if sources is None:
            sources = ["all"]

        # Fast resume paths
        # resume_from:
        # - "report": reuse report.md (fastest)
        # - "analysis": reuse analyzed_signals.json but regenerate report fresh
        if resume and resume_from == "report" and ckpt.exists("report.md"):
            logger.info(f"♻️ Resuming: found final report checkpoint for run_id={run_id}")
            report_md = ckpt.load_text("report.md")
            if report_md:
                report_dir = "reports"
                os.makedirs(report_dir, exist_ok=True)
                timestamp = now_utc().strftime('%Y%m%d_%H%M')
                md_filename = f"{report_dir}/daily_report_{timestamp}.md"
                with open(md_filename, "w", encoding="utf-8") as f:
                    f.write(report_md)
                html_filename = save_report_as_html(md_filename)
                ckpt.save_json(
                    "state.json",
                    {
                        "run_id": run_id,
                        "status": "completed",
                        "resumed_from": "report.md",
                        "finished_at": now_utc().isoformat(),
                    },
                )
                return html_filename or md_filename
            
        logger.info("--- Step 1: Trend Discovery ---")
        
        # 0. 意图分析 (如果存在 query)
        intent_info = ""
        if query:
            logger.info(f"🧠 Analyzing intent for: {query}")
            intent_info = self.intent_agent.run(query)
            ckpt.save_json("intent.json", intent_info)
        
        # 1. 解析 sources 参数
        if "all" in sources:
            actual_sources = self.ALL_SOURCES.copy()
        elif "financial" in sources:
            actual_sources = self.FINANCIAL_SOURCES.copy()
        elif "social" in sources:
            actual_sources = self.SOCIAL_SOURCES.copy()
        elif "tech" in sources:
            actual_sources = self.TECH_SOURCES.copy()
        else:
            actual_sources = sources
        
        logger.info(f"📡 Attempting to fetch from {len(actual_sources)} sources...")
        
        # 2. 获取热点
        successful_sources = []
        for source in actual_sources:
            try:
                # 使用 wide 控制抓取数量
                result = self.trend_agent.news_toolkit.fetch_hot_news(source, count=wide)
                if result and len(result) > 0:
                    successful_sources.append(source)
                else:
                    logger.warning(f"⚠️ Source '{source}' returned no data, skipping")
            except Exception as e:
                logger.warning(f"⚠️ Source '{source}' failed: {e}, skipping")
        
        logger.info(f"✅ Successfully fetched from {len(successful_sources)}/{len(actual_sources)} sources")
        ckpt.save_json(
            "trend_sources.json",
            {
                "actual_sources": actual_sources,
                "successful_sources": successful_sources,
                "wide": wide,
            },
        )
            
        # --- NEW: Active Search based on Intent ---
        search_signals = []
        if query and isinstance(intent_info, dict):
            search_queries = intent_info.get("search_queries", [query])
            is_specific = intent_info.get("is_specific_event", False)
            
            # 如果是特定事件，或者用户明确提问，我们应该主动搜索
            if is_specific or len(search_queries) > 0:
                logger.info(f"🔍 Executing active search for queries: {search_queries}")
                for q in search_queries[:2]: # 限制查询数，避免太慢
                    # Consider using 'baidu' for Chinese queries if 'ddg' is unstable
                    # enrich=True is default, so we get full content
                    results = self.search_tools.search_list(q, max_results=5, enrich=True)  # 使用默认引擎 (jina if configured)
                    for r in results:
                        # 转换为标准信号格式 (search_tools now returns standard keys including id, rank, etc)
                        search_signals.append({
                            "title": r.get('title'),
                            "url": r.get('url'),
                            "source": r.get('source', 'Search'), # keeping original source name
                            "content": r.get('content'),
                            "publish_time": r.get('publish_time') or now_utc(), 
                            "sentiment_score": r.get('sentiment_score', 0), 
                            "id": r.get('id') or f"search_{hash(r.get('url'))}"
                        })
                logger.info(f"🔍 Found {len(search_signals)} signals via search")
                ckpt.save_json("search_signals.json", {"query": query, "items": search_signals})

        # 2. 批量更新情绪分数 (保留，用于可视化)
        logger.info("Calculating sentiment scores...")
        self.trend_agent.sentiment_toolkit.batch_update_sentiment(limit=50)
        
        # 3. 从数据库读取新闻 + 合并搜索结果
        db_news = self.db.get_daily_news(limit=50)
        
        # 合并列表 (Search signals preferred if query exists)
        raw_news = search_signals + db_news if search_signals else db_news
        
        if not raw_news:
            logger.warning("No news found in database.")
            return

        ckpt.save_json(
            "raw_news_meta.json",
            {
                "db_news_count": len(db_news) if db_news else 0,
                "search_signals_count": len(search_signals),
                "raw_news_count": len(raw_news),
            },
        )
        
        # 4. 智能筛选（LLM 或传统方式）
        # 如果有 query，即使数量少也建议走 LLM 筛选以匹配相关性
        if depth == 'auto' or query:
            logger.info(f"🤖 Using LLM to filter signals (Query: {query if query else 'Default'})...")
            high_value_signals = self._llm_filter_signals(raw_news, depth, query)
        else:
            # 传统方式：按情绪分数排序
            if isinstance(depth, int) and depth > 0:
                high_value_signals = sorted(
                    raw_news, 
                    key=lambda x: abs(x.get("sentiment_score") or 0), 
                    reverse=True
                )[:depth]
            else:
                high_value_signals = raw_news

        # Store a light checkpoint to resume analysis without rerunning filter
        try:
            hv_meta = []
            for n in high_value_signals:
                hv_meta.append({
                    "id": n.get("id"),
                    "title": n.get("title"),
                    "url": n.get("url"),
                    "source": n.get("source"),
                    "sentiment_score": n.get("sentiment_score"),
                })
            ckpt.save_json("high_value_signals.json", {"count": len(high_value_signals), "items": hv_meta})
        except Exception:
            pass
            
        logger.info(f"--- Step 2: Financial Analysis ({len(high_value_signals)} signals) ---")

        
        analyzed_signals = []

        # Resume from analyzed_signals checkpoint if available
        if resume and ckpt.exists("analyzed_signals.json"):
            logger.info(f"♻️ Resuming: loading analyzed signals from checkpoint run_id={run_id}")
            analyzed_cached = ckpt.load_json("analyzed_signals.json", default=[])
            if isinstance(analyzed_cached, list) and analyzed_cached:
                analyzed_signals = analyzed_cached
        
        if analyzed_signals:
            logger.info(f"✅ Using {len(analyzed_signals)} analyzed signals from checkpoint")
        else:


            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def analyze_single_signal(signal_data):
                """Wrapper for single signal analysis to use in thread pool"""
                try:
                    logger.info(f"Analyzing: {signal_data['title']}")
                    # 2. 构造上下文
                    content = signal_data.get("content") or ""
                    if len(content) < 50 and signal_data.get("url"):
                        content = self.trend_agent.news_toolkit.fetch_news_content(signal_data["url"]) or ""
                    input_text = f"【{signal_data['title']}】\n{content[:3000]}"
                    
                    # 调用 FinAgent 执行 ISQ 解析
                    sig_obj = self.fin_agent.analyze_signal(input_text, news_id=signal_data.get("id"))

                    if sig_obj:
                        # 补充来源信息 (如果模型没填全)
                        if not sig_obj.sources and signal_data.get("url"):
                            sig_obj.sources = [{"title": signal_data["title"], "url": signal_data["url"], "source_name": signal_data.get("source", "Unknown")}]
                            
                        sig_dict = sig_obj.dict()
                        if user_id:
                            sig_dict['user_id'] = user_id
                            if sig_dict.get('signal_id'):
                                sig_dict['signal_id'] = f"{sig_dict['signal_id']}_{user_id}"
                        
                        # Note: Database writes are generally thread-safe in sqlite3 if sharing connection is handled, 
                        # but here DatabaseManager creates new connection per instance usually. 
                        # Ideally we should use a lock or separate db instance if `self.db` is shared.
                        # Assuming DatabaseManager handles its own connection or valid concurrency.
                        # If not, might need a lock. `self.db` uses `sqlite3.connect` which is valid for threads if check_same_thread=False
                        # But better to be safe and acquire lock for DB writes if needed.
                        # For now, we will do DB write in the main thread or use lock if errors appear.
                        # Actually, better to return the result and write in main thread to avoid DB collision issues completely.
                        
                        return sig_dict, signal_data.get("id"), sig_obj.summary
                    else:
                        logger.warning(f"Could not get structured analysis for {signal_data['title']}, skipping")
                        return None, None, None
                except Exception as e:
                    logger.error(f"Analysis failed for {signal_data['title']}: {e}")
                    raise e # Re-raise to trigger fallback if needed

            if concurrency > 1:
                logger.info(f"🚀 Using ThreadPoolExecutor with max_workers={concurrency} for analysis")
                try:
                    with ThreadPoolExecutor(max_workers=concurrency) as executor:
                        future_to_signal = {executor.submit(analyze_single_signal, sig): sig for sig in high_value_signals}
                        
                        processed_count = 0
                        for future in as_completed(future_to_signal):
                            sig_original = future_to_signal[future]
                            try:
                                result_dict, sig_id_res, summary_res = future.result()
                                if result_dict:
                                    # Write to DB (Main Thread Safe)
                                    self.db.save_signal(result_dict)
                                    analyzed_signals.append(result_dict)
                                    if sig_id_res:
                                        self.db.update_news_content(sig_id_res, analysis=summary_res)
                                
                                processed_count += 1
                                if processed_count % 3 == 0:
                                    ckpt.save_json("analyzed_signals.json", analyzed_signals)
                            except Exception as e:
                                logger.error(f"Thread execution failed for {sig_original['title']}: {e}")
                                # Determine if we should fallback? 
                                # If many fail, maybe. For now just log. 
                                # Ideally, if we see a specific "RateLimit" error, we abort and switch.
                                
                    # If all good
                    ckpt.save_json("analyzed_signals.json", analyzed_signals)
                    
                except Exception as e:
                    logger.error(f"⚠️ Critical error in concurrency mode: {e}. Falling back to sequential (1 worker).")
                    # Fallback Logic: Filter out already analyzed signals and process the rest sequentially
                    analyzed_ids = set(s.get("signal_id") for s in analyzed_signals) # Note: signal_id might be generated, relying on uniqueness might be tricky.
                    # Better: usage `high_value_signals` index or ID.
                    
                    logger.info("🔄 Fallback: Switching to sequential processing...")
                    # Sequential loop for remaining items (simple approach: just run the original sequential loop for ALL, checking duplicates or just use what's left)
                    # For simplicity in this iteration, we just continue sequential loop for items NOT in analyzed_signals (by ID logic if possible, or just retry all if safe/idipotent).
                    # Since analyze is idempotent-ish (updates DB), we can retry relevant ones.
                    
                    # Let's just run sequential logic for ANY that are not in analyzed list (by title match?)
                    analyzed_titles = set(s.get("title") for s in analyzed_signals)
                    remaining = [s for s in high_value_signals if s.get("title") not in analyzed_titles]
                    
                    for signal in remaining:
                        try:
                            # Reuse the extraction logic or calling the function directly
                            # ... (Original sequential logic) ...
                             logger.info(f"Fallback Analyzing: {signal['title']}")
                             res_dict, s_id, summ = analyze_single_signal(signal)
                             if res_dict:
                                 self.db.save_signal(res_dict)
                                 analyzed_signals.append(res_dict)
                                 if s_id:
                                    self.db.update_news_content(s_id, analysis=summ)
                        except Exception as seq_e:
                             logger.error(f"Sequential fallback failed for {signal['title']}: {seq_e}")
                    
                    ckpt.save_json("analyzed_signals.json", analyzed_signals)

            else:
                # Sequential Mode (Legacy)
                for signal in high_value_signals:
                    logger.info(f"Analyzing: {signal['title']}")

                    # 2. 构造上下文
                    content = signal.get("content") or ""
                    if len(content) < 50 and signal.get("url"):
                        content = self.trend_agent.news_toolkit.fetch_news_content(signal["url"]) or ""
                    input_text = f"【{signal['title']}】\n{content[:3000]}"

                    try:
                        # 调用 FinAgent 执行 ISQ 解析
                        sig_obj = self.fin_agent.analyze_signal(input_text, news_id=signal.get("id"))

                        if sig_obj:
                            # 补充来源信息 (如果模型没填全)
                            if not sig_obj.sources and signal.get("url"):
                                sig_obj.sources = [{"title": signal["title"], "url": signal["url"], "source_name": signal.get("source", "Unknown")}]

                            # 保存到深度信号表
                            sig_dict = sig_obj.dict()
                            if user_id:
                                sig_dict['user_id'] = user_id
                                if sig_dict.get('signal_id'):
                                    sig_dict['signal_id'] = f"{sig_dict['signal_id']}_{user_id}"
                            self.db.save_signal(sig_dict)
                            analyzed_signals.append(sig_obj.dict())

                            # 同步回 news 表（旧逻辑兼容）
                            if signal.get("id"):
                                self.db.update_news_content(signal["id"], analysis=sig_obj.summary)

                            # Incremental checkpoint every success to enable resume
                            if len(analyzed_signals) % 3 == 0:
                                ckpt.save_json("analyzed_signals.json", analyzed_signals)
                        else:
                            logger.warning(f"Could not get structured analysis for {signal['title']}, skipping")
                    except Exception as e:
                        logger.error(f"Analysis failed for {signal['title']}: {e}")

                ckpt.save_json("analyzed_signals.json", analyzed_signals)

        
        logger.info("--- Step 3: Report Generation ---")

        # Resume from report markdown checkpoint (pre-render)
        if resume and ckpt.exists("report.md"):
            logger.info(f"♻️ Resuming: using report.md checkpoint for run_id={run_id}")
            md_content = ckpt.load_text("report.md")
        else:
            result = self.report_agent.generate_report(analyzed_signals, user_query=query)
            report = result
            md_content = report.content if hasattr(report, "content") else str(report)
            if hasattr(report, "structured"):
                ckpt.save_json("report_structured.json", report.structured)
            ckpt.save_text("report.md", md_content)
        
        # 保存报告
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)
        timestamp = now_utc().strftime('%Y%m%d_%H%M')
        md_filename = f"{report_dir}/daily_report_{timestamp}.md"
        
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        # 转换为 HTML (默认)
        html_filename = save_report_as_html(md_filename)
            
        logger.info(f"✅ Report generated: {md_filename}")
        if html_filename:
            logger.info(f"🌐 HTML Report available: {html_filename}")
            ckpt.save_json("state.json", {"run_id": run_id, "status": "completed", "finished_at": now_utc().isoformat(), "output": html_filename})
            return html_filename
        ckpt.save_json("state.json", {"run_id": run_id, "status": "completed", "finished_at": now_utc().isoformat(), "output": md_filename})
        return md_filename

        return md_filename
        
    def update_run(
        self,
        base_run_id: str,
        checkpoint_dir: str = "reports/checkpoints",
        user_query: Optional[str] = None,
        new_run_id: Optional[str] = None,
        callback: Optional[Any] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        基于已有 Run 进行更新：
        1. 读取旧 Run 的 analyzed_signals
        2. 强制刷新这些信号关联的股价数据 (StockTools force_sync)
        3. 调用 ReportAgent 生成新报告 (包含 "Update/Comparison" 上下文)
        
        Returns:
            New run_id
        """
        # 1. Load base run data
        if callback:
            callback.step("system", "System", f"🔍 加载基准运行: {base_run_id}")
        base_ckpt = CheckpointManager(base_dir=checkpoint_dir, run_id=base_run_id)
        analyzed_signals = None
        if base_ckpt.exists("analyzed_signals.json"):
            analyzed_signals = base_ckpt.load_json("analyzed_signals.json")
        else:
            # Fallback: try dashboard DB run_data_json
            try:
                from dashboard.db import DashboardDB
                db = DashboardDB()
                run_data = db.get_run_data(base_run_id) or {}
                analyzed_signals = run_data.get("signals")
                logger.warning(f"⚠️ analyzed_signals.json missing, fallback to dashboard run_data for {base_run_id}")
                if callback:
                    callback.step("warning", "System", f"⚠️ 未找到 checkpoint，改用数据库信号 ({len(analyzed_signals or [])})")
            except Exception as e:
                logger.error(f"❌ Cannot update run {base_run_id}: analyzed_signals.json not found and DB fallback failed: {e}")
                if callback:
                    callback.step("error", "System", f"❌ 无法加载基准信号: {str(e)[:80]}")
                return None
        if not analyzed_signals or not isinstance(analyzed_signals, list):
            logger.error(f"❌ Cannot update run {base_run_id}: analyzed_signals is empty or invalid")
            return None
            
        logger.info(f"🔄 Starting UPDATE for run {base_run_id} (Signals: {len(analyzed_signals)})")
        if callback:
            callback.step("system", "System", f"🔄 更新开始，信号数: {len(analyzed_signals)}")
        
        # 2. Setup New Run
        new_run_id = new_run_id or generate_run_id()
        new_ckpt = CheckpointManager(base_dir=checkpoint_dir, run_id=new_run_id)
        os.makedirs(new_ckpt.run_dir, exist_ok=True)
        
        # Preserve lineage in state
        new_ckpt.save_json("state.json", {
            "run_id": new_run_id,
            "parent_run_id": base_run_id,
            "status": "running",
            "type": "update",
            "started_at": now_utc().isoformat()
        })
        
        # 3. Force Refresh Stock Data
        logger.info("📡 Refreshing stock market data for existing signals...")
        if callback:
            callback.phase("刷新数据", 30)
            callback.step("tool_call", "StockTools", "刷新行情数据")
        stock_tools = StockTools(self.db, auto_update=False)
        updated_tickers = set()
        ticker_logged = 0
        
        for signal in analyzed_signals:
            # Extract tickers from signal
            impact = signal.get('impact_tickers', [])
            if isinstance(impact, list):
                for item in impact:
                    if isinstance(item, dict):
                        ticker = item.get('ticker')
                        if ticker and ticker not in updated_tickers:
                            try:
                                # Force sync from network
                                stock_tools.get_stock_price(str(ticker), force_sync=True)
                                updated_tickers.add(ticker)
                                logger.debug(f"   Refreshed: {ticker}")
                                if callback and ticker_logged < 8:
                                    callback.step("result", "StockTools", f"✅ 刷新: {ticker}")
                                    ticker_logged += 1
                            except Exception as e:
                                logger.warning(f"   Failed to refresh {ticker}: {e}")
                                if callback and ticker_logged < 8:
                                    callback.step("warning", "StockTools", f"⚠️ 刷新失败: {ticker}")
                                    ticker_logged += 1
        
        logger.info(f"✅ Market data refreshed for {len(updated_tickers)} tickers.")
        if callback:
            callback.step("result", "StockTools", f"✅ 刷新完成: {len(updated_tickers)} 支标的")
        
        # 4. Active Signal Evolution (NEW)
        logger.info("🧠 Executing Logic Evolution Tracking for signals...")
        if callback:
            callback.phase("逻辑演变", 50)
            callback.step("thought", "FinAgent", "开始追踪信号逻辑演变")
            
        evolved_signals = []
        track_count = 0
        for sig in analyzed_signals:
            try:
                # 只追踪有效信号
                if not sig.get("title"):
                    continue
                    
                logger.info(f"Tracking signal: {sig['title']}")
                if callback:
                    callback.step("tool_call", "FinAgent", f"追踪: {sig['title']}")
                
                # 调用 FinAgent.track_signal
                new_sig_obj = self.fin_agent.track_signal(sig)
                
                if new_sig_obj:
                    # 转换回字典
                    new_sig_dict = new_sig_obj.dict()
                    # 确保保留一些不可变的元数据（如果需要）
                    new_sig_dict['sources'] = sig.get('sources', []) + new_sig_dict.get('sources', [])
                    evolved_signals.append(new_sig_dict)
                    track_count += 1
                    logger.info(f"✅ Evolved: {sig['title']} -> Sentiment: {new_sig_dict.get('sentiment_score')}")
                else:
                    # 如果追踪失败，保留原信号但标记警告
                    logger.warning(f"⚠️ Tracking failed for {sig['title']}, keeping original")
                    evolved_signals.append(sig)
                    
            except Exception as e:
                logger.error(f"Error tracking {sig.get('title')}: {e}")
                evolved_signals.append(sig)

        logger.info(f"✅ Evolution completed. {track_count}/{len(analyzed_signals)} signals evolved.")
        if callback:
            callback.step("result", "FinAgent", f"逻辑演变完成 ({track_count} 个信号更新)")

        # Use evolved signals for report
        final_signals = evolved_signals if evolved_signals else analyzed_signals

        # 5. Generate Updated Report
        # Construct a context query that guides the writer to focus on updates
        update_context = (
            f"【更新模式】这是一份基于旧版报告（RunID: {base_run_id}）的更新版本。"
            "分析师已经基于最新市场情况更新了所有信号的【推演逻辑(reasoning)】和【情绪分数】。"
            "请重点对比新旧逻辑的变化，特别是‘逻辑演变’部分。"
        )
        if user_query:
            update_context += f"\n用户附加指令: {user_query}"

        if callback:
            callback.phase("报告生成", 80)
            callback.step("thought", "ReportAgent", "生成演变对比报告")
        
        # Reuse ReportAgent with NEW signals
        result = self.report_agent.generate_report(final_signals, user_query=update_context)
        report_md = result.content if hasattr(result, "content") else str(result)
        if hasattr(result, "structured"):
            new_ckpt.save_json("report_structured.json", result.structured)
            if callback:
                callback.step("result", "ReportAgent", "✅ 已生成结构化报告")
        
        # 6. Save Artifacts
        new_ckpt.save_text("report.md", report_md)
        new_ckpt.save_json("analyzed_signals.json", final_signals) # Save the EVOLVED signals
        
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)
        
        # Naming convention: indicate it's an update
        timestamp = now_utc().strftime('%Y%m%d_%H%M')
        md_filename = f"{report_dir}/daily_report_UPDATE_{base_run_id}_{timestamp}.md"
        
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(report_md)
            
        html_filename = save_report_as_html(md_filename)
        if callback:
            callback.step("result", "ReportAgent", "📄 报告已生成")
        
        new_ckpt.save_json("state.json", {
            "run_id": new_run_id,
            "parent_run_id": base_run_id,
            "status": "completed",
            "finished_at": now_utc().isoformat(),
            "output": html_filename or md_filename
        })
        
        logger.info(f"✅ Update Run Completed: {new_run_id}")
        return new_run_id

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="DeepEar Workflow - Investment Signal Analysis")
    parser.add_argument("--template", type=str, default="default_isq_v1", 
                        help="ISQ template ID (default: default_isq_v1)")
    parser.add_argument("--sources", type=str, default="all", 
                        help="News sources: 'all', 'financial', 'social', 'tech', or comma-separated list")
    parser.add_argument("--wide", type=int, default=10, 
                        help="Number of news items per source (default: 10)")
    parser.add_argument("--depth", type=str, default="auto", 
                        help="Report depth: 'auto' or integer limit (default: auto)")
    parser.add_argument("--query", type=str, default=None, 
                        help="User query/intent (optional)")
    parser.add_argument("--run-id", type=str, default=None, help="Run id for logs/checkpoints (default: timestamp)")
    parser.add_argument("--resume", action="store_true", help="Resume from latest (or --run-id) checkpoint")
    parser.add_argument(
        "--resume-from",
        type=str,
        default="report",
        choices=["report", "analysis"],
        help="When --resume is set: 'report' reuses report.md; 'analysis' regenerates report from analyzed_signals.json",
    )
    parser.add_argument("--checkpoint-dir", type=str, default="reports/checkpoints", help="Checkpoint base dir")
    parser.add_argument("--log-dir", type=str, default="logs", help="Log directory")
    parser.add_argument("--log-level", type=str, default="DEBUG", help="Log level (INFO/DEBUG/...) ")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrency for signal analysis (default: 1)")
    parser.add_argument("--update-from", type=str, default=None, help="Update an existing run (provide base run ID) to enable tracking analysis")
    
    args = parser.parse_args()
    
    # Parse sources
    if args.sources.lower() in ["all", "financial", "social", "tech"]:
        sources = [args.sources.lower()]
    else:
        sources = [s.strip() for s in args.sources.split(",")]
    
    # Parse depth
    try:
        depth = int(args.depth)
    except ValueError:
        depth = args.depth
    
    # If resuming without explicit run-id, reuse the latest run directory
    if args.resume and not args.run_id:
        run_id = resolve_latest_run_id(args.checkpoint_dir) or make_run_id()
    else:
        run_id = args.run_id or make_run_id()
    log_path = setup_file_logging(run_id=run_id, log_dir=args.log_dir, level=args.log_level)
    logger.info(f"🧾 Log file: {log_path}")

    workflow = SignalFluxWorkflow(isq_template_id=args.template)
    try:
        if args.update_from:
            logger.info(f"🔄 Executing Tracking Analysis based on Run: {args.update_from}")
            workflow.update_run(
                base_run_id=args.update_from,
                checkpoint_dir=args.checkpoint_dir,
                user_query=args.query,
                new_run_id=run_id,
            )
        else:
            workflow.run(
                sources=sources,
                wide=args.wide,
                depth=depth,
                query=args.query,
                run_id=run_id,
                resume=bool(args.resume),
                resume_from=args.resume_from,
                checkpoint_dir=args.checkpoint_dir,
                concurrency=args.concurrency,
            )

        # 打印使用统计报告
        get_stats().print_report()

    except Exception as e:
        # 打印部分统计（即使失败）
        get_stats().print_report()

        # Best-effort crash record
        try:
            ckpt = CheckpointManager(base_dir=args.checkpoint_dir, run_id=run_id)
            ckpt.save_json(
                "state.json",
                {"run_id": run_id, "status": "failed", "error": str(e), "failed_at": now_utc().isoformat()},
            )
        except Exception:
            pass
        raise
