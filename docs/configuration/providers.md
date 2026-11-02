# Providers & Models

Nova supports four LLM provider types: **ollama** for local models,
**anthropic** for the Anthropic Messages API (`POST /v1/messages`),
**openai-compatible** for cloud APIs and locally-hosted OpenAI-compatible
servers, and **openai-response** for the OpenAI Responses API.

## Configuration File

The config file lives at `~/.nova/config.json`.

## Presets

Connecting a provider should not mean knowing its base URL. The form offers 216
vendors, each with its base URL, wire type, and key environment variable already
filled in, so only the API key and the model name are left.

Almost all of them are **derived from [models.dev](https://models.dev)** on the
same daily fetch that supplies each model's spec. That fetch runs once per server start
(any surface: `nova serve`, `web`, `desktop`) and again when a TUI launches, so a
backend that has been up for days still picks up a new vendor.

The derived rows live **in memory only**. `$NOVA_HOME/provider_presets.cache.json`
holds exactly the providers you connected — one row each, written when the
connection is saved — so a restart with no network still resolves what you use,
and nothing is written for the hundreds of vendors you never touched. A provider is offered when the
catalogue states a base URL; its wire comes from the SDK package the catalogue
assigns (`@ai-sdk/anthropic` is Anthropic Messages, everything else is OpenAI
Chat Completions). Adding a vendor therefore needs neither a release nor a row
in this repository.

Eight rows stay bundled, in `nova/registry/presets.json`, because nothing else
can supply them:

- the local runtimes — Ollama, LM Studio, vLLM, SGLang — which no public
  catalogue lists;
- OpenAI and Anthropic, whose base URL models.dev omits because their SDK
  hardcodes it;
- OpenCode Go and OpenCode Zen, where the catalogue's URL answers 404 and the
  working one is pinned.

A bundled row always wins over a derived one. That is the whole point of the
floor: a catalogue is a snapshot, and a URL checked against the vendor outranks
one that was merely published.

A preset is a convenience, not a restriction. Every field it fills stays editable,
and `GET /api/providers/presets` returns the same list for anything that wants to
drive the form itself. `POST /api/registry/refresh` re-fetches models.dev on
demand; the TUI does it once per launch, at most daily.

## Overriding a preset

A config entry states its own transport: `type`, and `base_url` for anything
OpenAI-compatible. Presets fill the connect form and stand in for a key that has
no entry at all — they are never merged into an entry that exists, because what a
file means should not depend on a cache that a fresh install may not have yet.

So an override carries the three lines it inherits nothing from:

```json
{
  "providers": {
    "opencode-go": {
      "type": "openai-compatible",
      "name": "OpenCode Go",
      "options": {
        "base_url": "https://opencode.ai/zen/go/v1",
        "request_session_hook": "~/.nova/hooks/session_headers.py"
      }
    }
  }
}
```

The key itself stays in `credentials.json`. A provider that still has a stored key
stays "authenticated" for `/connect` and the startup refresh, whether or not it
also has an entry here.

Anthropic and Ollama entries may omit `base_url`: their adapters default to the
vendor's own endpoint. Everything else must name one — that is the only way a
config is readable without knowing which presets happen to be cached.

### What connecting checks

Connecting asks the provider for its model list before anything is written, so a
key it rejects fails the whole action: nothing lands in `credentials.json` and no
provider appears. That is the one answer that is evidence about the key itself.

Everything else still saves, with a warning instead: a host that cannot be
reached (a local runtime may simply be off), an endpoint that does not implement
`/models`, or a catalogue that comes back empty. None of those say the key is
wrong, and refusing to save on them would make an offline setup impossible to
configure.

### Custom endpoints

An endpoint you declare yourself is not a vendor as far as Nova is concerned, so
it is treated differently in three ways:

- **No probe on connect, and no model list to read.** Nothing promised that
  endpoint serves `/models`, so connecting it does not depend on one. Its key is
  stored in `credentials.json` like any other, but the list of models is
  something you write under `providers.<key>.models` — the same way you would
  declare a model the vendor's catalogue does not know about.
- **No refresh.** The startup sync and the per-provider refresh both skip it;
  asking again would replace a declaration with whatever the endpoint happens to
  advertise today. `/api/config/providers/<key>/sync-models` answers `400` with
  that reason.
- **It shows up in `/connect` with `custom: true`**, so the form asks for a base
  URL rather than filling one in, and re-keying it only asks for the key.

The marker is `"custom": true` in the entry, written when you connect from the
form. A hand-written entry without it is treated as an ordinary provider.

### Per-provider request shaping

| Key (`options.*`) | Effect |
|---|---|
| `headers` | static headers on every request |
| `request_hook` | script run before every request; its headers are merged in |
| `request_session_hook` | same, run once per session and cached |
| `extra_body` | fields deep-merged into every request body |
| `user_agent` | the identity sent to this provider, when Nova's own is refused |

A hook receives `{"session_id": …}` on stdin and must print `{"headers": {…}}`
with exit 0. A failing hook fails the request rather than sending it unmodified.

### Per-model

```json
"models": {
  "beam-free": {
    "name": "Beam Free",
    "extra_body": { "reasoning": { "effort": "high" } },
    "limit": { "context": 1048576 },
    "reasoning_effort_levels": ["low", "high"]
  }
}
```

Model-level `extra_body` is merged over the provider's, one level deep at a time,
so a provider-wide quirk and a model-specific one compose instead of clobbering.
Any key Nova does not own passes through into the request body unchanged.

A model may also speak a **different transport** than its provider, on a
different endpoint. `type` and `base_url` on the model entry override the
provider's for that model alone:

```json
"models": {
  "gpt-5.6-luna": {
    "type": "openai-response",
    "base_url": "https://gateway.example/v1"
  }
}
```

Some gateways only serve clients they recognise and answer `401 unauthorized
client detected` to everything else. Nova always identifies itself as Nova, and
such a provider simply fails to connect — that refusal is reported as it came
from upstream rather than worked around. `options.user_agent` exists for the
case where you know which identity the gateway accepts and choose to send it
yourself; it applies to that provider alone, on discovery and on chat alike.

This is not a corner case: models.dev says 640 catalogue models use a transport
their provider does not, and 531 of those also need a different base URL. Nova
reads both from the catalogue when it discovers a model, so the mixed case works
without anyone writing it down — the entry above is only needed to override what
the catalogue says.

## How a model becomes selectable

`config.json` holds what you chose: the providers you connected, and any model you
pinned with a label, a context window, or tools turned off. It is not where the
model list lives.

Connecting a provider asks it what it serves (Ollama's `/api/tags`, OpenAI's
`/models`, Anthropic's `/v1/models`) and stores the answer in
`$NOVA_HOME/models.json` — a snapshot beside the database, not configuration.
Where the provider states a context window (`context_length`, `max_model_len`,
`max_input_tokens`, `context_window`), the snapshot keeps it. Where it states
nothing, the gap is filled from [models.dev](https://models.dev) — the same public
catalogue OpenCode and Codewhale are built on — once a day, in the background.
Both end up in the same per-model object:

```json
"deepseek": {
  "fetched_at": 1793537779,
  "models": {
    "deepseek-flash": {
      "context": 1048576,
      "context_source": "provider",
      "efforts": ["low", "high", "max"]
    }
  }
}
```

`context_source` records who said it. A window the provider stated is never
replaced by the catalogue; the catalogue only adds what was missing, and may
correct its own earlier value. Reasoning ladders work the same way: a config
declaration wins, otherwise the catalogue's `efforts` are offered, and a model
neither of them knows simply has no control. Nothing is ever inferred from the
model's name.

`config.json` is the override, never the inventory: it only needs an entry for a
model whose label, tools flag, context window or reasoning levels differ from
what Nova already knows.
`GET /api/models` merges the two: a configured entry wins, and an id known only
from the snapshot is selectable with Nova's defaults until you pin its real
values. Deleting the snapshot costs you nothing; deleting a provider removes its
models from the list.

Every TUI launch refreshes the **authenticated** providers once, in the
background: the first frame does not wait for it, and a provider that is down
only appears as itself in the list, not as an error. Nothing polls on a timer —
Nova refreshes when you start it, because that is the moment you would otherwise
restart to see a new model.

A provider whose key lives in `config.json` is a hand-authored one. Nova does not
poll it on startup: its model list is part of what you wrote, and
`POST /api/config/providers/{key}/sync-models` refreshes it on demand. That is
also what the check mark in `/connect` distinguishes — it marks a key Nova stores
for this machine, not a provider that merely exists in the file.

`GET /api/providers/{key}/available-models` exposes the same lookup for a form that
wants a picklist, and `POST /api/config/providers/{key}/sync-models` refreshes the
snapshot after, say, `ollama pull`. Failures are reported as failures — an
unreachable host, a rejected key, and a response that is not a model list each name
what has to change, because an empty list would send you looking in the wrong
place. The API key never leaves the server.

## Credentials and `{env:...}`

A provider Nova already knows needs only a key. "Knows" means the bundled floor
or a row remembered from an earlier connection — a key on its own carries no
base URL and no wire type, so a provider whose preset is neither is skipped with
a warning naming it. Reconnecting it from `/connect` is what restores the row. Keys live in
`$NOVA_HOME/credentials.json` (written with mode `0600`), never in
`config.json`, so connecting OpenAI or Anthropic leaves your config untouched and
nothing secret ends up in a file you might read, diff, or commit.

An explicit `config.json` entry always wins over a credential. That is how you
point a known provider at a proxy, pin a context window for one model, or declare
an endpoint Nova has never heard of.

A key can stay out of the file entirely:

```json
{
  "providers": {
    "gateway": {
      "type": "openai-compatible",
      "options": {
        "base_url": "https://gateway.example/v1",
        "api_key": "{env:GATEWAY_API_KEY}"
      }
    }
  }
}
```

`{env:NAME}` is resolved when the config is read. An unset variable resolves to an
empty key rather than to the literal template, so a missing secret fails as "no
key" instead of being sent as a bearer token.

Keep `credentials.json` out of version control — it is runtime state, like the
database.

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
