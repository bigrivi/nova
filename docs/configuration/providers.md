# Providers & Models

Nova supports two LLM provider types: **Ollama** for local models and
**openai-compatible** for cloud APIs and locally-hosted OpenAI-compatible
servers.

## Configuration File

The config file lives at `~/.nova/config.json`.

## Provider Types

### Ollama (Local)

[Ollama](https://ollama.com) runs models on your own machine. No data leaves
your computer.

```json
{
  "ollama": {
    "type": "ollama",
    "name": "Ollama (local)",
    "options": {
      "base_url": "http://localhost:11434"
    },
    "models": {
      "gemma4:26b": {
        "name": "gemma4:26b",
        "tools": true
      }
    }
  }
}
```

- `base_url` -- default is `http://localhost:11434`
- Models with `tools: true` can use Nova's built-in tools

### OpenAI-compatible (Cloud)

Works with OpenAI, DeepSeek, OpenRouter, Azure OpenAI, or any server exposing
an OpenAI-compatible chat completions API.

```json
{
  "openai": {
    "type": "openai-compatible",
    "name": "OpenAI",
    "options": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-your-key-here"
    },
    "models": {
      "gpt-4o": {
        "name": "gpt-4o",
        "tools": true
      }
    }
  }
}
```

## Multiple Providers

You can define several providers and switch between them at runtime:

```json
{
  "model": "gemma4:26b",
  "model_provider": "ollama",
  "providers": {
    "ollama": { ... },
    "openai": { ... },
    "deepseek": {
      "type": "openai-compatible",
      "name": "DeepSeek",
      "options": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-..."
      },
      "models": {
        "deepseek-chat": {
          "name": "deepseek-chat",
          "tools": true
        }
      }
    }
  }
}
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `NOVA_HOME` | Override `~/.nova/` home directory |
| `NOVA_OLLAMA_BASE_URL` | Override Ollama base URL |
| `NOVA_OPENAI_BASE_URL` | Override OpenAI-compatible base URL |
| `NOVA_OPENAI_API_KEY` | Override API key |
| `OPENAI_API_KEY` | Fallback API key |
| `NOVA_LOG_LEVEL` | Log level (default: INFO) |
| `NOVA_HOST` | Server bind host (default: 127.0.0.1) |
| `NOVA_BACKEND_PORT` | Server port (default: 8765) |

## CLI Overrides

Override provider and model for a single session:

```bash
python -m nova cli --provider ollama --model gemma4:26b
```
