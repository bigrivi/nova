# Providers & Models

Nova supports four LLM provider types: **ollama** for local models,
**anthropic** for the Anthropic Messages API (`POST /v1/messages`),
**openai-compatible** for cloud APIs and locally-hosted OpenAI-compatible
servers, and **openai-response** for the OpenAI Responses API.

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

### Anthropic

Talks to the Anthropic Messages API (`POST /v1/messages`) directly over HTTP.
No vendor SDK and no OpenAI compatibility shim.

```json
{
  "providers": {
    "anthropic": {
      "type": "anthropic",
      "name": "Anthropic",
      "options": {
        "base_url": "https://api.anthropic.com",
        "api_key": "sk-ant-...",
        "anthropic_version": "2023-06-01",
        "betas": []
      },
      "models": {
        "claude-sonnet-4-5": {
          "name": "claude-sonnet-4-5",
          "tools": true
        }
      }
    }
  }
}
```

- `base_url` -- optional, defaults to `https://api.anthropic.com`. A URL that
  already ends in `/v1` is accepted and not doubled, so an Anthropic-compatible
  gateway can be pointed at directly.
- `api_key` -- sent as the `x-api-key` header. Anthropic does not use
  `Authorization: Bearer`.
- `anthropic_version` -- optional, defaults to `2023-06-01`. Sent as the
  `anthropic-version` header.
- `betas` -- optional list of strings, joined into the `anthropic-beta` header.
- `extra_body` -- same semantics as the other providers: flattened into the
  outgoing request body, model-level entries overriding provider-level ones.
  See Config rules in the project README for deep-merge precedence.

The Anthropic API requires `max_tokens` on every request. Nova picks a per-model
default and you can override it with `extra_body.max_tokens` at either the
provider or model level.

Extended thinking is enabled through `extra_body`:

```json
"extra_body": { "thinking": { "type": "enabled", "budget_tokens": 4000 } }
```

Thinking text surfaces as Nova's reasoning stream, the same as
`reasoning_content` on OpenAI-compatible providers.

Extended thinking with tool calling relies on Anthropic thinking-block
signatures. Each `thinking` block comes with a cryptographic `signature`
and the API requires the latest assistant turn's block back unmodified
whenever tools are in play. Nova stores the thinking text in
`reasoning_content` and the signature in the internal `provider_meta`
field on the message, recombining them on the next request. The signature
covers the text so the text is stored once. Existing databases pick up
the storage on next launch with no manual migration or config change.

Nova skips replaying the block when it would be rejected and degrades
gracefully:

- extended thinking is not enabled for the request
- the message was produced by a different model -- signatures are
  model-scoped, so switching models mid-session drops reasoning continuity
  for that turn instead of erroring
- only the latest assistant turn that carries a thinking block is replayed
  -- Anthropic requires that one, and each extra block would be billed as
  input tokens and consume context window on models that retain prior
  turns. Whether prior-turn thinking counts against the window is
  model-dependent -- some models strip it automatically, others retain and
  bill it -- so replaying only the last turn bounds the cost either way.

### OpenAI Response

Uses the OpenAI Responses API via `nova/llm/openai_response.py`. Provider
options are `base_url`, `api_key`, and `user_agent`.

```json
{
  "openai-responses": {
    "type": "openai-response",
    "name": "OpenAI Responses",
    "options": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-..."
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
