# Context Compaction

Long sessions eventually exceed the model's context window. Nova handles this with two layers that run inside the agent loop, before every model call. Layer 1 is cheap and local. Layer 2 calls the model to summarise. Both are driven by the same token estimates the `GET /api/sessions/{id}/context` endpoint reports, so the numbers you see in the TUI and frontend match the decision the agent makes.

Source files: `nova/settings.py:_parse_compaction_config`, `nova/agent/compaction.py`.

## When Compaction Runs

Before each turn, the agent estimates the context size with `estimate_context_tokens()`. That function looks for the most recent assistant message that carried a `tokens_input` value from the provider. That value already includes the system prompt, tool schemas, and cached prefix, so the estimate does not drift.

The threshold that triggers compaction is `model_max_tokens - reserve`, where `model_max_tokens` is the model's window after a 20 percent safety margin and `reserve` is `output_reserve_tokens + summary_reserve_tokens`, capped at half the window. Two counters are checked:

* `scope_tokens`: tokens accumulated since the last compaction.
* `total_tokens`: absolute context size.

If either exceeds its limit, the agent first runs Layer 1, then re-evaluates. If pressure remains, it plans Layer 2. The failure counter on the controller can suppress repeated Layer 2 attempts.

## Layer 1: Snip Old Tool Output

Old tool results are the first thing to go. They are often the largest part of the prompt and the least useful in full once the task has moved on.

How it works (`snip_old_tool_results` in `nova/agent/compaction.py`):

1. Walk the history from newest to oldest, keeping a running token budget (`snip_tool_output_token_budget`).
2. The most recent `snip_preserve_last_n_messages` messages are always kept verbatim, and any tool output that still fits in the budget is kept verbatim too.
3. When the budget is exhausted, or a tool result is longer than `snip_max_chars`, the content is trimmed: the first quarter and last three quarters are kept, the middle is replaced with a marker like `[... 12345 chars snipped ... Full output: /path/to/file]`.
4. The full text is written to `~/.nova/sessions/<id>/tool-output/<message_id>.txt` so the model can read it back if needed.
5. Trimmed messages are written back to the database (`update_message_content`).

This step never calls a model, so it runs even while the Layer 2 circuit breaker is open.

```text
tool output kept verbatim while budget allows
        ↓
budget exhausted or content > snip_max_chars
        ↓
head (snip_max_chars/4) + [chars snipped + file pointer] + tail (snip_max_chars*3/4)
        ↓
full text on disk at ~/.nova/sessions/<id>/tool-output/<message_id>.txt
```

## Layer 2: Summarise Older Turns

When snipping is not enough, the agent asks the model to summarise the older part of the history.

How it works (`compact` and helpers in `nova/agent/compaction.py`):

1. The history is split with `find_split_point`, which keeps roughly `summary_keep_ratio` of the tokens in the recent portion. That split is then retreated to a safe boundary: it will not start on a `tool` message (that would orphan it from its declaring assistant turn) and it will start on a `user` message. If no safe split exists, compaction is skipped.
2. The older portion is formatted as `[role]: content` lines and sent to the model with a prompt that asks for seven sections: request and intent, technical context, files and code, errors and fixes, current state, pending work, and next step. If a previous summary exists in the older portion, the prompt tells the model to fold every still-relevant fact into the new summary.
3. On success, a new assistant message is inserted of the form `[Previous conversation summary]\n<summary>\n\n<continuation instruction>`, the old messages and any orphaned tool responses whose assistant turn was compacted are marked as compacted, and the session's `compacted_at` timestamp is updated.
4. On failure, the session is left untouched and the failure counter is incremented. A failed summary is not written as a summary, and old messages are not discarded.

The summarisation request itself costs tokens, which is why `summary_reserve_tokens` is reserved.

## Tuning Keys

All keys live under `compaction` in `~/.nova/config.json`. They are parsed by `_parse_compaction_config` in `nova/settings.py`. Unknown keys are ignored.

```json
{
  "compaction": {
    "output_reserve_tokens": 16000,
    "summary_reserve_tokens": 8000,
    "snip_max_chars": 2000,
    "snip_tool_output_token_budget": 50000,
    "snip_preserve_last_n_messages": 12,
    "summary_keep_ratio": 0.3,
    "max_consecutive_failures": 3,
    "default_context_window": 128000
  }
}
```

| Key | Default | What it controls |
|-----|---------|------------------|
| `output_reserve_tokens` | `16000` | Tokens reserved for the current model reply. Added to `summary_reserve_tokens` to form the total reserve. |
| `summary_reserve_tokens` | `8000` | Tokens reserved for the summarisation request itself. |
| `snip_max_chars` | `2000` | Layer 1 threshold: tool results longer than this are trimmed. Trimmed output keeps `max_chars/4` from the head and `max_chars*3/4` from the tail. |
| `snip_tool_output_token_budget` | `50000` | Layer 1 budget: walking from newest to oldest, tool output within this budget is kept verbatim. |
| `snip_preserve_last_n_messages` | `12` | Layer 1: the most recent N messages are always kept verbatim regardless of budget. Also accepts the legacy alias `snip_preserve_last_n_turns`. |
| `summary_keep_ratio` | `0.3` | Layer 2: fraction of tokens to keep in the recent portion when choosing the split point. `0.3` means roughly the last 30 percent of tokens stay. |
| `max_consecutive_failures` | `3` | Circuit breaker: after this many failed summarisation calls in a row, Layer 2 is disabled for the agent. `0` or negative means never disable. Layer 1 still runs. |
| `default_context_window` | `128000` | Assumed window when the model is unknown to the tokenizer. |

All numeric values are cast with `int()` or `float()` on load. The alias `snip_preserve_last_n_turns` is read only when `snip_preserve_last_n_messages` is absent:

```python
snip_preserve_last_n_messages=int(
    raw.get("snip_preserve_last_n_messages",
            raw.get("snip_preserve_last_n_turns", 12))),
```

If you used the legacy name, switch to `snip_preserve_last_n_messages` to avoid confusion. Both work, but the alias may be removed in a future release.

> **Note:** Three keys appeared in older documentation but are not read by the code: `token_ratio`, `max_messages`, and `max_turns_between_compact`. Setting them in `config.json` has no effect. Remove them to avoid confusion. This is the single highest-value correction from the previous docs: the real keys are the eight listed above.

## Observing Compaction

The agent emits events that surface in the streaming APIs:

* `COMPACTION_START` / `COMPACTION_END`: Layer 2 lifecycle, with `message_count` and `token_count`.
* `CONTEXT_UPDATE`: current `used`, `limit`, `percent` after each turn.

In the AI SDK SSE stream these appear as `data-nova-compaction-start`, `data-nova-compaction-end`, and `data-nova-context`. The TUI renders the context percentage as a bar above the input area.

## Tips

* If your model has a small window (for example, 32k), the reserve is capped at half the window so compaction does not fire on every request.
* If summarisation keeps failing, check the model is reachable and `max_consecutive_failures` is not masking the errors. Set it to `0` temporarily to keep retrying.
* To see what was trimmed, look under `~/.nova/sessions/<id>/tool-output/`. Each file is named `<message_id>.txt` and contains the full tool output before snipping.
