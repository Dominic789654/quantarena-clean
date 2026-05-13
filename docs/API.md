# 数据源和 API

## 新闻来源（DeepEar）

### 财经新闻
- **财联社 (cls)** - 实时财经快讯
- **华尔街见闻 (wallstreetcn)** - 全球金融市场
- **东方财富 (eastmoney)** - A股资讯

### 社交媒体
- **微博 (weibo)** - 社交媒体热点
- **雪球 (xueqiu)** - 投资者社区
- **知乎 (zhihu)** - 深度讨论

### 科技资讯
- **36氪 (36kr)** - 科技创业
- **IT之家 (ithome)** - IT新闻
- **掘金 (juejin)** - 技术社区

## 搜索引擎（DeepEar）

| 引擎 | 特点 | 配置 |
|------|------|------|
| **Tavily** | AI 优化搜索（推荐） | 需 `TAVILY_API_KEY` |
| **Jina AI** | LLM 友好输出 | 需 `JINA_API_KEY` |
| **DuckDuckGo** | 免费，国际搜索 | 无需 API Key |
| **Baidu** | 免费，中文搜索 | 无需 API Key |

## 行情数据（DeepFund）

### A股数据
- **TuShare** - 主要数据源
  - 注册: https://tushare.pro/register
  - 免费版有调用限制
  - Pro 版需要积分

### 美股数据
- **Alpha Vantage** - 免费版每日 25 次限制
- **YFinance** - 免费，通过雅虎财经

### 国际数据
- **FinancialDataset** - 国际金融市场数据

## API 使用示例

### TuShare A股数据

```python
import tushare as ts

pro = ts.pro_api('your-token')

# 获取日线数据
df = pro.daily(ts_code='600519.SH', start_date='20240101', end_date='20240131')

# 获取股票列表
stocks = pro.stock_basic(exchange='', list_status='L')
```

### Alpha Vantage 美股数据

```python
from alpha_vantage.timeseries import TimeSeries

ts = TimeSeries(key='your-api-key')
data, meta_data = ts.get_daily('AAPL')
```

## API 限制说明

| 数据源 | 免费限制 | 付费选项 |
|--------|----------|----------|
| TuShare | 5000积分/天 | Pro 会员 |
| Alpha Vantage | 25次/天 | 付费套餐 |
| Tavily | 1000次/月 | 付费套餐 |
| Jina AI | 免费额度 | 按量付费 |

## 错误处理

当 API 限流或失败时，系统会：
1. 自动重试（带指数退避）
2. 降级到备用数据源
3. 记录错误日志
4. 返回友好的错误提示

示例：
```
⚠️ Alpha Vantage API 限流，自动降级到 YFinance
```
