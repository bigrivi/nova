from __future__ import annotations

import sys
from pathlib import Path

import webview

from nova.license.fingerprint import fingerprint
from nova.license.validator import validate, _license_path


def _handle_drop(window: webview.Window) -> None:
    result = window.create_file_dialog(webview.OPEN_DIALOG, file_types=("License files (*.lic)",))
    if not result:
        return
    path = Path(result[0])
    dst = _license_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(path.read_bytes())

    status = validate()
    if status.is_valid:
        window.load_url("about:blank")
        window.destroy()
    else:
        window.evaluate_js(f"document.getElementById('error').textContent = {status.message!r}")


def show_activation_dialog() -> bool:
    fp = fingerprint()
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f5f7; display: flex; align-items: center; justify-content: center;
    min-height: 100vh; color: #1d1d1f;
  }}
  .card {{ background: #fff; border-radius: 16px; padding: 32px; width: 420px; box-shadow: 0 4px 24px rgba(0,0,0,.08); }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  p {{ font-size: 13px; color: #86868b; margin-bottom: 20px; }}
  .fingerprint {{ background: #f5f5f7; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 13px; word-break: break-all; margin-bottom: 20px; }}
  .fingerprint label {{ font-size: 11px; color: #86868b; display: block; margin-bottom: 4px; }}
  .btn {{
    display: inline-flex; align-items: center; justify-content: center;
    padding: 8px 20px; border-radius: 20px; font-size: 13px; font-weight: 500;
    border: none; cursor: pointer; background: #0071e3; color: #fff; width: 100%;
  }}
  .btn:hover {{ background: #0077ed; }}
  .error {{ color: #d32f2f; font-size: 12px; margin-top: 12px; min-height: 18px; }}
</style>
</head>
<body>
<div class="card">
  <h1>Activate Nova</h1>
  <p>Send the machine fingerprint below to the developer to receive a license file.</p>
  <div class="fingerprint">
    <label>Machine Fingerprint</label>
    {fp}
  </div>
  <button class="btn" onclick="selectFile()">Select License File</button>
  <p class="error" id="error"></p>
</div>
<script>
function selectFile() {{ pywebview.api.select_file(); }}
</script>
</body>
</html>"""

    activated = False

    class API:
        def select_file(self) -> None:
            nonlocal activated
            result = window.create_file_dialog(webview.OPEN_DIALOG, file_types=("License files (*.lic)",))
            if not result:
                return
            path = Path(result[0])
            dst = _license_path()
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(path.read_bytes())

            status = validate()
            if status.is_valid:
                nonlocal activated
                activated = True
                window.destroy()
            else:
                window.evaluate_js(f"document.getElementById('error').textContent = {status.message!r}")

    window = webview.create_window(
        "Activate Nova",
        html=html,
        width=480,
        height=400,
        resizable=False,
        js_api=API(),
    )
    webview.start()
    return activated
