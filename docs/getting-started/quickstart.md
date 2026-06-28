# Quickstart

This guide gets you from zero to your first conversation in 5 minutes.

## Step 1: Set Up a Provider

Nova needs an LLM provider. The two options are:

- **Ollama** (local, free) -- run models on your own machine
- **OpenAI-compatible** (cloud) -- use OpenAI, DeepSeek, or any compatible API

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

## Step 2: Start Chatting

```bash
python -m nova
```

The CLI starts with your configured model. Type a message and press Enter.

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

Inside the CLI, type `/models` to see and switch between configured models.

## Next

- [CLI Commands](../cli/index.md) -- all available commands
- [Tool Overview](../tools/index.md) -- what Nova's tools can do
