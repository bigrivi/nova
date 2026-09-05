# Quickstart

This guide gets you from zero to your first conversation in 5 minutes.

## Step 1: Set Up a Provider

Nova needs an LLM provider. Supported provider types are `ollama`, `anthropic`,
`openai-compatible`, and `openai-response`:

- **Ollama** (local, free) -- run models on your own machine
- **Anthropic** (cloud) -- use Claude via the Anthropic Messages API
- **OpenAI-compatible** (cloud) -- use OpenAI, DeepSeek, or any compatible API
- **OpenAI Response** (cloud) -- use the OpenAI Responses API

### Option A: Ollama

[Install Ollama](https://ollama.com) on your machine, then pull a model:

```bash
ollama pull gemma4:26b
```

Create or edit `~/.nova/config.json`:

```json
{
  "model": "gemma4:26b",
  "model_provider": "ollama",
  "providers": {
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
}
```

### Option B: OpenAI-compatible

```json
{
  "model": "gpt-4o",
  "model_provider": "openai",
  "providers": {
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
}
```

### Option C: Anthropic

```json
{
  "model": "claude-sonnet-4-5",
  "model_provider": "anthropic",
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

Anthropic talks to `POST /v1/messages` directly. `base_url` defaults to
`https://api.anthropic.com` and may end in `/v1`. `api_key` is sent as
`x-api-key`. `anthropic_version` defaults to `2023-06-01` and `betas` is joined
into the `anthropic-beta` header. `extra_body` follows the same flattening and
deep-merge rules as the other providers.

The API requires `max_tokens` on every request. Nova sets a per-model default;
override it with `extra_body.max_tokens` at the provider or model level. To
enable extended thinking, set `extra_body.thinking` to
`{ "type": "enabled", "budget_tokens": 4000 }`. Thinking text appears as Nova's
reasoning stream.

## Step 2: Start Chatting

```bash
./nova-tui
```

The TUI (requires [bun](https://bun.sh)) starts with your configured model.
Type a message and press Enter.

## Step 3: Try Things

```bash
# Ask a question
What files are in the current directory?

# Run shell commands
Run ls -la to list files in the current directory

# Write a file
Write a Python script that calculates fibonacci numbers
```

## Step 4: Switch Models (Optional)

Inside the TUI, type `/models` to see and switch between configured models.

## Next

- [TUI Commands](../tui/index.md) -- all available commands
- [Tool Overview](../tools/index.md) -- what Nova's tools can do
