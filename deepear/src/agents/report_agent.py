import hashlib
import json
import textwrap
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
from deepear.src.schema.models import InvestmentSignal, InvestmentReport, TransmissionNode, ClusterContext, ForecastResult
from deepear.src.agents.forecast_agent import ForecastAgent
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
        """
        import threading
        import functools

        for attempt in range(self.LLM_MAX_RETRIES + 1):
            try:
                # 使用线程和超时控制
                result = [None]
                exception = [None]

                def run_in_thread():
                    try:
                        response = agent.run(prompt)
                        result[0] = response.content if hasattr(response, 'content') else str(response)
                    except Exception as e:
                        exception[0] = e

                thread = threading.Thread(target=run_in_thread)
                thread.start()
                thread.join(timeout=self.LLM_TIMEOUT_SECONDS)

                if thread.is_alive():
                    # 超时
                    logger.warning(f"⚠️ {context} timed out after {self.LLM_TIMEOUT_SECONDS}s (attempt {attempt + 1}/{self.LLM_MAX_RETRIES + 1})")
                    if attempt < self.LLM_MAX_RETRIES:
                        time.sleep(self.LLM_RETRY_DELAY * (attempt + 1))  # 指数退避
                        continue
                    return None

                if exception[0] is not None:
                    raise exception[0]

                return result[0]

            except Exception as e:
                logger.warning(f"⚠️ {context} failed (attempt {attempt + 1}/{self.LLM_MAX_RETRIES + 1}): {e}")
                if attempt < self.LLM_MAX_RETRIES:
                    time.sleep(self.LLM_RETRY_DELAY * (attempt + 1))  # 指数退避
                    continue

        logger.error(f"❌ {context} failed after all retries")
        return None

    @staticmethod
    def _make_cite_key(url: str, title: str = "", source_name: str = "") -> str:
        basis = (url or "").strip() or f"{(title or '').strip()}|{(source_name or '').strip()}"
        digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]
        return f"SF-{digest}"

    def _build_bibliography(self, signals: List[Any]) -> tuple[list[Dict[str, Any]], Dict[int, list[str]]]:
        """Build stable bibliography entries and per-signal cite key mapping.

        Returns:
            bib_entries: ordered unique entries: [{key,url,title,source,publish_time}]
            signal_to_keys: {signal_index(1-based): [key1,key2,...]}
        """
        bib_by_key: Dict[str, Dict[str, Any]] = {}
        signal_to_keys: Dict[int, list[str]] = {}

        for sig_idx, signal in enumerate(signals, 1):
            source_items: list[Dict[str, Any]] = []

            if hasattr(signal, "sources") and getattr(signal, "sources"):
                source_items = list(getattr(signal, "sources") or [])
            elif isinstance(signal, dict) and signal.get("sources"):
                # analyzed_signals are dicts; their sources are nested under the `sources` key
                src_list = signal.get("sources")
                if isinstance(src_list, list) and src_list:
                    source_items = list(src_list)
            elif isinstance(signal, dict):
                # Treat raw signals as single-source entries
                if signal.get("url") or signal.get("title"):
                    source_items = [
                        {
                            "title": signal.get("title"),
                            "url": signal.get("url"),
                            "source_name": signal.get("source") or signal.get("source_name"),
                            "publish_time": signal.get("publish_time"),
                        }
                    ]

            if not source_items:
                continue

            for src in source_items:
                url = (src.get("url") or "").strip()
                title = (src.get("title") or "").strip()
                source_name = (src.get("source_name") or src.get("source") or "").strip()
                publish_time = (src.get("publish_time") or "").strip() if isinstance(src.get("publish_time"), str) else src.get("publish_time")

                key = self._make_cite_key(url=url, title=title, source_name=source_name)
                signal_to_keys.setdefault(sig_idx, [])
                if key not in signal_to_keys[sig_idx]:
                    signal_to_keys[sig_idx].append(key)

                if key in bib_by_key:
                    continue

                # Prefer canonical metadata from DB when possible
                enriched = self.db.lookup_reference_by_url(url) if url else None
                bib_by_key[key] = {
                    "key": key,
                    "url": url or (enriched.get("url") if enriched else ""),
                    "title": (enriched.get("title") if enriched else None) or title or "（无标题）",
                    "source": (enriched.get("source") if enriched else None) or source_name or "（未知来源）",
                    "publish_time": (enriched.get("publish_time") if enriched else None) or publish_time or "",
                }

        return list(bib_by_key.values()), signal_to_keys

    @staticmethod
    def _render_references_section(bib_entries: list[Dict[str, Any]], key_to_num: Dict[str, int]) -> str:
        lines = ["## 参考文献", ""]
        if not bib_entries:
            lines.append("（无）")
            return "\n".join(lines).strip() + "\n"

        for entry in bib_entries:
            key = entry.get("key")
            num = key_to_num.get(key) if key else None
            title = entry.get("title") or "（无标题）"
            source = entry.get("source") or "（未知来源）"
            url = entry.get("url") or ""
            publish_time = entry.get("publish_time") or ""
            suffix = ""
            if publish_time:
                suffix = f"，{publish_time}"
            label = f"[{num}]" if isinstance(num, int) else "[?]"
            if url:
                lines.append(f"<a id=\"ref-{key}\"></a>{label} {title} ({source}{suffix}), {url}")
            else:
                lines.append(f"<a id=\"ref-{key}\"></a>{label} {title} ({source}{suffix})")

        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _inject_references(report_md: str, references_md: str) -> str:
        # Replace existing references section, if any
        pattern = re.compile(r"(?ms)^##\s*参考文献\s*$.*?(?=^##\s|\Z)")
        if pattern.search(report_md or ""):
            return pattern.sub(references_md.strip() + "\n\n", report_md).strip()

        # Otherwise append at end
        return (report_md or "").rstrip() + "\n\n" + references_md.strip() + "\n"

    @staticmethod
    def _normalize_citations(report_md: str, signal_to_keys: Dict[int, list[str]], key_to_num: Dict[str, int]) -> str:
        text = report_md or ""

        # Convert legacy [[n]] to the first available cite key for that signal.
        def repl_legacy(match: re.Match) -> str:
            idx = int(match.group(1))
            keys = signal_to_keys.get(idx) or []
            if not keys:
                return match.group(0)
            key = keys[0]
            num = key_to_num.get(key)
            label = f"[{num}]" if isinstance(num, int) else "[?]"
            return f"{label}(#ref-{key})"

        text = re.sub(r"\[\[(\d+)\]\]", repl_legacy, text)

        # Convert cite keys to numbered display while keeping stable anchor: [@KEY] -> [N](#ref-KEY)
        def repl_key(match: re.Match) -> str:
            key = match.group("key")
            num = key_to_num.get(key)
            label = f"[{num}]" if isinstance(num, int) else "[?]"
            return f"{label}(#ref-{key})"

        text = re.sub(r"\[@(?P<key>[A-Za-z0-9][A-Za-z0-9:_\-]{0,64})\](?!\()", repl_key, text)

        # Convert loose cite markers like: （@SF-xxxxxxxx） / (@SF-xxxxxxxx)
        # These sometimes appear when the model forgets the bracket form.
        def repl_loose_key(match: re.Match) -> str:
            lparen = match.group("lparen")
            rparen = match.group("rparen")
            key = match.group("key")
            num = key_to_num.get(key)
            label = f"[{num}]" if isinstance(num, int) else "[?]"
            return f"{lparen}{label}(#ref-{key}){rparen}"

        text = re.sub(
            r"(?P<lparen>[\(\（])\s*@(?P<key>SF-[0-9a-fA-F]{8})\s*(?P<rparen>[\)\）])",
            repl_loose_key,
            text,
        )

        return text

    @staticmethod
    def _clean_ticker(ticker_raw: str) -> str:
        t = (ticker_raw or "").strip()
        if not t:
            return ""
        if "," in t:
            t = t.split(",")[0].strip()
        if "." in t:
            t = t.split(".")[0].strip()
        digits = "".join([c for c in t if c.isdigit()])
        return digits or t

    @classmethod
    def _signal_mentions_ticker(cls, signal: Any, ticker_digits: str) -> bool:
        if not ticker_digits:
            return False

        def norm(s: str) -> str:
            return cls._clean_ticker(s)

        try:
            # Prefer structured impact_tickers if present
            impact = getattr(signal, 'impact_tickers', None) if not isinstance(signal, dict) else signal.get('impact_tickers')
            if isinstance(impact, list):
                for item in impact:
                    if not isinstance(item, dict):
                        continue
                    t = item.get('ticker') or item.get('code') or item.get('symbol')
                    if t and norm(str(t)) == ticker_digits:
                        return True

            # Fallback to text search
            title_text = getattr(signal, 'title', '') if not isinstance(signal, dict) else signal.get('title', '')
            summary_text = getattr(signal, 'summary', '') if not isinstance(signal, dict) else signal.get('summary', '')
            analysis_text = getattr(signal, 'analysis', '') if not isinstance(signal, dict) else signal.get('analysis', '')
            combined = f"{title_text} {summary_text} {analysis_text}"
            return ticker_digits in combined
        except Exception:
            return False

    def _extract_forecast_requests(self, text: str, context_window_chars: int = 1200) -> List[Dict[str, Any]]:
        """Extract forecast requests from markdown content.

        Returns list of dicts: {ticker, pred_len, title, context_snippet}
        """
        if not text:
            return []

        pattern = re.compile(r'```json-chart\s*(\{.*?\})\s*```', re.DOTALL)
        requests: List[Dict[str, Any]] = []

        for match in pattern.finditer(text):
            json_str = match.group(1).strip()
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
            cfg = extract_json(json_str)
            if not cfg:
                continue
            if cfg.get('type') != 'forecast':
                continue

            ticker_raw = str(cfg.get('ticker', '')).strip()
            ticker = self._clean_ticker(ticker_raw)
            if not (ticker.isdigit() and len(ticker) in (5, 6)):
                continue

            try:
                pred_len = int(cfg.get('pred_len', 5))
            except Exception:
                pred_len = 5
            pred_len = max(1, min(pred_len, 20))

            title = str(cfg.get('title') or f"{ticker_raw} 预测").strip()

            # Prefer writer-provided final attribution over raw surrounding snippet.
            # This supports the workflow: multi-scenario discussion in正文 -> final chosen scenario -> render ONE forecast chart.
            structured_lines: List[str] = []
            selected_scenario = cfg.get('selected_scenario') or cfg.get('scenario') or cfg.get('case')
            selection_reason = cfg.get('selection_reason') or cfg.get('case_reason') or cfg.get('reason')
            scenarios = cfg.get('scenarios')

            if selected_scenario:
                structured_lines.append(f"- 最可能情景: {str(selected_scenario).strip()}")
            if selection_reason:
                structured_lines.append(f"- 归因: {str(selection_reason).strip()}")
            if isinstance(scenarios, list) and scenarios:
                structured_lines.append("- 备选情景:")
                for item in scenarios[:6]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get('name', '')).strip()
                    desc = str(item.get('description', '')).strip()
                    prob = item.get('probability', None)
                    prob_str = ""
                    try:
                        if prob is not None:
                            prob_str = f" (p={float(prob):.2f})"
                    except Exception:
                        prob_str = ""
                    line = "  - " + (name or "（未命名）")
                    if desc:
                        line += f": {desc}"
                    line += prob_str
                    structured_lines.append(line)

            structured_context = ""
            if structured_lines:
                structured_context = "【最终归因/情景选择（作者在 forecast 块中给定）】\n" + "\n".join(structured_lines)

            start = max(0, match.start() - context_window_chars)
            end = min(len(text), match.end() + context_window_chars)
            snippet = text[start:end]
            # remove the code block itself from the snippet to reduce noise
            snippet = snippet.replace(match.group(0), "").strip()
            # remove any other json-chart blocks to avoid polluting forecast context
            snippet = re.sub(r'```json-chart[\s\S]*?```', '', snippet).strip()

            # If structured attribution exists, use it as the primary snippet; keep raw snippet as fallback.
            context_snippet = structured_context or snippet
            if len(context_snippet) > 3500:
                context_snippet = context_snippet[:3500] + "\n\n（上下文过长已截断）"

            requests.append({
                'ticker': ticker,
                'ticker_raw': ticker_raw,
                'pred_len': pred_len,
                'title': title,
                'context_snippet': context_snippet,
            })

        return requests

    def _build_forecast_map(self, report_text: str, signals: Optional[List[Any]] = None) -> Dict[tuple, ForecastResult]:
        """Generate forecasts once per unique (ticker, pred_len) to ensure consistency across the report."""
        reqs = self._extract_forecast_requests(report_text)
        if not reqs:
            return {}

        # Allowlist: only generate forecasts for tickers that are backed by structured signals.
        allowed_tickers: Optional[set[str]] = None
        if signals:
            allowed_tickers = set()
            for s in signals:
                impact = getattr(s, 'impact_tickers', None) if not isinstance(s, dict) else s.get('impact_tickers')
                if not isinstance(impact, list):
                    continue
                for item in impact:
                    if not isinstance(item, dict):
                        continue
                    t = item.get('ticker') or item.get('code') or item.get('symbol')
                    tt = self._clean_ticker(str(t or ""))
                    if tt and tt.isdigit() and len(tt) in (5, 6):
                        allowed_tickers.add(tt)
            if not allowed_tickers:
                allowed_tickers = None

        # group by key, merge context
        grouped: Dict[tuple, Dict[str, Any]] = {}
        for r in reqs:
            key = (r['ticker'], int(r['pred_len']))
            g = grouped.get(key)
            if not g:
                grouped[key] = {
                    'ticker': r['ticker'],
                    'pred_len': int(r['pred_len']),
                    'titles': {r['title']},
                    'snippets': [r.get('context_snippet', '')],
                }
            else:
                g['titles'].add(r['title'])
                sn = r.get('context_snippet', '')
                if sn and sn not in g['snippets']:
                    g['snippets'].append(sn)

        logger.info(f"🔮 Forecast requests: total={len(reqs)}, unique={len(grouped)}")

        forecasts: Dict[tuple, ForecastResult] = {}
        for key, g in grouped.items():
            ticker, pred_len = key

            if allowed_tickers is not None and str(ticker) not in allowed_tickers:
                logger.info(f"ℹ️ Skip forecast for {ticker}: not in validated impact_tickers")
                continue

            related_signals: List[Any] = []
            if signals:
                for s in signals:
                    if self._signal_mentions_ticker(s, str(ticker)):
                        related_signals.append(s)

            # If we have signals context, require at least one related signal for attribution.
            if signals and not related_signals:
                logger.info(f"ℹ️ Skip forecast for {ticker}: no attributable signals")
                continue

            # merge context snippets (cap size)
            merged_snippet = "\n\n---\n\n".join([s for s in g['snippets'] if s])
            if len(merged_snippet) > 3500:
                merged_snippet = merged_snippet[:3500] + "\n\n（上下文过长已截断）"

            extra_context = ""
            if merged_snippet:
                extra_context = (
                    "【报告写作上下文（来自章节正文，可能包含主观判断）】\n"
                    + merged_snippet
                )

            try:
                fc = self._get_forecast_agent().generate_forecast(
                    str(ticker),
                    related_signals,
                    pred_len=int(pred_len),
                    extra_context=extra_context
                )
                if fc:
                    forecasts[key] = fc
            except Exception as e:
                logger.warning(f"⚠️ Forecast generation failed for {ticker} pred_len={pred_len}: {e}")

        return forecasts

    @staticmethod
    def _sanitize_json_chart_blocks(text: str) -> str:
        """Best-effort repair for malformed json-chart fenced blocks.

        Common failure mode: model outputs an opening ```json-chart but forgets to close it.
        That causes downstream chart processing to miss it and swallows the rest of the report.

        Strategy:
        - For each opening fence, locate the first JSON object and close the fence right after
          the JSON object (balanced braces, ignoring braces inside strings).
        - If a closing fence already exists after the JSON object, leave as-is.
        """

        if not text:
            return text

        # Phase 0: Normalize malformed json-chart fences.
        # We only touch fences in/around json-chart blocks to avoid modifying other markdown.
        if "json-chart" in text:
            lines = text.splitlines()
            out_lines: list[str] = []
            in_chart = False
            i = 0
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()

                if not in_chart:
                    # Opening fence variants
                    if stripped in ("```json-chart", "``json-chart", "``` json-chart", "`` json-chart"):
                        out_lines.append("```json-chart")
                        in_chart = True
                        i += 1
                        continue

                    # Variant: opening fence on its own line, language on next line.
                    #   ```
                    #   json-chart
                    #   { ... }
                    if stripped in ("```", "``") and i + 1 < len(lines) and lines[i + 1].strip() == "json-chart":
                        out_lines.append("```json-chart")
                        in_chart = True
                        i += 2
                        continue

                    # Variant: opening fence appears at end of a content line.
                    #   ...：   ```
                    #   json-chart
                    if stripped.endswith("```") and not stripped.startswith("```"):
                        if i + 1 < len(lines) and lines[i + 1].strip() == "json-chart":
                            prefix = line[: line.rfind("```")].rstrip()
                            if prefix:
                                out_lines.append(prefix)
                            out_lines.append("```json-chart")
                            in_chart = True
                            i += 2
                            continue

                else:
                    # Closing fence variants
                    if stripped in ("```", "``"):
                        out_lines.append("```")
                        in_chart = False
                        i += 1
                        continue

                    # Variant: closing fence appears on the same line after JSON.
                    #   { ... } ```
                    if "```" in line:
                        pos = line.find("```")
                        before = line[:pos].rstrip()
                        after = line[pos + 3 :].strip()
                        if before:
                            out_lines.append(before)
                        out_lines.append("```")
                        in_chart = False
                        if after:
                            out_lines.append(after)
                        i += 1
                        continue

                out_lines.append(line)
                i += 1

            text = "\n".join(out_lines)

        def find_json_end(s: str, start_idx: int) -> Optional[int]:
            # find first '{'
            i = s.find('{', start_idx)
            if i == -1:
                return None
            depth = 0
            in_str = False
            escape = False
            quote = '"'
            for j in range(i, len(s)):
                ch = s[j]
                if in_str:
                    if escape:
                        escape = False
                        continue
                    if ch == '\\':
                        escape = True
                        continue
                    if ch == quote:
                        in_str = False
                    continue

                if ch == '"' or ch == "'":
                    in_str = True
                    quote = ch
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return j
            return None

        # Phase 1: Repair missing closing fences for properly-opened blocks.
        if "```json-chart" not in text:
            return text

        out = []
        i = 0
        needle = "```json-chart"
        while True:
            idx = text.find(needle, i)
            if idx == -1:
                out.append(text[i:])
                break

            # append preceding text
            out.append(text[i:idx])

            # keep the opening fence line
            fence_line_end = text.find("\n", idx)
            if fence_line_end == -1:
                out.append(text[idx:])
                break
            fence_line_end += 1
            out.append(text[idx:fence_line_end])

            # attempt to find end of JSON object
            json_end = find_json_end(text, fence_line_end)
            if json_end is None:
                # cannot repair; keep rest and stop
                out.append(text[fence_line_end:])
                break

            # include JSON object (up to closing brace)
            out.append(text[fence_line_end:json_end + 1])

            # check if there's already a closing fence soon after
            after_json = text[json_end + 1:]
            closing_idx = after_json.find("```")
            opening_idx2 = after_json.find(needle)

            if closing_idx != -1 and (opening_idx2 == -1 or closing_idx < opening_idx2):
                # existing closing fence; keep everything up to it as-is
                out.append(after_json[:closing_idx + 3])
                i = json_end + 1 + closing_idx + 3
                continue

            # missing closing fence: insert one
            out.append("\n```\n")
            i = json_end + 1

        return "".join(out)

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
        """构建结构化研报输出（便于前端渲染）"""
        text = (report_md or "").strip()
        lines = text.splitlines() if text else []

        # 标题
        title = "研报"
        for line in lines:
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break

        # 章节解析
        sections: List[Dict[str, Any]] = []
        current: Dict[str, Any] | None = None
        for line in lines:
            heading = re.match(r"^(#{2,4})\s+(.*)$", line.strip())
            if heading:
                if current:
                    sections.append(current)
                current = {"title": heading.group(2).strip(), "content": []}
                continue
            if current is None:
                current = {"title": "摘要", "content": []}
            current["content"].append(line)
        if current:
            sections.append(current)

        # 摘要要点
        bullets = [
            re.sub(r"^[-*•]\s+", "", l.strip())
            for l in lines
            if l.strip().startswith(("- ", "* ", "• "))
        ]
        bullets = [b for b in bullets if b]

        # 信号映射
        signal_map = {}
        for i, s in enumerate(signals, 1):
            title_s = s.title if hasattr(s, "title") else s.get("title", "")
            signal_map[i] = {
                "id": i,
                "title": title_s,
                "summary": getattr(s, "summary", "") if not isinstance(s, dict) else s.get("summary", ""),
                "sentiment_score": getattr(s, "sentiment_score", None) if not isinstance(s, dict) else s.get("sentiment_score"),
                "confidence": getattr(s, "confidence", None) if not isinstance(s, dict) else s.get("confidence"),
                "intensity": getattr(s, "intensity", None) if not isinstance(s, dict) else s.get("intensity"),
                "impact_tickers": getattr(s, "impact_tickers", []) if not isinstance(s, dict) else s.get("impact_tickers", []),
                "expected_horizon": getattr(s, "expected_horizon", "") if not isinstance(s, dict) else s.get("expected_horizon", "")
            }

        # 聚类
        structured_clusters = []
        for c in clusters or []:
            ids = c.get("signal_ids", []) or []
            structured_clusters.append({
                "title": c.get("theme_title", ""),
                "rationale": c.get("rationale", ""),
                "signal_ids": ids,
                "signals": [signal_map.get(i) for i in ids if i in signal_map]
            })

        return {
            "title": title,
            "summary_bullets": bullets[:8],
            "sections": [
                {"title": s["title"], "content": "\n".join(s["content"]).strip()}
                for s in sections
            ],
            "clusters": structured_clusters,
            "signals": list(signal_map.values())
        }

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
            rationale = cluster.get("rationale", "")
            
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
            final_response_content = self._normalize_citations(final_response_content, signal_to_keys)
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
        """Helper to remove markdown code fences"""
        text = text.strip()
        if text.startswith("```markdown"):
            text = text[len("```markdown"):].strip()
        elif text.startswith("```"):
            text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        return text

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
                                            if best_match: break
                                    
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
