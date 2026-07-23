"""Chart-rendering pipeline -- extract-report-agent-chart-renderer (Phase 4 step 29).

`process_charts` is `ReportAgent._process_charts`'s body (docs/refactor_program_plan.md,
step 29) moved verbatim out of `deepear/src/agents/report_agent.py`, including its
nested `replace_match` closure (and that closure's own nested `find_json_end`-style
inline logic, the raw sentiment SQL, the file-path construction under
`reports/charts/`, and the throwaway `Agent(...)` construction for the "transmission"
chart type's Draw.io XML generation).

`grep -n "self\\."` restricted to the original method's body finds six reads across
three distinct instance attributes: `self.db` (once, constructing the internal
`StockTools(self.db, auto_update=False)` collaborator, plus twice more for the
"sentiment" chart type's `self.db.execute_query(query, params)` calls -- the initial
query and the broadened-keyword fallback query), `self.tool_model` (once, as the
`model=` kwarg for the "transmission" chart type's throwaway Draw.io-XML-generation
`Agent(...)`), and `self._get_forecast_agent()` (twice: once in the "stock" chart
type's optional `show_forecast`/`forecast` flag path, once in the "forecast" chart
type's `forecast_map`-miss fallback path). Per ground rule 6, all three become
explicit parameters: `db` and `tool_model` as plain keyword-only values (there is no
lazy-cache semantics to preserve for either -- they are read straight off the
instance every time), and `get_forecast_agent` as a required keyword-only callable,
exactly mirroring `forecast_requests.py`'s `build_forecast_map(..., *,
get_forecast_agent)` precedent -- `_get_forecast_agent` itself is *not* moved; it
stays on `ReportAgent` as the lazy, per-instance `ForecastAgent`/Kronos-model cache
that `tests/report_agent_harness.py` patches around (by swapping the module-level
`ForecastAgent` class).

A fourth dependency needs threading even though it is not a `self.` read: the
"transmission" chart type constructs a throwaway `agno.agent.Agent(...)` purely to
generate Draw.io XML via an LLM call. In `report_agent.py`, that name resolves to
the module-level `Agent` import (`from agno.agent import Agent`), which is exactly
the seam `tests/report_agent_harness.py`'s `make_report_agent` monkeypatches
(`monkeypatch.setattr(report_agent_module, "Agent", <FakeAgent subclass>)`) so every
internal `Agent(...)` construction -- the four long-lived agents built in
`ReportAgent.__init__` and this one throwaway construction alike -- never makes a
real LLM call in tests. Moving the construction verbatim into this module would move
it out from under that patch (this module has its own, separate `Agent` name bound
at *this module's* import time, which `monkeypatch.setattr(report_agent_module,
"Agent", ...)` cannot reach). Per the plan's explicit instruction to prefer
injection over a second patch point, `process_charts` takes a required keyword-only
`agent_cls` parameter and calls `agent_cls(...)` exactly where the original body
called `Agent(...)`; `ReportAgent._process_charts` forwards `agent_cls=Agent` --
reading its own module's `Agent` global *at call time*, not at import time -- so the
harness's existing patch of `report_agent_module.Agent` is picked up by every call
without any change to the harness or any new patch point in this module.

The two lazy in-function imports -- `from utils.visualizer import VisualizerTools`
and `from utils.stock_tools import StockTools` -- move with their exact bare
spelling unchanged. They are resolved by `tests/conftest.py`'s
`_pin_ambiguous_package_resolution` session fixture (`utils` -> `deepear/src/utils`)
purely via `sys.path` order, which does not depend on which file performs the
import -- so the spelling is preserved character-for-character specifically so this
module's lazy imports keep resolving exactly like the original method's did, and so
the plan's regression coverage for that resolution keeps applying unchanged. The
"transmission" chart type's third lazy import, `from prompts.visualizer import
get_drawio_system_prompt, get_drawio_task`, is left with the same bare spelling for
the same reason (a single, unambiguous `deepear/src/prompts` on `sys.path`, so no
resolution-pin assertion exists for it, but nothing about moving files changes how
it resolves).

Monkeypatch audit (ground rule 2): `git grep -n "_process_charts\\|process_charts"
tests/ deepear/ backtest/ deepfund/ shared/` finds: the method definition and one
internal call site (`self._process_charts(...)` inside `generate_report`) in
`deepear/src/agents/report_agent.py`; `tests/report_agent_harness.py`'s docstring
mentioning `_process_charts` as one of the two `StockTools` collaborators
constructed with `auto_update=False` (no monkeypatch of the name itself);
`tests/test_report_chart_renderer.py` (new in this change) calling
`harness.agent._process_charts(...)` directly on a real instance. No literal
`monkeypatch.setattr("...")` string path and no class-attribute patch of the name
exists anywhere in the repo today. `ReportAgent` keeps a real `_process_charts`
bound instance method (a one-line delegator to this module's `process_charts`, not
a bare attribute alias) so a future `monkeypatch.setattr(ReportAgent,
"_process_charts", ...)` class-attribute patch would still intercept the internal
`self._process_charts(...)` call site inside `generate_report`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from loguru import logger

from deepear.src.schema.models import ForecastResult
from deepear.src.utils.json_utils import extract_json


def process_charts(
    content: str,
    signals: List[Dict[str, Any]] = None,
    forecast_map: Optional[Dict[tuple, ForecastResult]] = None,
    *,
    db: Any,
    tool_model: Any,
    get_forecast_agent: Callable[[], Any],
    agent_cls: Any,
) -> str:
    """解析 json-chart 代码块并替换为 HTML 链接/Iframe"""
    from utils.visualizer import VisualizerTools
    from utils.stock_tools import StockTools

    stock_tools = StockTools(db, auto_update=False)

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
                                forecast_obj = get_forecast_agent().generate_forecast(ticker, related_signals)
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
                    forecast_obj = get_forecast_agent().generate_forecast(ticker, related_signals, pred_len=pred_len)

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
                    results = db.execute_query(query, params)
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
                            results = db.execute_query(query, params)
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
                            visualizer_agent = agent_cls(
                                model=tool_model,
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
