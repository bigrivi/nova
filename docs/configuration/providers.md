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

- `base_url` -- default is `http://localhost:11434`
- Models with `tools: true` can use Nova's built-in tools

### OpenAI-compatible (Cloud)

Works with OpenAI, DeepSeek, OpenRouter, Azure OpenAI, or any server exposing
an OpenAI-compatible chat completions API.

```json
{
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
{
  "providers": {
    "anthropic": {
      "type": "anthropic",
      "options": {
        "extra_body": { "thinking": { "type": "enabled", "budget_tokens": 4000 } }
      }
    }
  }
}
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
  "providers": {
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
}
```

## Custom Headers and Request Hook

`openai-compatible`, `openai-response`, and `anthropic` providers accept two
extra `options` for controlling HTTP headers:

- `headers` -- an object of static header name/value pairs sent with every
  provider request.
- `request_hook` -- path to a user Python script run before **every**
  request to supply dynamic headers. Use it when a header value must be
  computed per request (e.g. a fresh request id).
- `request_session_hook` -- same protocol, but runs **once per session**
  (result cached); use it for session-stable values (e.g. a session
  attestation id). When both hooks set the same header, `request_hook` wins.

Hook protocol: nova writes `{"session_id": ...}` as JSON to the script's
stdin; the script must print `{"headers": {...}}` as JSON to stdout and exit
0. Missing file, timeout (5s), nonzero exit, or bad JSON fails the request
with a clear error -- hooks are fail-closed and header values are never
logged. Relative paths resolve against `NOVA_HOME`. Scripts run with
`sys.executable` (the frozen desktop app re-executes itself), so no system
Python is required. Hook output is merged over static `headers`.

Example `~/.nova/hooks/request_headers.py` (stdlib only):

```python
import json
import sys
import uuid


def main():
    try:
        ctx = json.load(sys.stdin)
    except Exception:
        ctx = {}
    sys.stdout.write(json.dumps({"headers": {
        "x-request-id": uuid.uuid4().hex,
        "x-session-id": str(ctx.get("session_id") or ""),
    }}))


if __name__ == "__main__":
    main()
```

Note: the older `session_header` option has been removed; move its use to a
hook script as above.

These exist for gateways that require client identification or per-session
affinity. A gateway that asks every client to send a stable session id and
to identify itself:

```json
{
  "providers": {
    "example-gateway": {
      "type": "openai-compatible",
      "name": "Example Gateway",
      "options": {
        "base_url": "https://gateway.example.com/v1",
        "api_key": "sk-...",
        "user_agent": "nova/1.0",
        "headers": { "x-client-name": "nova/1.0" },
        "request_hook": "~/.nova/hooks/request_headers.py",
        "request_session_hook": "~/.nova/hooks/request_headers.py"
      },
      "models": {
        "example-model": { "name": "example-model", "tools": true }
      }
    }
  }
}
```

`user_agent` is a separate option that sets the `User-Agent` header directly.
Identify Nova with its own value rather than impersonating another client.

Both hook options take the same script shape; the difference is execution
frequency. `request_hook` runs before every request, so its output may vary
per call (e.g. the `x-request-id` above). `request_session_hook` runs once
per session and reuses the result, so its output must be session-stable
(e.g. the `x-session-id` above). Configure either or both; when both set the
same header, `request_hook` wins.

A provider's `type` fixes its endpoint: `openai-compatible` posts to
`/chat/completions`, `openai-response` to `/responses`, and `anthropic` to
`/messages`. A gateway that exposes models across several endpoints needs
one provider per endpoint, each carrying the same `headers` and hook options.

## Multiple Providers

You can define several providers under `providers`. There is no top-level
default-model key. Nova resolves the provider and model for each request in
this order:

1. Explicit `provider` and `model` fields on `POST /api/chat`
2. The session's agent config -- what `/models` in the TUI or the model
   selector in the web frontend writes
3. The first configured provider and its first model

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "options": { "base_url": "http://localhost:11434" },
      "models": { "gemma4:26b": { "name": "gemma4:26b", "tools": true } }
    },
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

Switch at runtime with `/models` in the TUI, the model selector in the web
frontend, or by starting the backend with
`nova serve --provider ollama --model gemma4:26b`.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `NOVA_HOME` | Override `~/.nova/` home directory |
| `NOVA_OLLAMA_BASE_URL` | Override Ollama base URL |
| `NOVA_OPENAI_BASE_URL` | Override OpenAI-compatible base URL |
| `NOVA_OPENAI_API_KEY` | Override API key |
| `OPENAI_API_KEY` | Fallback API key |
| `NOVA_FRONTEND_DIST` | Override the directory of the built frontend the server serves |

Server bind host, port, log level, and LAN auth live in the config file
`server` block, not in the environment. See [Settings](settings.md).
