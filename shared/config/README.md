# Shared Configuration

This directory contains the unified configuration system for the unified agent trading framework.

## Files

- **unified_config.yaml** - Template configuration file with all available settings
- **loader.py** - Configuration loader class with environment variable support
- **__init__.py** - Package exports

## Usage

### Basic Usage

```python
from shared.config import load_config

# Load configuration (automatically finds unified_config.yaml)
config = load_config()

# Get a configuration value
provider = config.get("llm.reasoning_model.provider", "openai")

# Get value with environment variable override
provider = config.get_with_env_override("llm.reasoning_model.provider")
```

### Component-Specific Configuration

```python
from shared.config import (
    get_llm_config,
    get_deepear_config,
    get_deepfund_config,
    get_data_source_config,
    get_database_config,
)

# Get LLM configuration
llm_config = get_llm_config()
reasoning_provider = llm_config["reasoning_model"]["provider"]
tool_model_id = llm_config["tool_model"]["model_id"]

# Get DeepEar configuration
deepear_config = get_deepear_config()
sources = deepear_config["sources"]

# Get DeepFund configuration
deepfund_config = get_deepfund_config()
personality = deepfund_config["personality"]

# Get data source configuration
tushare_config = get_data_source_config("tushare")
api_key = tushare_config.get("api_key")
```

### Environment Variables

The configuration system supports environment variable overrides for all key settings.

```bash
# Override LLM provider
export REASONING_MODEL_PROVIDER=openai
export REASONING_MODEL_ID=gpt-4o

# Override data source API keys
export TUSHARE_API_KEY=your_token_here
export ALPHA_VANTAGE_API_KEY=your_key_here
```

## Configuration Structure

### LLM Configuration

```yaml
llm:
  reasoning_model:
    provider: openrouter  # openai, ollama, deepseek, etc.
    model_id: gpt-4o
    host: ~
  tool_model:
    provider: ollama
    model_id: qwen3:latest
    host: http://127.0.0.1:11434
```

### Data Sources

```yaml
data_sources:
  tushare:
    enabled: true
    api_key_env: TUSHARE_API_KEY
  alpha_vantage:
    enabled: true
    api_key_env: ALPHA_VANTAGE_API_KEY
```

### DeepEar

```yaml
deepear:
  enabled: true
  sources:
    financial: [cailian, wallstreetcn, eastmoney]
    social: [weibo, xueqiu]
  isq_template: default_isq_v1
```

### DeepFund

```yaml
deepfund:
  enabled: true
  personality: balanced  # conservative, aggressive, passive, balanced
  max_position_ratio: 0.33
  workflow_analysts: [fundamental, technical, company_news]
```

## Profiles

You can define multiple configuration profiles in the YAML file:

```yaml
profiles:
  development:
    llm:
      tool_model:
        provider: ollama
        model_id: qwen3:latest

  production:
    llm:
      tool_model:
        provider: openai
        model_id: gpt-4o-mini
```

Load a specific profile:

```python
config = load_config(profile="production")
```

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `REASONING_MODEL_PROVIDER` | LLM provider for reasoning tasks | `openrouter` |
| `REASONING_MODEL_ID` | Model ID for reasoning | `gpt-4o` |
| `TOOL_MODEL_PROVIDER` | LLM provider for tool tasks | `ollama` |
| `TOOL_MODEL_ID` | Model ID for tools | `qwen3:latest` |
| `TUSHARE_API_KEY` | TuShare API token | - |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage API key | - |
| `JINA_API_KEY` | Jina AI API key | - |
| `SUPABASE_URL` | Supabase database URL | - |
| `SUPABASE_KEY` | Supabase API key | - |
