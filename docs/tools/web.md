# Web Tools

## `web_search`

Search the web using the Exa search API. Returns relevant results with
descriptions.

```text
Search for the latest news about AI agents
```

## `web_fetch`

Fetch a web page and extract its content as Markdown.

```text
Fetch https://example.com and summarize the content
```

- 5MB response limit
- Uses a browser user-agent for better compatibility
- Converts HTML to readable Markdown

## `browser_use`

Full browser automation using Playwright. Supports 18 actions including:

- `go_to_url` -- navigate to a URL
- `click_element` -- click on a page element
- `input_text` -- type text into an input field
- `scroll_down` / `scroll_up` -- scroll the page
- `scroll_to_text` -- scroll to specific text
- `extract_content` -- extract page content with LLM assistance
- `screenshot` -- take a page screenshot
- `switch_tab` / `open_tab` / `close_tab` -- manage tabs
- `go_back` -- navigate back

```text
Go to github.com, search for "nova", and show me the results
```

Requires Playwright to be installed:

```bash
playwright install chromium
```

Uses a persistent Chrome profile at `~/.nova/chrome-profile/` for session
continuity.
