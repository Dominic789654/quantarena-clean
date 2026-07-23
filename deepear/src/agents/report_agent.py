import hashlib
import json
import time
from datetime import datetime, timedelta
import pandas as pd
from typing import List, Dict, Any, Optional
from agno.agent import Agent
from agno.models.base import Model
from loguru import logger
from types import SimpleNamespace

from deepear.src.utils.database_manager import DatabaseManager
from deepear.src.utils.hybrid_search import InMemoryRAG
from deepear.src.utils.json_utils import extract_json
from deepear.src.utils.stock_tools import StockTools
import re
from deepear.src.schema.models import ClusterContext, ForecastResult
from deepear.src.agents.forecast_agent import ForecastAgent
from deepear.src.agents.report.retry import run_agent_with_retry
from deepear.src.agents.report.chart_sanitizer import sanitize_json_chart_blocks
from deepear.src.agents.report.structured_report import build_structured_report as _build_structured_report_impl
from deepear.src.agents.report.citations import (
    make_cite_key as _make_cite_key_impl,
    build_bibliography as _build_bibliography_impl,
    render_references_section as _render_references_section_impl,
    inject_references as _inject_references_impl,
    normalize_citations as _normalize_citations_impl,
    clean_markdown as _clean_markdown_impl,
)
from deepear.src.agents.report.ticker_utils import (
    clean_ticker as _clean_ticker_impl,
    signal_mentions_ticker as _signal_mentions_ticker_impl,
)
from deepear.src.agents.report.forecast_requests import (
    extract_forecast_requests as _extract_forecast_requests_impl,
    build_forecast_map as _build_forecast_map_impl,
)
from deepear.src.prompts.report_agent import (
    get_report_planner_base_instructions,
    get_report_writer_base_instructions,
    get_report_editor_base_instructions,
    format_signal_for_report,
    get_cluster_planner_instructions,
    get_report_planner_instructions,
    get_report_writer_instructions,
    get_report_editor_instructions,
    get_section_editor_instructions,
    get_summary_generator_instructions,
    get_final_assembly_instructions,
    get_cluster_task,
    get_writer_task,
    get_planner_task,
    get_editor_task
)


class ReportAgent:
    """
    研报生成器 (ReportAgent) - Map-Reduce 架构
    支持增量编辑模式，避免一次性加载所有章节
    """

    # 超时和重试配置
    LLM_TIMEOUT_SECONDS = 120  # 单次 LLM 调用超时
    LLM_MAX_RETRIES = 2  # 最大重试次数
    LLM_RETRY_DELAY = 2  # 重试延迟（秒）

    def __init__(self, db: DatabaseManager, model: Model, incremental_edit: bool = True, tool_model: Optional[Model] = None):
        self.db = db
        self.model = model
        self.tool_model = tool_model or model
        self.incremental_edit = incremental_edit
        
        # 0. InMemory RAG for cross-chapter context
        self.rag = InMemoryRAG(data=[], text_fields=["title", "content", "summary"])
        
        # 1. Planner Agent
        self.planner = Agent(
            model=self.tool_model,
            tools=[self.rag.search],
            instructions=[get_report_planner_base_instructions()],
            markdown=False,
            debug_mode=True,
            output_schema=ClusterContext if hasattr(self.tool_model, 'response_format') else None
        )
        
        # 2. Writer Agent
        self.writer = Agent(
            model=model,
            instructions=[get_report_writer_base_instructions()],
            markdown=False,
            debug_mode=True
        )
        
        # 3. Editor Agent
        self.editor = Agent(
            model=self.tool_model,
            tools=[self.rag.search],
            instructions=[get_report_editor_base_instructions()],
            markdown=False,
            debug_mode=True
        )
        
        # 5. Section Editor Agent (用于增量编辑)
        self.section_editor = Agent(
            model=self.tool_model,
            tools=[self.rag.search],
            instructions=[get_report_editor_base_instructions()],
            markdown=False,
            debug_mode=True
        )
        
        # 6. Forecast Agent (lazy init: avoid heavy Kronos load unless actually requested)
        self._forecast_agent: Optional[ForecastAgent] = None
        
        logger.info(f"📝 ReportAgent initialized (incremental_edit={incremental_edit})")

    def _get_forecast_agent(self) -> ForecastAgent:
        if self._forecast_agent is None:
            self._forecast_agent = ForecastAgent(self.db, self.model)
        return self._forecast_agent

    def _run_agent_with_retry(self, agent: Agent, prompt: str, context: str = "LLM call") -> Optional[str]:
        """
        带超时和重试的 Agent 调用

        Args:
            agent: agno Agent 实例
            prompt: 输入提示
            context: 用于日志的上下文描述

        Returns:
            响应内容，如果所有重试都失败则返回 None

        Delegates to `deepear.src.agents.report.retry.run_agent_with_retry`
        (extract-report-agent-retry-helper), forwarding the three timeout/retry
        constants as explicit arguments so per-instance overrides (e.g. tests
        setting `agent.LLM_RETRY_DELAY = 0.01`) keep working unchanged.
        """
        return run_agent_with_retry(
            agent,
            prompt,
            context,
            max_retries=self.LLM_MAX_RETRIES,
            timeout_seconds=self.LLM_TIMEOUT_SECONDS,
            retry_delay=self.LLM_RETRY_DELAY,
        )

    @staticmethod
    def _make_cite_key(url: str, title: str = "", source_name: str = "") -> str:
        """Delegates to `deepear.src.agents.report.citations.make_cite_key`
        (extract-report-agent-citation-manager). The original method touched
        no instance/class state, so this is a pure pass-through -- kept as a
        real staticmethod (not a bare attribute alias) so existing/future
        monkeypatches of the name, and the class-level
        `ReportAgent._make_cite_key(url=..., ...)` calls used by tests to
        derive fixture cite keys, keep working.
        """
        return _make_cite_key_impl(url, title, source_name)

    def _build_bibliography(self, signals: List[Any]) -> tuple[list[Dict[str, Any]], Dict[int, list[str]]]:
        """Build stable bibliography entries and per-signal cite key mapping.

        Returns:
            bib_entries: ordered unique entries: [{key,url,title,source,publish_time}]
            signal_to_keys: {signal_index(1-based): [key1,key2,...]}

        Delegates to `deepear.src.agents.report.citations.build_bibliography`
        (extract-report-agent-citation-manager), forwarding `self.db` as the
        threaded `db` dependency so the internal
        `self._build_bibliography(...)` call site keeps working unchanged.
        """
        return _build_bibliography_impl(signals, db=self.db)

    @staticmethod
    def _render_references_section(bib_entries: list[Dict[str, Any]], key_to_num: Dict[str, int]) -> str:
        """Delegates to
        `deepear.src.agents.report.citations.render_references_section`
        (extract-report-agent-citation-manager). The original method touched
        no instance/class state, so this is a pure pass-through -- kept as a
        real staticmethod (not a bare attribute alias) so existing/future
        monkeypatches of the name keep intercepting the internal
        `self._render_references_section(...)` call sites.
        """
        return _render_references_section_impl(bib_entries, key_to_num)

    @staticmethod
    def _inject_references(report_md: str, references_md: str) -> str:
        """Delegates to `deepear.src.agents.report.citations.inject_references`
        (extract-report-agent-citation-manager). The original method touched
        no instance/class state, so this is a pure pass-through -- kept as a
        real staticmethod (not a bare attribute alias) so existing/future
        monkeypatches of the name keep intercepting the internal
        `self._inject_references(...)` call sites.
        """
        return _inject_references_impl(report_md, references_md)

    @staticmethod
    def _normalize_citations(report_md: str, signal_to_keys: Dict[int, list[str]], key_to_num: Dict[str, int]) -> str:
        """Delegates to `deepear.src.agents.report.citations.normalize_citations`
        (extract-report-agent-citation-manager). The original method touched
        no instance/class state, so this is a pure pass-through -- kept as a
        real staticmethod (not a bare attribute alias) so existing/future
        monkeypatches of the name keep intercepting the internal
        `self._normalize_citations(...)` call sites. All three arguments
        remain required (see
        `openspec/changes/archive/2026-07-23-fix-report-agent-citation-normalize-args/`);
        this move does not reintroduce the fixed two-argument call bug.
        """
        return _normalize_citations_impl(report_md, signal_to_keys, key_to_num)

    @staticmethod
    def _clean_ticker(ticker_raw: str) -> str:
        """Delegates to `deepear.src.agents.report.ticker_utils.clean_ticker`
        (extract-report-agent-forecast-and-ticker-coordinator). The original
        method touched no instance/class state, so this is a pure
        pass-through -- kept as a real staticmethod (not a bare attribute
        alias) so existing/future monkeypatches of the name keep
        intercepting the internal `self._clean_ticker(...)` call sites.
        """
        return _clean_ticker_impl(ticker_raw)

    @classmethod
    def _signal_mentions_ticker(cls, signal: Any, ticker_digits: str) -> bool:
        """Delegates to
        `deepear.src.agents.report.ticker_utils.signal_mentions_ticker`
        (extract-report-agent-forecast-and-ticker-coordinator). The
        original classmethod's only use of `cls` was its nested `norm`
        closure calling `cls._clean_ticker(...)`; the module function needs
        no `cls` at all (it calls `clean_ticker` directly), but this
        delegator stays a `@classmethod` -- not downgraded to a
        `@staticmethod` -- to preserve its original binding kind so any
        future subclass override or `cls`-aware monkeypatch keeps working.
        """
        return _signal_mentions_ticker_impl(signal, ticker_digits)

    def _extract_forecast_requests(self, text: str, context_window_chars: int = 1200) -> List[Dict[str, Any]]:
        """Extract forecast requests from markdown content.

        Returns list of dicts: {ticker, pred_len, title, context_snippet}

        Delegates to
        `deepear.src.agents.report.forecast_requests.extract_forecast_requests`
        (extract-report-agent-forecast-and-ticker-coordinator). The
        original method's only `self.` read was `self._clean_ticker(...)`,
        which became a direct in-module call to `clean_ticker` once both
        functions moved into leaf modules -- nothing is threaded here.
        Kept as a real bound instance method (not a bare attribute alias)
        so existing/future monkeypatches of the name keep intercepting the
        internal `self._extract_forecast_requests(...)` call site inside
        `_build_forecast_map`.
        """
        return _extract_forecast_requests_impl(text, context_window_chars)

    def _build_forecast_map(self, report_text: str, signals: Optional[List[Any]] = None) -> Dict[tuple, ForecastResult]:
        """Generate forecasts once per unique (ticker, pred_len) to ensure consistency across the report.

        Delegates to
        `deepear.src.agents.report.forecast_requests.build_forecast_map`
        (extract-report-agent-forecast-and-ticker-coordinator). Of the
        original method's four `self.` reads, three
        (`self._extract_forecast_requests`, `self._clean_ticker`,
        `self._signal_mentions_ticker`) became direct in-module calls since
        their callees moved into leaf modules alongside this one. The
        fourth, `self._get_forecast_agent()` -- the lazy, per-instance
        Kronos/`ForecastAgent` cache -- is threaded through as the required
        keyword-only `get_forecast_agent` callable per the program plan's
        explicit "inject the lazy `_get_forecast_agent` callable"
        instruction; `_get_forecast_agent` itself stays on this class
        unchanged. Kept as a real bound instance method (not a bare
        attribute alias) so existing/future monkeypatches of the name keep
        intercepting the internal `self._build_forecast_map(...)` call site
        inside `generate_report`.
        """
        return _build_forecast_map_impl(report_text, signals, get_forecast_agent=self._get_forecast_agent)

    @staticmethod
    def _sanitize_json_chart_blocks(text: str) -> str:
        """Best-effort repair for malformed json-chart fenced blocks.

        Delegates to `deepear.src.agents.report.chart_sanitizer.sanitize_json_chart_blocks`
        (extract-report-agent-pure-chart-and-structured-report-functions). The
        original method touched no instance/class state, so this is a pure
        pass-through -- kept as a real staticmethod (not a bare attribute
        alias) so existing/future monkeypatches of the name keep intercepting
        the internal `self._sanitize_json_chart_blocks(...)` call site.
        """
        return sanitize_json_chart_blocks(text)

    def _cluster_signals(self, signals: List[Dict[str, Any]], user_query: str = None) -> List[Dict[str, Any]]:
        """
        使用 Planner 将信号聚类为几个核心主题
        返回: [{"theme_title": "主题A", "signal_ids": [1, 2], "rationale": "..."}]
        """
        # 准备简要输入
        signals_preview = ""
        for i, s in enumerate(signals, 1):
            title = s.title if hasattr(s, 'title') else s.get('title', '')
            signals_preview += f"[{i}] {title}\n"
            
        logger.info(f"🧠 Clustering {len(signals)} signals into themes...")
        
        instruction = get_cluster_planner_instructions(signals_preview, user_query)
        self.planner.instructions = [instruction]
        
        try:
            response = self.planner.run(get_cluster_task(signals_preview))
            content = response.content
            
            cluster_data = extract_json(content)
            if cluster_data and "clusters" in cluster_data:
                clusters = cluster_data["clusters"]
                logger.info(f"✅ Created {len(clusters)} signal clusters.")
                return clusters
            else:
                logger.warning("⚠️ Failed to parse cluster JSON, fallback to individual signal mode.")
                return []
                
        except Exception as e:
            logger.error(f"Signal clustering failed: {e}")
            return []

    @staticmethod
    def build_structured_report(report_md: str, signals: List[Dict[str, Any]], clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建结构化研报输出（便于前端渲染）

        Delegates to `deepear.src.agents.report.structured_report.build_structured_report`
        (extract-report-agent-pure-chart-and-structured-report-functions). The
        original method touched no instance/class state, so this is a pure
        pass-through -- kept as a real staticmethod (not a bare attribute
        alias) so existing/future monkeypatches of the name keep intercepting
        the internal `self.build_structured_report(...)` call site.
        """
        return _build_structured_report_impl(report_md, signals, clusters)

    def generate_report(self, signals: List[Dict[str, Any]], user_query: str = None) -> str:
        """
        执行 Write-Plan-Edit 流程生成研报
        """
        stock_tools = StockTools(self.db, auto_update=False)

        logger.info(f"📝 Starting report generation for {len(signals)} signals...")
        
        # --- Phase 1: Signal Clustering ---
        clusters = self._cluster_signals(signals, user_query)
        
        # 如果聚类失败，或者没有返回 clusters，则回退到每个信号一节（模拟每个信号是一个簇）
        if not clusters:
             clusters = [{"theme_title": (s.title if hasattr(s, 'title') else s.get('title', '')), "signal_ids": [i]} for i, s in enumerate(signals, 1)]

        # Build stable bibliography keys first so Writer can cite deterministically
        bib_entries, signal_to_keys = self._build_bibliography(signals)
        key_to_num = {e.get("key"): i for i, e in enumerate(bib_entries, 1) if e.get("key")}

        # --- Phase 2: Writing Drafts based on Clusters ---
        sections = []
        sources_list_lines = []
        section_titles = []  # 存储 (anchor, title)

        # Sources list shown to the LLM (even though final references are injected programmatically)
        for entry in bib_entries:
            sources_list_lines.append(
                f"[@{entry.get('key')}] {entry.get('title')} ({entry.get('source')}), {entry.get('url') or 'N/A'}"
            )
        
        for i, cluster in enumerate(clusters, 1):
            theme_title = cluster.get("theme_title", f"主题 {i}")
            signal_ids = cluster.get("signal_ids", [])
            cluster.get("rationale", "")
            
            logger.info(f"✍️ Writing draft for theme [{i}/{len(clusters)}]: {theme_title} (Signals: {signal_ids})...")
            
            # 聚合该簇下的所有信号内容
            cluster_signals_text = ""
            cluster_price_context = ""
            cluster_tickers_seen = set()
            
            for sig_idx in signal_ids:
                # 注意：signal_ids 是 1-based，访问 list 需要 -1
                if sig_idx < 1 or sig_idx > len(signals):
                    continue
                    
                signal = signals[sig_idx-1]
                
                # 聚合信号文本
                cluster_signals_text += format_signal_for_report(signal, sig_idx, cite_keys=signal_to_keys.get(sig_idx, [])) + "\n"
                
                # 聚合行情 Context (去重)
                analysis_text = getattr(signal, 'analysis', '') if not isinstance(signal, dict) else signal.get('analysis', '')
                potential_tickers = list(set(re.findall(r'\b(\d{6})\b', analysis_text)))
                for t in potential_tickers:
                    if t not in cluster_tickers_seen:
                        cluster_tickers_seen.add(t)
                        # 获取行情
                        try:
                            end_date = datetime.now().strftime("%Y-%m-%d")
                            start_date = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
                            df_ctx = stock_tools.get_stock_price(t, start_date=start_date, end_date=end_date)
                            if not df_ctx.empty:
                                last_5 = df_ctx.tail(5)
                                prices_str = ", ".join([f"{row['date']}:{row['close']}" for _, row in last_5.iterrows()])
                                cluster_price_context += f"- {t}: {prices_str}\n"
                        except Exception as e:
                            logger.debug(f"Failed to get price context for ticker {t}: {e}")
                            continue

            # 撰写单节草稿 (基于主题)
            writer_instruction = get_report_writer_instructions(
                theme_title=theme_title,
                signal_cluster_text=cluster_signals_text,
                signal_indices=signal_ids,
                price_context=cluster_price_context,
                user_query=user_query
            )
            
            try:
                self.writer.instructions = [writer_instruction] 
                response = self.writer.run(get_writer_task(theme_title))
                content = response.content.strip()
                
                # 尝试提取第一行作为标题
                lines = content.split('\n')
                title_line = lines[0].strip().replace('###', '').strip().replace('#', '')
                # 如果第一行太长或者没标题，就用 theme_title
                final_title = title_line if title_line and len(title_line) < 50 else theme_title
                
                # 存储原始章节，带锚点
                section_content = f"<a id=\"section-{i}\"></a>\n\n{content}\n"
                sections.append(section_content)
                section_titles.append((f"section-{i}", final_title))
                
            except Exception as e:
                logger.error(f"Failed to write section for theme {theme_title}: {e}")
        
        if not sections:
            return "⚠️ 无法生成研报：没有有效的分析章节。"

        sources_list_text = "\n".join(sources_list_lines)
        
        # --- Decision Point: Incremental vs Global ---
        # 如果开启增量编辑，或者内容总长度超过阈值（如 80000 字符），使用增量模式以避免上下文溢出
        total_content_length = sum(len(s) for s in sections)
        use_incremental = self.incremental_edit or total_content_length > 80000
        
        if use_incremental:
            logger.info(f"🔄 Using INCREMENTAL editing mode (sections={len(sections)})...")
            final_response_content = self._incremental_edit(sections, sources_list_text, section_titles, bib_entries=bib_entries, signal_to_keys=signal_to_keys)
        else:
            # --- Phase 3: Global Planning (The Planner) ---
            # 虽然已经聚类，但全局 Planner 仍有助于调整章节顺序和识别分歧
            logger.info("🧠 Using GLOBAL Planning & Editing mode...")
            
            # ... (Rest of global logic remains mostly the same, just operating on theme sections)
            draft_docs = []
            toc_lines = []
            for i, section in enumerate(sections, 1):
                title = section_titles[i-1][1]
                draft_docs.append({
                    "id": str(i),
                    "title": title,
                    "content": section,
                    "summary": section[:500]
                })
                toc_lines.append(f"[{i}] {title}")
            
            self.rag.update_data(draft_docs)
            toc_text = "\n".join(toc_lines)
            
            planner_instruction = get_report_planner_instructions(toc_text, len(signals), user_query)
            self.planner.instructions = [planner_instruction]
            
            try:
                plan_response = self.planner.run(get_planner_task())
                report_plan = plan_response.content
                logger.info("✅ Report plan generated.")
            except Exception as e:
                logger.error(f"Planning failed: {e}")
                report_plan = "（规划失败，请按默认顺序编排）"

            # --- Phase 4: Final Editing (The Editor) ---
            logger.info("🎬 Editing final report based on plan...")
            
            all_drafts_text = "\n---\n".join(sections)
            editor_instruction = get_report_editor_instructions(all_drafts_text, report_plan, sources_list_text)
            self.editor.instructions = [editor_instruction]
            
            try:
                # 使用 Editor 进行重组和润色
                final_response = self.editor.run(get_editor_task())
                final_response_content = final_response.content
            except Exception as e:
                logger.error(f"Final editing failed: {e}")
                final_response_content = f"# 研报生成失败\n\n{e}"

            # Normalize citations + inject programmatic bibliography
            final_response_content = self._normalize_citations(final_response_content, signal_to_keys, key_to_num)
            final_response_content = self._inject_references(
                final_response_content,
                self._render_references_section(bib_entries, key_to_num),
            )

        # 清理 Markdown 标记
        final_response_content = final_response_content.strip()
        if final_response_content.startswith("```markdown"):
            final_response_content = final_response_content[len("```markdown"):].strip()
        if final_response_content.startswith("```"):
            final_response_content = final_response_content[3:].strip()
        if final_response_content.endswith("```"):
            final_response_content = final_response_content[:-3].strip()

        # 统一添加 TOC (如果 Editor 未生成)
        if not use_incremental and "[TOC]" not in final_response_content:
             lines = final_response_content.split('\n')
             if lines and lines[0].strip().startswith('# '):
                 # 插入在标题之后
                 final_response_content = lines[0] + "\n\n[TOC]\n\n" + "\n".join(lines[1:])
             else:
                 # 插入在最前
                 final_response_content = "[TOC]\n\n" + final_response_content
        
        # Fix duplicate headers (e.g. "#### #### Title") caused by LLM stutter
        final_response_content = re.sub(r'(#{1,6})\s+\1', r'\1', final_response_content)

        # Normalize citations + inject programmatic bibliography (incremental path may also pass through here)
        final_response_content = self._normalize_citations(final_response_content, signal_to_keys, key_to_num)
        final_response_content = self._inject_references(
            final_response_content,
            self._render_references_section(bib_entries, key_to_num),
        )
        
        # --- Phase 5: Visualization Processing ---
        logger.info("🎨 Processing visualization...")

        # Repair malformed json-chart blocks (e.g. missing closing fence) before extraction/rendering
        final_response_content = self._sanitize_json_chart_blocks(final_response_content)

        forecast_map = self._build_forecast_map(final_response_content, signals)
        final_report_with_charts = self._process_charts(final_response_content, signals, forecast_map=forecast_map)

        structured_report = self.build_structured_report(final_response_content, signals, clusters)
        return SimpleNamespace(content=final_report_with_charts, structured=structured_report)

    def _clean_markdown(self, text: str) -> str:
        """Helper to remove markdown code fences

        Delegates to `deepear.src.agents.report.citations.clean_markdown`
        (extract-report-agent-citation-manager). The original method touched
        no instance/class state either (it is called as `self._clean_markdown
        (...)` throughout `_incremental_edit`, but never reads or writes
        `self`) -- kept as a real bound method (not a bare attribute alias)
        so existing/future monkeypatches of the name keep intercepting every
        internal `self._clean_markdown(...)` call site.
        """
        return _clean_markdown_impl(text)

    def _incremental_edit(
        self,
        sections: List[str],
        sources_list_text: str,
        section_titles_data: List[tuple] = None,
        bib_entries: Optional[list[Dict[str, Any]]] = None,
        signal_to_keys: Optional[Dict[int, list[str]]] = None,
    ) -> str:
        """增量编辑模式"""
        # 1. 填充 RAG
        draft_docs = []
        toc_lines = []
        for i, section in enumerate(sections, 1):
            if section_titles_data and i <= len(section_titles_data):
                _, title = section_titles_data[i-1]
            else:
                title = f"章节 {i}"
            
            draft_docs.append({
                "id": str(i),
                "title": title,
                "content": section,
                "summary": section[:300]
            })
            toc_lines.append(f"[{i}] {title}")
        
        self.rag.update_data(draft_docs)
        toc = "\n".join(toc_lines)
        
        # 2. 逐节编辑（带重试和超时）
        edited_sections = []
        for i, section in enumerate(sections, 1):
            logger.info(f"✍️ Incremental editing: section {i}/{len(sections)}...")

            editor_instruction = get_section_editor_instructions(i, len(sections), toc)
            self.section_editor.instructions = [editor_instruction]

            # 使用带重试的方法调用 LLM
            response = self._run_agent_with_retry(
                self.section_editor,
                f"请编辑以下章节内容：\n\n{section}",
                context=f"Section {i}/{len(sections)} editing"
            )

            if response:
                cleaned_content = self._clean_markdown(response)
                edited_sections.append(cleaned_content)
            else:
                logger.warning(f"⚠️ Section {i} editing failed after retries, using original")
                edited_sections.append(self._clean_markdown(section))

            # 简短延迟避免 API 过载
            time.sleep(0.5)
        
        # 3. 生成摘要（带重试和超时）
        logger.info("📝 Generating summary (incremental)...")
        section_summaries = "\n".join([s[:200] + "..." for s in edited_sections])
        summary_instruction = get_summary_generator_instructions(toc, section_summaries)
        self.editor.instructions = [summary_instruction]

        summary_response = self._run_agent_with_retry(
            self.editor,
            "请生成核心观点摘要。",
            context="Summary generation"
        )

        if summary_response:
            summary = self._clean_markdown(summary_response)
        else:
            logger.warning("⚠️ Summary generation failed after retries")
            summary = "（摘要生成失败，请参阅各章节详情。）"

        # 4. 生成参考文献和尾部内容（带重试和超时）
        logger.info("📚 Generating references (incremental)...")
        assembly_instruction = get_final_assembly_instructions(sources_list_text)
        self.editor.instructions = [assembly_instruction]

        tail_response = self._run_agent_with_retry(
            self.editor,
            "请生成参考文献、风险提示和快速扫描表格。",
            context="Tail content generation"
        )

        quick_scan = ""
        other_tail = ""

        if tail_response:
            try:
                tail_content = self._clean_markdown(tail_response)
                # Some models (or fallback templates) may accidentally indent headings, turning them into code blocks.
                tail_content = re.sub(r'(?m)^[ \t]+(#{1,6}\s+)', r'\1', tail_content)
                # And sometimes they indent whole sections (e.g. 12 spaces). Tail is expected to be prose/tables, not code.
                tail_content = re.sub(r'(?m)^[ \t]{4,}(?=\S)', '', tail_content)

                # Guardrail: some models ask the user for more info instead of generating the required sections.
                bad_markers = ["为了完成您的请求", "我需要您提供", "请您提供", "请提供必要的细节"]
                if any(m in tail_content for m in bad_markers) or ("参考文献" not in tail_content and "风险提示" not in tail_content):
                    raise ValueError("Tail content looks invalid; falling back")

                # 分离快速扫描和其他尾部内容
                if "快速扫描" in tail_content:
                    parts = tail_content.split("## 快速扫描")
                    if len(parts) == 2:
                        other_tail = parts[0].strip()
                        quick_scan = "## 快速扫描" + parts[1].split("## ")[0] if "## " in parts[1] else "## 快速扫描" + parts[1]
                else:
                    other_tail = tail_content
            except Exception as e:
                logger.warning(f"⚠️ Tail content processing failed: {e}, using fallback")
                tail_response = None

        if not tail_response:
            logger.warning("⚠️ Tail content generation failed after retries, using fallback template")
            quick_scan = ""
            sources_clean = (sources_list_text or "").strip()
            other_tail = (
                "## 参考文献\n\n"
                + (sources_clean + "\n\n" if sources_clean else "（无）\n\n")
                + "## 风险提示\n\n"
                + "本报告由 AI 自动生成，仅供参考，不构成投资建议。\n"
            )

        # Programmatically inject references to avoid LLM instability
        try:
            bib_entries_safe = bib_entries or []
            key_to_num = {e.get("key"): i for i, e in enumerate(bib_entries_safe, 1) if e.get("key")}
            other_tail = self._inject_references(other_tail, self._render_references_section(bib_entries_safe, key_to_num))
        except Exception as e:
            logger.debug(f"Failed to inject references programmatically: {e}")
        
        # 5. 组装最终报告
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        # 清理 edited_sections：只做代码块保护和基本清理
        
        # 清理 edited_sections 中的标题层级问题
        cleaned_sections = []
        for section in edited_sections:
            # 保护代码块：先临时替换代码块内容
            code_blocks = []
            def preserve_code_block(match):
                code_blocks.append(match.group(0))
                return f"__CODE_BLOCK_{len(code_blocks) - 1}__"
            
            section_protected = re.sub(r'```[\s\S]*?```', preserve_code_block, section)
            
            # 只清理明显的错误：重复的 # 符号（LLM stutter）
            # 移除重复的 # 符号
            section_fixed = re.sub(r'(#{1,6})\s+\1+', r'\1', section_protected)
            
            # 恢复代码块
            for i, block in enumerate(code_blocks):
                section_fixed = section_fixed.replace(f"__CODE_BLOCK_{i}__", block)
            
            cleaned_sections.append(section_fixed)
        
        # Use simple string concatenation or 0-indented string to avoid dedent issues with dynamic content
        sections_text = "\n\n".join(cleaned_sections)
        final_report = f"""# DeepEar 全球市场趋势日报 ({current_date})

[TOC]

{quick_scan}

{summary}

{sections_text}

{other_tail}
"""
        # Fix duplicate headers (e.g. "#### #### Title") caused by LLM stutter
        final_report = re.sub(r'(#{1,6})\s+\1', r'\1', final_report)

        # Normalize citations for final report
        bib_entries_safe = bib_entries or []
        key_to_num = {e.get("key"): i for i, e in enumerate(bib_entries_safe, 1) if e.get("key")}
        final_report = self._normalize_citations(final_report, signal_to_keys or {}, key_to_num)
        
        # 移除连续的空行（最多保留2个）
        final_report = re.sub(r'\n{4,}', '\n\n\n', final_report)
         
        return final_report.strip()
    

    def _process_charts(self, content: str, signals: List[Dict[str, Any]] = None, forecast_map: Optional[Dict[tuple, ForecastResult]] = None) -> str:
        """解析 json-chart 代码块并替换为 HTML 链接/Iframe"""
        from utils.visualizer import VisualizerTools
        from utils.stock_tools import StockTools
        
        stock_tools = StockTools(self.db, auto_update=False)

        # Cache rendered forecast HTML per (ticker, pred_len) to guarantee identical output across duplicates
        rendered_forecast_html: Dict[tuple, str] = {}

        def replace_match(match):
            json_str = match.group(1).strip()
            # Normalize smart quotes that frequently break JSON parsing.
            json_str = (
                json_str.replace("\u201c", '"')
                .replace("\u201d", '"')
                .replace("\u2018", "'")
                .replace("\u2019", "'")
                .replace("“", '"')
                .replace("”", '"')
                .replace("‘", "'")
                .replace("’", "'")
            )
            try:
                config = extract_json(json_str)
                if not config:
                    raise ValueError("No valid JSON found in chart block")
                
                chart_type = config.get("type")
                
                if chart_type == "stock":
                    ticker_raw = config.get("ticker", "")
                    base_title = config.get("title", f"{ticker_raw} 走势")
                    prediction = config.get("prediction", None)
                    
                    # 处理多个 ticker 的情况（逗号或空格分隔）
                    tickers = re.split(r'[,\s]+', str(ticker_raw).strip())
                    
                    # 尝试解析每个 ticker
                    valid_tickers = []
                    for t in tickers:
                        t = t.strip()
                        if not t:
                            continue
                        
                        # 1. 预处理：移除后缀
                        clean_t = t.split('.')[0] if '.' in t else t
                        
                        # 2. 直接匹配：5位(港股) 或 6位(A股) 数字代码
                        if clean_t.isdigit() and (len(clean_t) == 5 or len(clean_t) == 6):
                            valid_tickers.append(clean_t)
                            logger.info(f"📊 Extracted ticker {clean_t} from {t}")
                            continue

                        # 3. 尝试模糊匹配（处理名称、短代码等）
                        if len(t) > 1 or (clean_t.isdigit() and len(clean_t) < 5):
                            try:
                                search_results = stock_tools.search_ticker(t)
                                if search_results and len(search_results) > 0:
                                    best_match = None
                                    
                                    # 智能匹配逻辑
                                    if clean_t.isdigit():
                                        # 构造可能的完整代码
                                        candidates = []
                                        # 如果明确是 HK 后缀，优先匹配 5 位补零
                                        if '.HK' in t.upper():
                                            candidates.append(clean_t.zfill(5))
                                        # 如果明确是 A 股后缀，优先匹配 6 位补零
                                        elif '.SZ' in t.upper() or '.SH' in t.upper():
                                            candidates.append(clean_t.zfill(6))
                                        else:
                                            # 无后缀，都尝试，优先 5 位 (港股短码常见)，然后 6 位
                                            candidates.append(clean_t.zfill(5))
                                            candidates.append(clean_t.zfill(6))
                                        
                                        # 在搜索结果中寻找完全匹配
                                        for cand in candidates:
                                            for res in search_results:
                                                if res['code'] == cand:
                                                    best_match = res['code']
                                                    break
                                            if best_match:
                                                break
                                    
                                    # 如果没有通过数字补全找到，尝试名称匹配或默认第一个
                                    if not best_match:
                                        # 再次遍历，看有没有完全等于 clean_t 的 (虽然前面 digit check 应该覆盖了)
                                        for res in search_results:
                                            if res['code'] == clean_t:
                                                best_match = res['code']
                                                break
                                    
                                    final_ticker = best_match if best_match else search_results[0].get('code', '')
                                    
                                    if final_ticker:
                                        valid_tickers.append(final_ticker)
                                        logger.info(f"📊 Fuzzy matched ticker {final_ticker} from query '{t}'")
                            except Exception as e:
                                logger.warning(f"⚠️ Fuzzy search failed for {t}: {e}")
                    
                    tickers = valid_tickers
                    
                    if not tickers:
                        logger.warning(f"⚠️ No valid ticker found in: {ticker_raw}")
                        return f"\n<!-- 无法解析股票代码: {ticker_raw} -->\n"

                    
                    if len(tickers) > 1:
                        logger.info(f"📊 Multiple tickers detected: {tickers}, generating charts for all")
                    
                    # 为每个 ticker 生成图表
                    all_charts_html: List[str] = []
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
                    
                    for idx, ticker in enumerate(tickers):
                        # 如果有多个 ticker，为每个生成独立的标题
                        if len(tickers) > 1:
                            chart_title = f"{ticker} - {base_title}"
                        else:
                            chart_title = base_title
                        
                        df = stock_tools.get_stock_price(ticker, start_date=start_date, end_date=end_date)
                        
                        if not df.empty:
                            # Optional: attach Kronos forecast if explicitly requested
                            forecast_obj = None
                            if config.get("show_forecast", False) or config.get("forecast", False):
                                try:
                                    related_signals = []
                                    if signals:
                                        for s in signals:
                                            analysis_text = getattr(s, 'analysis', '') if not isinstance(s, dict) else s.get('analysis', '')
                                            title_text = getattr(s, 'title', '') if not isinstance(s, dict) else s.get('title', '')
                                            full_text = f"{title_text} {analysis_text}"
                                            if str(ticker) in full_text:
                                                related_signals.append(s)
                                    forecast_obj = self._get_forecast_agent().generate_forecast(ticker, related_signals)
                                except Exception as e:
                                    logger.warning(f"⚠️ Forecast generation failed for {ticker}: {e}")
                                    forecast_obj = None

                            chart = VisualizerTools.generate_stock_chart(
                                df,
                                ticker,
                                chart_title,
                                prediction=prediction,
                                forecast=forecast_obj
                            )

                            if chart:
                                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                                filename = f"reports/charts/stock_{ticker}_{timestamp}.html"
                                VisualizerTools.render_chart_to_file(chart, filename)
                                rel_path = f"charts/stock_{ticker}_{timestamp}.html"
                                all_charts_html.append(
                                    f'<iframe src="{rel_path}" width="100%" height="500px" style="border:none;"></iframe>\n'
                                    f'<p style="text-align:center;color:gray;font-size:12px">交互式图表: {chart_title}</p>'
                                )
                        else:
                            logger.warning(f"⚠️ No data for ticker: {ticker}")
                    
                    if all_charts_html:
                        return "\n" + "\n".join(all_charts_html) + "\n"
                    else:
                        return f"\n<!-- 无法获取股票数据: {ticker_raw} -->\n"

                elif chart_type == "forecast":
                    ticker_raw = config.get("ticker", "")
                    title = config.get("title", f"{ticker_raw} 预测")
                    pred_len = config.get("pred_len", 5)
                    
                    # Only allow one ticker for forecast (supports suffix like 002371.SZ / 9868.HK)
                    t = str(ticker_raw).strip().split(',')[0].strip()
                    clean_t = t.split('.')[0] if '.' in t else t
                    clean_t = ''.join([c for c in clean_t if c.isdigit()]) or clean_t
                    if not (clean_t.isdigit() and len(clean_t) in (5, 6)):
                        return (
                            f'\n<p style="text-align:center;color:#b45309;font-size:13px;'
                            f'background:#fffbeb;padding:10px;border:1px dashed #f59e0b;border-radius:8px;">'
                            f'⚠️ 暂不支持该股票代码的预测渲染：{ticker_raw}（仅支持 A 股 6 位 / 港股 5 位数字代码）。'
                            f'</p>\n'
                        )
                    ticker = clean_t
                    
                    # Gather signals that mention this ticker
                    related_signals = []
                    if signals:
                        for s in signals:
                            # 辅助函数：从信号中提取所有相关的 ticker
                            # 兼容字典和 Pydantic 模型
                            analysis_text = getattr(s, 'analysis', '') if not isinstance(s, dict) else s.get('analysis', '')
                            title_text = getattr(s, 'title', '') if not isinstance(s, dict) else s.get('title', '')
                            full_text = f"{title_text} {analysis_text}"
                            if ticker in full_text:
                                related_signals.append(s)
                    
                    key = (ticker, int(pred_len) if str(pred_len).isdigit() else 5)

                    if key in rendered_forecast_html:
                        return rendered_forecast_html[key]

                    forecast_obj = None
                    if forecast_map and key in forecast_map:
                        forecast_obj = forecast_map[key]
                    else:
                        # Backward-compatible fallback (may be inconsistent across duplicates)
                        forecast_obj = self._get_forecast_agent().generate_forecast(ticker, related_signals, pred_len=pred_len)
                    
                    # Fetch history for rendering
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
                    df = stock_tools.get_stock_price(ticker, start_date=start_date, end_date=end_date)
                    
                    if df.empty:
                        html = f"<!-- 无法获取股票数据: {ticker} -->"
                        rendered_forecast_html[key] = html
                        return html

                    if forecast_obj:
                        chart = VisualizerTools.generate_stock_chart(df, ticker, title, forecast=forecast_obj)
                        if chart:
                            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                            filename = f"reports/charts/forecast_{ticker}_{timestamp}.html"
                            VisualizerTools.render_chart_to_file(chart, filename)

                            rel_path = f"charts/forecast_{ticker}_{timestamp}.html"
                            html = (
                                f'<iframe src="{rel_path}" width="100%" height="500px" style="border:none;"></iframe>\n'
                                f'<p style="text-align:center;color:gray;font-size:12px">AI 深度预测: {title}</p>'
                            )
                            html += (
                                f'\n<p style="font-size:13px; color:#555; background:#f9f9f9; padding:10px; '
                                f'border-left:4px solid #9333ea;"><b>预测逻辑:</b> {forecast_obj.rationale}</p>\n'
                            )
                            rendered_forecast_html[key] = html
                            return html

                    # Fallback: forecast failed, still render history-only chart
                    chart = VisualizerTools.generate_stock_chart(df, ticker, title)
                    if chart:
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        filename = f"reports/charts/stock_{ticker}_{timestamp}.html"
                        VisualizerTools.render_chart_to_file(chart, filename)
                        rel_path = f"charts/stock_{ticker}_{timestamp}.html"
                        html = (
                            f'<iframe src="{rel_path}" width="100%" height="500px" style="border:none;"></iframe>\n'
                            f'<p style="text-align:center;color:gray;font-size:12px">（预测失败，已展示历史行情）{title}</p>'
                        )
                        rendered_forecast_html[key] = html
                        return html

                    html = f"<!-- FORECAST FAILED FOR {ticker} -->"
                    rendered_forecast_html[key] = html
                    return html



                
                elif chart_type == "sentiment":
                    keywords = config.get("keywords", [])
                    title = config.get("title", "舆情情绪趋势")
                    
                    if keywords:
                        # 使用参数化查询防止 SQL 注入
                        conditions = " OR ".join(["content LIKE ?" for _ in keywords])
                        params = tuple(f"%{k}%" for k in keywords)
                        query = f"SELECT publish_time, sentiment_score FROM daily_news WHERE ({conditions}) AND sentiment_score IS NOT NULL ORDER BY publish_time"
                        
                        logger.info(f"📊 Executing sentiment query: {query} with {len(params)} params")
                        results = self.db.execute_query(query, params)
                        logger.info(f"📊 Query result count: {len(results)}")
                        
                        if not results or len(results) == 0:
                            # Fallback: Try broadening search by splitting keywords
                            logger.info("⚠️ Initial sentiment query empty, attempting fallback with split keywords...")
                            broad_keywords = []
                            for k in keywords:
                                broad_keywords.extend(k.split())
                            
                            # Deduplicate and filter short words
                            broad_keywords = list(set([k for k in broad_keywords if len(k) > 1]))
                            
                            if broad_keywords:
                                conditions = " OR ".join(["content LIKE ?" for _ in broad_keywords])
                                params = tuple(f"%{k}%" for k in broad_keywords)
                                query = f"SELECT publish_time, sentiment_score FROM daily_news WHERE ({conditions}) AND sentiment_score IS NOT NULL ORDER BY publish_time"
                                logger.info(f"📊 Executing fallback sentiment query: {query} with {len(params)} params")
                                results = self.db.execute_query(query, params)
                                logger.info(f"📊 Fallback query result count: {len(results)}")

                        if results:
                            # 格式化数据
                            sentiment_history = []
                            for row in results:
                                try:
                                    # 假设 publish_time 是字符串，或者 date object
                                    dt = row[0]
                                    if isinstance(dt, datetime):
                                        d_str = dt.strftime("%Y-%m-%d")
                                    else:
                                        d_str = str(dt)[:10] # 截取日期部分
                                        
                                    sentiment_history.append({"date": d_str, "score": row[1]})
                                except (TypeError, ValueError, IndexError) as e:
                                    logger.debug(f"Failed to parse sentiment row: {e}")
                                    continue
                            
                            # 聚合每天的平均分
                            df_sent = pd.DataFrame(sentiment_history)
                            if not df_sent.empty:
                                df_sent = df_sent.groupby('date')['score'].mean().reset_index()
                                sentiment_history_agg = df_sent.to_dict('records')
                                
                                chart = VisualizerTools.generate_sentiment_trend_chart(sentiment_history_agg)
                                if chart:
                                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                                    filename = f"reports/charts/sentiment_{timestamp}.html"
                                    VisualizerTools.render_chart_to_file(chart, filename)
                                    rel_path = f"charts/sentiment_{timestamp}.html"
                                    return f'\n<iframe src="{rel_path}" width="100%" height="400px" style="border:none;"></iframe>\n<p style="text-align:center;color:gray;font-size:12px">交互式图表: {title}</p>\n'
                        
                        # Fallback for sentiment if query results are empty
                        return f'\n<p style="text-align:center;color:gray;font-size:12px;padding:20px;border:1px dashed #ccc;border-radius:8px;">📊 暂无足够历史数据生成 "{title}" 的趋势图</p>\n'

                elif chart_type == "isq":
                    sentiment = config.get("sentiment", 0.0)
                    confidence = config.get("confidence", 0.5)
                    intensity = config.get("intensity", 3)
                    expectation_gap = config.get("expectation_gap", 0.5)
                    timeliness = config.get("timeliness", 0.8)
                    title = config.get("title", "信号质量 ISQ 评估")
                    
                    chart = VisualizerTools.generate_isq_radar_chart(
                        sentiment, confidence, intensity, 
                        expectation_gap=expectation_gap, 
                        timeliness=timeliness, 
                        title=title
                    )
                    if chart:
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        # Avoid collisions: multiple ISQ charts can be rendered within the same second.
                        payload = {
                            "type": "isq",
                            "sentiment": sentiment,
                            "confidence": confidence,
                            "intensity": intensity,
                            "expectation_gap": expectation_gap,
                            "timeliness": timeliness,
                            "title": title,
                        }
                        content_hash = hashlib.md5(
                            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
                        ).hexdigest()[:8]
                        filename = f"reports/charts/isq_{timestamp}_{content_hash}.html"
                        VisualizerTools.render_chart_to_file(chart, filename)
                        rel_path = f"charts/isq_{timestamp}_{content_hash}.html"
                        return f'\n<iframe src="{rel_path}" width="100%" height="420px" style="border:none;"></iframe>\n<p style="text-align:center;color:gray;font-size:12px">信号质量雷达图: {title}</p>\n'

                elif chart_type == "transmission":
                    nodes = config.get("nodes", [])
                    title = config.get("title", "投资逻辑传导链条")
                    
                    if nodes:
                        # 生成基于节点内容的唯一标识
                        nodes_str = json.dumps(nodes, sort_keys=True, ensure_ascii=False)
                        content_hash = hashlib.md5(nodes_str.encode()).hexdigest()[:8]
                        
                        # Generate XML using LLM with retry
                        max_retries = 2
                        xml_success = False
                        
                        for attempt in range(max_retries):
                            try:
                                from prompts.visualizer import get_drawio_system_prompt, get_drawio_task
                                
                                # Use tool_model (usually faster/cheaper) or main model
                                # Creating a lightweight agent purely for XML generation
                                visualizer_agent = Agent(
                                    model=self.tool_model,
                                    instructions=[get_drawio_system_prompt()],
                                    markdown=False
                                )
                                
                                logger.info(f"🎨 Generating Draw.io XML for '{title}' (attempt {attempt + 1}/{max_retries})...")
                                resp = visualizer_agent.run(get_drawio_task(nodes, title))
                                xml_content = resp.content
                                
                                # Basic cleanup if LLM wrapped in markdown code blocks
                                match = re.search(r'<mxGraphModel.*?</mxGraphModel>', xml_content, re.DOTALL)
                                if match:
                                    xml_content = match.group(0)
                                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                                    filename = f"reports/charts/trans_{timestamp}_{content_hash}.html"
                                    
                                    result_path = VisualizerTools.render_drawio_to_html(xml_content, filename, title)
                                    if result_path:
                                        rel_path = f"charts/trans_{timestamp}_{content_hash}.html"
                                        xml_success = True
                                        return f'\n<iframe src="{rel_path}" width="100%" height="500px" style="border:none;"></iframe>\n<p style="text-align:center;color:gray;font-size:12px">交互式逻辑推演图: {title} (AI Generated)</p>\n'
                                    else:
                                        logger.warning(f"⚠️ Render failed for {title}, attempt {attempt + 1}")
                                else:
                                    logger.warning(f"⚠️ Failed to extract XML from response for {title}, attempt {attempt + 1}")
                                    
                            except Exception as e:
                                logger.error(f"Draw.io generation failed (attempt {attempt + 1}): {e}")
                            
                            # Wait before retry
                            if attempt < max_retries - 1:
                                import time
                                time.sleep(1)
                        
                        # Fallback mechanism (Old Graph) if all retries failed
                        if not xml_success:
                            logger.info("⚠️ Falling back to Pyecharts Graph for Transmission Chain.")
                            chart = VisualizerTools.generate_transmission_graph(nodes, title)
                            if chart:
                                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                                filename = f"reports/charts/trans_legacy_{timestamp}_{content_hash}.html"
                                VisualizerTools.render_chart_to_file(chart, filename)
                                rel_path = f"charts/trans_legacy_{timestamp}_{content_hash}.html"
                                return f'\n<iframe src="{rel_path}" width="100%" height="420px" style="border:none;"></iframe>\n<p style="text-align:center;color:gray;font-size:12px">逻辑传导拓扑图: {title}</p>\n'

                # 如果是其他类型或失败，保留原文或者显示错误
                return f"```json\n{json_str}\n```" # Fallback to json display if render fails logic mismatch
            
            except Exception as e:
                logger.error(f"Chart processing failed: {e}")
                return match.group(0) # Return original text on error

        # 匹配 ```json-chart ... ```
        pattern = re.compile(r'```json-chart\s*(\{.*?\})\s*```', re.DOTALL)
        new_content = pattern.sub(replace_match, content)

        # Make invalid-forecast-ticker failures visible (older versions emitted HTML comments)
        new_content = re.sub(
            r'<!--\s*NO VALID TICKER FOR FORECAST:\s*([^>]+?)\s*-->',
            lambda m: (
                '\n<p style="text-align:center;color:#b45309;font-size:13px;'
                'background:#fffbeb;padding:10px;border:1px dashed #f59e0b;border-radius:8px;">'
                f'⚠️ 暂不支持该股票代码：{m.group(1).strip()}。'
                '</p>\n'
            ),
            new_content,
        )

        return new_content
