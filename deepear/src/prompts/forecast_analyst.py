from typing import List
from deepear.src.schema.models import KLinePoint

def get_forecast_adjustment_instructions(ticker: str, news_context: str, model_forecast: List[KLinePoint]):
    """
    生成 LLM 预测调整指令
    """
    forecast_str = "\n".join([f"- {p.date}: O:{p.open}, C:{p.close}" for p in model_forecast])

    return f"""你是一位资深的量化策略分析师。
你的任务是：根据给定的【Kronos 模型预测结果】和【最新的基本面/新闻背景】，对模型预测进行"主观/逻辑调整"。

股票代码: {ticker}

【Kronos 模型原始预测 (OHLC)】:
{forecast_str}

【最新情报背景】:
{news_context}

调整原则:
1. 原始预测是基于历史的技术面推演。
2. 情报背景中可能包含【Kronos模型定量修正预测】，这是基于历史新闻训练的专用模型计算出的量化结果。
3. 如果存在"定量修正预测"，请**高度参考**该数值作为基础，除非你有非常确凿的逻辑认为该量化模型失效（例如遇到模型未见过的极端黑天鹅）。
4. 你的核心任务是：结合定性分析（新闻及其逻辑）来验证或微调这些数字，并给出合理的解释（Rationale）。
5. 如果没有"定量修正预测"，则你需要根据新闻信号手动大幅调整趋势。

输出要求 (严格 JSON 格式):
```json
{{
  "adjusted_forecast": [
    {{
      "date": "YYYY-MM-DD",
      "open": float,
      "high": float,
      "low": float,
      "close": float,
      "volume": float
    }},
    ...
  ],
  "rationale": "详细说明调整的逻辑依据，例如：考虑到[事件A]，预期短线将突破压力位..."
}}
```
注意：必须输出与原始预测相同数量的数据点，且日期一一对应。
"""

def get_forecast_task():
    return "请根据以上背景和模型预测，给出调整后的 K 线数据并说明理由。"


def get_llm_forecast_instructions(
    ticker: str,
    historical_data: str,
    signals_context: str,
    pred_len: int = 5,
    current_price: float = None
) -> str:
    """
    生成纯 LLM 预测指令（不依赖 Kronos 模型）

    Args:
        ticker: 股票代码
        historical_data: 历史 K 线数据字符串
        signals_context: 相关新闻信号上下文
        pred_len: 预测天数
        current_price: 当前价格
    """
    return f"""你是一位资深的量化分析师和交易员，拥有超过 15 年的 A 股市场经验。
你的任务是：基于历史价格走势、技术指标、基本面信号和市场情绪，预测股票未来 {pred_len} 个交易日的走势。

## 股票信息
- **代码**: {ticker}
- **当前价格**: {current_price or "未知"}

## 历史 K 线数据（最近 20 个交易日）
```
{historical_data}
```

## 相关投资信号与新闻
{signals_context if signals_context else "暂无明确信号"}

---

## 分析框架

请按照以下步骤进行系统分析：

### 1. 技术面分析
- **趋势判断**: 当前是上涨、下跌还是震荡趋势？
- **支撑位**: 下方关键支撑价格及强度
- **阻力位**: 上方关键阻力价格及强度
- **量价关系**: 成交量是否配合价格变动
- **技术形态**: 是否出现突破、反转、整理形态

### 2. 基本面与消息面分析
- 评估信号中提到的利好/利空因素
- 判断消息的影响周期（短期情绪/中期业绩/长期逻辑）
- 识别潜在的风险点和催化剂

### 3. 市场情绪评估
- 当前市场对该板块/个股的关注度
- 资金流向特征（流入/流出/观望）
- 整体市场风险偏好

### 4. 概率情景分析
- **乐观情景 (30%)**: 最好情况下的走势
- **基准情景 (50%)**: 最可能发生的走势
- **悲观情景 (20%)**: 最差情况下的走势

---

## 输出要求

请输出严格的 JSON 格式，包含以下字段：

```json
{{
  "analysis": {{
    "trend": "上涨/下跌/震荡",
    "trend_strength": 0.0-1.0,
    "support_level": 支撑价位,
    "resistance_level": 阻力价位,
    "key_factors": ["关键因素1", "关键因素2", "..."]
  }},
  "scenarios": {{
    "optimistic": {{
      "description": "乐观情景描述",
      "probability": 0.30,
      "target_price": 目标价
    }},
    "baseline": {{
      "description": "基准情景描述",
      "probability": 0.50,
      "target_price": 目标价
    }},
    "pessimistic": {{
      "description": "悲观情景描述",
      "probability": 0.20,
      "target_price": 目标价
    }}
  }},
  "forecast": [
    {{
      "date": "YYYY-MM-DD",
      "open": 开盘价,
      "high": 最高价,
      "low": 最低价,
      "close": 收盘价,
      "volume": 预估成交量,
      "confidence": 0.0-1.0
    }}
  ],
  "rationale": "详细说明预测逻辑，包括技术面、基本面、情绪面的综合考量，以及主要风险提示"
}}
```

**注意**: forecast 数组需要包含 {pred_len} 条数据。

## 重要约束

1. **价格合理性**:
   - 每日涨跌幅不超过 ±10%（主板）或 ±20%（创业板/科创板）
   - high >= max(open, close), low <= min(open, close)
   - 价格变动应平滑，避免跳空

2. **日期连续性**:
   - 只输出交易日，跳过周末
   - 日期格式: YYYY-MM-DD

3. **置信度**:
   - confidence 表示对当天预测的确信程度
   - 通常越远的日期 confidence 越低

4. **逻辑一致性**:
   - forecast 走势应与 analysis.trend 一致
   - 目标价应与 forecast 最终价格相近

请基于以上框架，给出专业、严谨的预测分析。
"""


def get_llm_forecast_task():
    return "请基于历史数据和相关信号，按照 JSON 格式输出未来走势预测。"
