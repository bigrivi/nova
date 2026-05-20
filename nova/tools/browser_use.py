import asyncio
import base64
import json
import os
import sys
import shutil
from pathlib import Path
from typing import Optional

from nova.llm import ToolResult
from nova.tools.registry import tool
from nova.tools.web_search import TOOL as web_search_tool

_BROWSER_DESCRIPTION = """\
A browser automation tool for interacting with web pages through various actions.
Maintains state across calls — the browser session persists until explicitly closed.

Each action returns the current page URL, title, and a list of clickable elements
identified by index (e.g. [0], [1], ...). Use these indices for click_element,
input_text, get_dropdown_options, and select_dropdown_option actions.

Key capabilities:
- Navigation: go_to_url, go_back, web_search
- Interaction: click_element, input_text, send_keys
- Scrolling: scroll_down, scroll_up, scroll_to_text
- Dropdowns: get_dropdown_options, select_dropdown_option
- Extraction: extract_content
- Tabs: switch_tab, open_tab, close_tab
- Utilities: wait, get_state, cleanup
"""

_playwright = None
_browser = None
_context = None
_page = None
_extraction_llm = None
_element_cache: dict[str, list] = {}


def _detect_system_browser() -> str | None:
    candidates = []
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
    elif sys.platform == "win32":
        candidates = [
            shutil.which("chrome"),
            shutil.which("msedge"),
            shutil.which("brave"),
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        ]
    elif sys.platform == "linux":
        candidates = [
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("brave-browser"),
        ]
    for path in candidates:
        if path and Path(path).exists():
            return str(path)
    return None


def _detect_system_profile() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    if sys.platform == "win32":
        return os.path.expanduser("~/AppData/Local/Google/Chrome/User Data")
    return os.path.expanduser("~/.config/google-chrome")


def _seed_profile(target: str):
    src_default = os.path.join(_detect_system_profile(), "Default")
    if not os.path.isdir(src_default):
        return
    dst_default = os.path.join(target, "Default")
    os.makedirs(dst_default, exist_ok=True)
    for name in ("Extensions", "Bookmarks", "Preferences", "Cookies", "Login Data"):
        src = os.path.join(src_default, name)
        if os.path.exists(src):
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(dst_default, name), dirs_exist_ok=True)
                else:
                    shutil.copy2(src, os.path.join(dst_default, name))
            except Exception:
                pass


async def _ensure_browser():
    global _playwright, _browser, _context, _page
    if _browser is not None:
        return _page

    from playwright.async_api import async_playwright

    _playwright = await async_playwright().start()

    browser_path = _detect_system_browser()

    user_data_dir = os.path.expanduser("~/.nova/chrome-profile")
    if not os.path.isdir(os.path.join(user_data_dir, "Default")):
        _seed_profile(user_data_dir)

    launch_kwargs = {
        "headless": False,
        "ignore_default_args": [
            "--enable-automation",
            "--disable-extensions",
            "--disable-component-extensions-with-background-pages",
            "--no-sandbox",
        ],
        "viewport": {"width": 1280, "height": 720},
    }
    if browser_path:
        launch_kwargs["executable_path"] = browser_path

    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir, **launch_kwargs
    )
    _browser = _context.browser
    _page = _context.pages[0] if _context.pages else await _context.new_page()
    return _page


def _invalidate_cache():
    _element_cache.clear()


@tool(
    name="browser_use",
    description=_BROWSER_DESCRIPTION,
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "go_to_url", "click_element", "input_text",
                    "scroll_down", "scroll_up", "scroll_to_text",
                    "send_keys", "get_dropdown_options", "select_dropdown_option",
                    "go_back", "web_search", "wait", "extract_content",
                    "switch_tab", "open_tab", "close_tab",
                    "get_state", "cleanup",
                ],
                "description": (
                    "The browser action to perform. "
                    "go_to_url requires url. "
                    "click_element requires index. "
                    "input_text requires index and text. "
                    "scroll_down/scroll_up optionally accept scroll_amount. "
                    "scroll_to_text requires text. "
                    "send_keys requires keys. "
                    "get_dropdown_options/select_dropdown_option require index (and text for select). "
                    "go_back takes no extra params. "
                    "web_search requires query. "
                    "wait optionally accepts seconds. "
                    "extract_content requires goal. "
                    "switch_tab requires tab_id. "
                    "open_tab requires url. "
                    "close_tab takes no extra params. "
                    "get_state/cleanup take no extra params."
                ),
            },
            "url": {
                "type": "string",
                "description": "URL for go_to_url or open_tab actions",
            },
            "index": {
                "type": "integer",
                "description": "Element index for click_element, input_text, get_dropdown_options, or select_dropdown_option",
            },
            "text": {
                "type": "string",
                "description": "Text for input_text, scroll_to_text, or select_dropdown_option",
            },
            "scroll_amount": {
                "type": "integer",
                "description": "Pixels to scroll (positive down, negative up) for scroll_down or scroll_up",
            },
            "tab_id": {
                "type": "integer",
                "description": "Tab ID for switch_tab action",
            },
            "query": {
                "type": "string",
                "description": "Search query for web_search action",
            },
            "goal": {
                "type": "string",
                "description": "Extraction goal for extract_content action",
            },
            "keys": {
                "type": "string",
                "description": "Keys to send for send_keys action",
            },
            "seconds": {
                "type": "integer",
                "description": "Seconds to wait for wait action",
            },
            "screenshot": {
                "type": "boolean",
                "description": "Include screenshot in get_state response (default false)",
            },
        },
        "required": ["action"],
    },
)
async def browser_use(
    action: str,
    url: Optional[str] = None,
    index: Optional[int] = None,
    text: Optional[str] = None,
    scroll_amount: Optional[int] = None,
    tab_id: Optional[int] = None,
    query: Optional[str] = None,
    goal: Optional[str] = None,
    keys: Optional[str] = None,
    seconds: Optional[int] = None,
    screenshot: Optional[bool] = None,
) -> ToolResult:
    global _page

    try:
        if action == "cleanup":
            await _cleanup()
            return ToolResult(content="Browser session closed.")

        if action == "get_state":
            _invalidate_cache()
            include_screenshot = screenshot if screenshot is not None else False
            state = await _get_state(include_screenshot=include_screenshot)
            payload = {"text": _format_state_text(state)}
            if include_screenshot:
                payload["images"] = [state["screenshot"]]
            return ToolResult(content=json.dumps(payload, ensure_ascii=False))

        page = await _ensure_browser()

        if action == "go_to_url":
            if not url:
                return ToolResult(error="URL required for go_to_url")
            await page.goto(url, wait_until="load")
            _invalidate_cache()

        elif action == "go_back":
            await page.go_back()
            await page.wait_for_load_state()
            _invalidate_cache()

        elif action == "click_element":
            if index is None:
                return ToolResult(error="Index required for click_element")
            elements = await _get_clickable_elements(page)
            if index < 0 or index >= len(elements):
                return ToolResult(error=f"Invalid index {index}, max {len(elements) - 1}")
            await page.locator(f"xpath={elements[index]['xpath']}").first.click()

        elif action == "input_text":
            if index is None or text is None:
                return ToolResult(error="Index and text required for input_text")
            elements = await _get_clickable_elements(page)
            if index < 0 or index >= len(elements):
                return ToolResult(error=f"Invalid index {index}")
            await page.locator(f"xpath={elements[index]['xpath']}").first.fill(text)

        elif action == "scroll_down":
            amount = scroll_amount if scroll_amount is not None else 600
            await page.evaluate("window.scrollBy(0, arguments[0])", amount)

        elif action == "scroll_up":
            amount = scroll_amount if scroll_amount is not None else 600
            await page.evaluate("window.scrollBy(0, -arguments[0])", amount)

        elif action == "scroll_to_text":
            if not text:
                return ToolResult(error="Text required for scroll_to_text")
            locator = page.get_by_text(text, exact=False)
            await locator.scroll_into_view_if_needed()

        elif action == "send_keys":
            if not keys:
                return ToolResult(error="Keys required for send_keys")
            await page.keyboard.press(keys)

        elif action == "get_dropdown_options":
            if index is None:
                return ToolResult(error="Index required for get_dropdown_options")
            elements = await _get_clickable_elements(page)
            if index < 0 or index >= len(elements):
                return ToolResult(error=f"Invalid index {index}")
            options = await page.evaluate("""
                (xpath) => {
                    const el = document.evaluate(xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (!el || el.tagName !== 'SELECT') return null;
                    return Array.from(el.options).map(o => ({
                        text: o.text, value: o.value, index: o.index
                    }));
                }
            """, elements[index]["xpath"])
            return ToolResult(content=json.dumps({"text": f"Dropdown options: {json.dumps(options, ensure_ascii=False)}"}, ensure_ascii=False))

        elif action == "select_dropdown_option":
            if index is None or text is None:
                return ToolResult(error="Index and text required for select_dropdown_option")
            elements = await _get_clickable_elements(page)
            if index < 0 or index >= len(elements):
                return ToolResult(error=f"Invalid index {index}")
            await page.locator(f"xpath={elements[index]['xpath']}").first.select_option(label=text)

        elif action == "web_search":
            if not query:
                return ToolResult(error="Query required for web_search")
            result = await web_search_tool(query=query, fetch_content=True, num_results=1)
            if not result.success or not result.content:
                return ToolResult(error="Search returned no results")
            try:
                search_data = json.loads(result.content)
                urls = search_data.get("results", [])
                if urls:
                    first_url = urls[0].get("url", "") if isinstance(
                        urls[0], dict) else urls[0]
                    if first_url:
                        await page.goto(first_url, wait_until="load")
                        _invalidate_cache()
            except (json.JSONDecodeError, IndexError, KeyError) as e:
                return ToolResult(error=f"Failed to parse search results: {e}")

        elif action == "wait":
            seconds_to_wait = seconds if seconds is not None else 3
            await asyncio.sleep(seconds_to_wait)

        elif action == "extract_content":
            if not goal:
                return ToolResult(error="Goal required for extract_content")
            import markdownify
            narrowed = await page.inner_html(
                "main, article, #content, [role=main]"
            )
            raw_html = f"<html><body>{narrowed}</body></html>" if narrowed else await page.content()
            raw_content = markdownify.markdownify(raw_html)

            global _extraction_llm
            if _extraction_llm is None:
                from nova.app.runtime import build_llm
                from nova.settings import get_settings
                _extraction_llm = build_llm(get_settings())

            content_trunc = raw_content[:8000]
            prompt = (
                "You are a web content extractor. Extract the information "
                f"relevant to the following goal from the page content below.\n\n"
                f"Goal: {goal}\n\n"
                f"Page content:\n{content_trunc}\n\n"
                "Return only the extracted information, no extra commentary."
            )
            response = await _extraction_llm.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            return ToolResult(content=json.dumps({
                "text": response.content,
            }, ensure_ascii=False))

        elif action == "switch_tab":
            if tab_id is None:
                return ToolResult(error="Tab ID required for switch_tab")
            pages = _context.pages
            if tab_id < 0 or tab_id >= len(pages):
                return ToolResult(error=f"Invalid tab ID {tab_id}, open tabs: {len(pages)}")
            _page = pages[tab_id]
            await _page.bring_to_front()

        elif action == "open_tab":
            if not url:
                return ToolResult(error="URL required for open_tab")
            _page = await _context.new_page()
            await _page.goto(url, wait_until="load")
            _invalidate_cache()

        elif action == "close_tab":
            pages = _context.pages
            if len(pages) <= 1:
                return ToolResult(error="Cannot close the last tab")
            await _page.close()
            pages = _context.pages
            _page = pages[-1]

        else:
            return ToolResult(error=f"Unknown action: {action}")

        _invalidate_cache()
        state = await _get_state(include_screenshot=False)
        return ToolResult(content=json.dumps({
            "text": _format_state_text(state),
        }, ensure_ascii=False))

    except Exception as e:
        return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")


async def _get_clickable_elements(page) -> list[dict]:
    current_url = page.url
    if current_url in _element_cache:
        return _element_cache[current_url]
    elements = await page.evaluate("""
        () => {
            const tags = ['a', 'button', 'input', 'select', 'textarea',
                '[role=button]', '[role=link]', '[role=tab]', '[role=menuitem]',
                '[role=option]', '[onclick]', 'label',
                'div[tabindex]:not([tabindex="-1"])',
                'span[tabindex]:not([tabindex="-1"])',
                '[class*="btn"]', '[class*="button"]'];
            const all = document.querySelectorAll(tags.join(','));
            const results = [];
            let index = 0;
            for (const el of all) {
                const rect = el.getBoundingClientRect();
                if (rect.width < 5 || rect.height < 5) continue;
                if (el.offsetParent === null && el.tagName !== 'SELECT') continue;
                const text = (el.textContent || el.value || el.placeholder || '').trim().slice(0, 80);
                if (!text && !el.href) continue;
                results.push({
                    index: index++,
                    tag: el.tagName.toLowerCase(),
                    text: text,
                    href: el.href || '',
                    type: el.type || '',
                    xpath: _getXPath(el),
                });
            }
            return results;
            function _getXPath(el) {
                const parts = [];
                while (el && el.nodeType === 1) {
                    let idx = 1;
                    for (let sib = el.previousSibling; sib; sib = sib.previousSibling) {
                        if (sib.nodeType === 1 && sib.tagName === el.tagName) idx++;
                    }
                    parts.unshift(el.tagName.toLowerCase() + '[' + idx + ']');
                    el = el.parentElement;
                }
                return '/' + parts.join('/');
            }
        }
    """)
    _element_cache[current_url] = elements
    return elements


async def _get_state(include_screenshot: bool = False) -> dict:
    try:
        await _page.wait_for_load_state("load", timeout=10000)
    except Exception:
        pass
    await asyncio.sleep(0.2)
    url = _page.url
    title = await _page.title()

    elements = await _get_clickable_elements(_page)
    scroll = await _page.evaluate("""() => ({
        pixels_above: window.scrollY,
        pixels_below: Math.max(0, document.documentElement.scrollHeight - window.scrollY - window.innerHeight),
        total_height: document.documentElement.scrollHeight,
        viewport_height: window.innerHeight,
    })""")

    state = {
        "url": url,
        "title": title,
        "tabs": len(_context.pages) if _context else 1,
        "scroll_info": scroll,
        "interactive_elements": "\n".join(
            f"[{e['index']}] <{e['tag']}>{' ' + e['text'][:60] if e['text'] else ''}"
            for e in elements[:80]
        ),
    }

    if include_screenshot:
        screenshot = await _page.screenshot(
            full_page=False, type="jpeg", quality=85
        )
        state["screenshot"] = base64.b64encode(screenshot).decode("utf-8")
        state["screenshot_mime"] = "image/jpeg"

    return state


def _format_state_text(state: dict) -> str:
    lines = [
        f"URL: {state['url']}",
        f"Title: {state['title']}",
        f"Tabs: {state['tabs']}",
    ]
    si = state["scroll_info"]
    lines.append(
        f"Scroll: {si['pixels_above']}px above, {si['pixels_below']}px below "
        f"(total {si['total_height']}px)"
    )
    if state["interactive_elements"]:
        lines.append(
            f"\nInteractive elements:\n{state['interactive_elements']}")
    return "\n".join(lines)


async def _cleanup():
    global _playwright, _browser, _context, _page
    if _context:
        await _context.close()
        _context = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
    _page = None
    _browser = None


TOOL = browser_use
