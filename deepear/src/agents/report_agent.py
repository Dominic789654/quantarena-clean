import time
from datetime import datetime, timedelta
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
from deepear.src.agents.report.chart_renderer import process_charts as _process_charts_impl
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
        return _process_charts_impl(
            content,
            signals,
            forecast_map,
            db=self.db,
            tool_model=self.tool_model,
            get_forecast_agent=self._get_forecast_agent,
            agent_cls=Agent,
        )
