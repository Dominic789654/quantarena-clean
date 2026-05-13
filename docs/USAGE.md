# 使用指南

## 运行方式

### 直接运行（推荐）

```bash
# 激活虚拟环境
source .venv_unified/bin/activate

# 查看帮助
python run.py --help
```

### 运行 DeepEar（情报收集）

```bash
# 分析 A股科技板块
./run_venv.sh --mode deepear --query "A股科技股" --sources financial

# 增加每个来源的新闻数量
./run_venv.sh --mode deepear --query "半导体行业" --sources all --wide 20

# 从断点恢复
./run_venv.sh --mode deepear --resume
```

### 运行 DeepFund（交易分析）

```bash
# 分析指定日期的 A股
./run_venv.sh --mode deepfund --market cn --date 2024-01-15

# 使用自定义配置
./run_venv.sh --mode deepfund --config deepfund/src/config/exp/ashare.yaml --date 2024-01-15

# 美股分析（本地数据库）
./run_venv.sh --mode deepfund --market us --date 2024-01-15 --local-db
```

### 运行完整流程

```bash
# A股市场完整工作流
./run_venv.sh --mode full --market cn --date 2024-01-15

# 跳过 DeepEar 阶段，仅运行交易分析
./run_venv.sh --mode full --market cn --date 2024-01-15 --skip-deepear

# 遇到错误继续执行
./run_venv.sh --mode full --market us --date 2024-01-15 --continue-on-error
```

### 运行回测（历史模拟）

```bash
# 简单回测（无LLM，快速验证）
./run_venv.sh --mode backtest --tickers "600519,000858" \
    --start-date 2024-01-01 --end-date 2024-01-31

# LLM 智能回测（多分析师决策）
./run_venv.sh --mode backtest --tickers "600519" \
    --start-date 2024-01-01 --end-date 2024-01-31 \
    --use-llm --analysts "fundamental,technical,company_news" \
    --personality "balanced"

# FOF 元策略回测（聚合多个人格 sleeve）
./run_venv.sh --mode backtest --tickers "600519,000858,300750" \
    --start-date 2024-01-01 --end-date 2024-03-31 \
    --use-llm --analysts "fundamental,technical,company_news" \
    --personality "fof"

# 使用 FOF 配置文件直接运行（自动读取 sleeves / analysts / cashflow）
./run_venv.sh --mode backtest \
    --config deepfund/src/config/fof.yaml \
    --start-date 2024-01-01 --end-date 2024-03-31 \
    --personality "fof"

# 完整集成回测（DeepEar + DeepFund）
./run_venv.sh --mode backtest --tickers "600519" \
    --start-date 2024-01-01 --end-date 2024-01-31 \
    --use-llm --analysts "fundamental,technical,deepear_intelligence" \
    --personality "balanced"
```

**多人格并行回测（同时比较多种投资策略）**

```bash
# 5种人格并行回测，10只股票，半年期
./run_venv.sh --mode multi-personality \
    --tickers "600519,000858,601318,300750,600036,000333,000651,600276,600900,601888" \
    --start-date 2025-08-01 --end-date 2026-01-31 \
    --use-llm \
    --analysts "fundamental,technical,company_news" \
    --personalities "conservative,balanced,aggressive,passive,ewi" \
    --max-workers 5 \
    --cashflow 100000
```

**可用人格:**
- `conservative` - 保守型
- `balanced` - 平衡型
- `aggressive` - 激进型
- `passive` - 被动型
- `ewi` - 等权指数
- `fof` - 母基金式多人格聚合
- FOF 回测报告会额外导出 sleeve 归因、sleeve 内部持仓拆解，以及聚合目标权重
- FOF 配置支持最小再平衡阈值，用于抑制小权重漂移导致的噪音换手
- FOF 还支持按 bear/volatile 与低共识状态放大再平衡阈值，不增加额外 LLM 调用

## CLI 选项

### 全局选项

| 选项 | 说明 |
|------|------|
| `--mode` | 执行模式: deepear, deepfund, full, backtest, multi-personality |
| `--log-level` | 日志级别: DEBUG, INFO, WARNING, ERROR |
| `--check-env` | 检查环境并退出 |

### DeepEar 选项

| 选项 | 说明 |
|------|------|
| `--query` | 用户查询/意图 |
| `--sources` | 新闻来源: all, financial, social, tech |
| `--wide` | 每个来源抓取的新闻数量 |
| `--depth` | 报告深度: auto 或整数 |
| `--resume` | 从断点恢复 |

### DeepFund 选项

| 选项 | 说明 |
|------|------|
| `--market` | 市场: cn (A股), us (美股) |
| `--date` | 交易日期 (YYYY-MM-DD) |
| `--config` | 配置文件路径 |
| `--local-db` | 使用本地 SQLite 数据库 |

### 回测选项

| 选项 | 说明 |
|------|------|
| `--tickers` | 股票代码，逗号分隔 |
| `--start-date` | 开始日期 (YYYY-MM-DD) |
| `--end-date` | 结束日期 (YYYY-MM-DD) |
| `--cashflow` | 初始资金 |
| `--use-llm` | 启用 LLM 决策 |
| `--analysts` | 分析师列表 |
| `--personality` | 投资性格 |
| `--personalities` | 多人格模式的人格列表 |
| `--max-workers` | 并行工作进程数 |

## 输出文件

运行结果保存在以下目录：

- `reports/` - 生成的报告
- `logs/` - 日志文件
- `data/` - 数据库文件
- `reports/checkpoints/` - 断点文件
