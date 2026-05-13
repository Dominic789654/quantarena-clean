# 安装指南

详细的安装和配置说明。

## 前置要求

- Python 3.11+
- pip 或 uv 包管理器
- LLM 提供商和数据源的 API Keys

## 安装步骤

### 1. 进入项目目录

```bash
cd /path/to/quantarena
```

### 2. 创建虚拟环境

```bash
# 创建新环境（推荐）
python -m venv .venv_unified
source .venv_unified/bin/activate

# 或使用项目提供的旧环境
source .venv_unified/bin/activate
```

### 3. 安装依赖

```bash
# 安装默认运行依赖（推荐，支持 CLI、provider smoke、report 和普通回测）
pip install -e .

# 可选：安装开发依赖
pip install -e ".[dev]"

# 可选：安装预测/embedding 实验依赖（会安装 torch/transformers）
pip install -e ".[ml]"

# 可选：安装全部开发和 ML 依赖
pip install -e ".[full]"
```

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Keys
```

**必需的 API Keys:**

| API | 获取地址 | 用途 |
|-----|----------|------|
| **Tushare** | https://tushare.pro/register | A股数据 |
| **LLM Provider** | 火山引擎/DeepSeek/OpenAI 等 | 智能分析 |

**可选 API Keys:**
- **Alpha Vantage** (美股): https://www.alphavantage.co/
- **Tavily** (AI搜索): https://tavily.com/
- **Jina AI** (搜索提取): https://jina.ai/

### 5. 验证环境

```bash
# 简单回测（无LLM，验证数据API）
python run.py --mode backtest --tickers "600519" --start-date 2026-01-05 --end-date 2026-01-08

# LLM智能回测（验证LLM API）
python run.py --mode backtest --tickers "600519" --start-date 2026-01-05 --end-date 2026-01-08 --use-llm --analysts "fundamental"
```

## 配置验证

启动时会自动验证必需的环境变量：

```bash
$ python run.py --mode deepfund
✅ All environment variables validated successfully
```

如果缺少必需变量，会提示：

```
❌ Missing required environment variables:
  • REASONING_MODEL_PROVIDER: LLM provider for reasoning model
  • REASONING_MODEL_ID: Model ID for reasoning

================================================================
Quick Fix:
  1. cp .env.example .env
  2. Edit .env and fill in your API keys
  3. Run again
================================================================
```

## 常见问题

| 问题 | 解决 |
|------|------|
| `ModuleNotFoundError` | 确保激活虚拟环境: `source .venv_unified/bin/activate` |
| `No columns to parse from file` | 数据API可能返回空数据，检查 API Key 是否有效 |
| `'xxx' is not a valid Provider` | Provider 值需要首字母大写，如 `Ark`, `DeepSeek` |
| `API Key Error` | 检查 `.env` 文件中的 API Key 是否设置 |

## 下一步

- 查看 [基本用法](USAGE.md)
- 查看 [配置选项](../.env.example)
- 查看 [常见问题](../README.md)
