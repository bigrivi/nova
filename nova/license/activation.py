from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import webview

from nova.license.fingerprint import fingerprint
from nova.license.validator import validate, _license_path


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
  .card {{ background: #fff; border-radius: 16px; padding: 32px; width: 440px; box-shadow: 0 4px 24px rgba(0,0,0,.08); }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  p {{ font-size: 13px; color: #86868b; margin-bottom: 20px; }}
  .fingerprint {{ background: #f5f5f7; border-radius: 8px; padding: 12px; margin-bottom: 16px; }}
  .fingerprint label {{ font-size: 11px; color: #86868b; display: block; margin-bottom: 4px; }}
  .fingerprint code {{ display: block; font-family: monospace; font-size: 13px; word-break: break-all; user-select: all; }}
  .row {{ display: flex; gap: 8px; }}
  .row .btn {{ flex: 1; }}
  .btn {{
    display: inline-flex; align-items: center; justify-content: center;
    padding: 8px 20px; border-radius: 20px; font-size: 13px; font-weight: 500;
    border: none; cursor: pointer;
  }}
  .btn-primary {{ background: #0071e3; color: #fff; }}
  .btn-primary:hover {{ background: #0077ed; }}
  .btn-secondary {{ background: #e8e8ed; color: #1d1d1f; }}
  .btn-secondary:hover {{ background: #d1d1d6; }}
  .toast {{
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: #1d1d1f; color: #fff; padding: 8px 16px; border-radius: 20px;
    font-size: 12px; opacity: 0; transition: opacity .3s;
  }}
  .toast.show {{ opacity: 1; }}
  .error {{ color: #d32f2f; font-size: 12px; margin-top: 12px; min-height: 18px; }}
</style>
</head>
<body>
<div class="card">
  <h1>Activate Nova</h1>
  <p>Send this fingerprint to the developer to get a license file.</p>
  <div class="fingerprint">
    <label>Machine Fingerprint</label>
    <code id="fp">{fp}</code>
  </div>
  <div class="row">
    <button class="btn btn-secondary" onclick="copyFp()">Copy</button>
    <button class="btn btn-primary" onclick="selectFile()">Select License File</button>
  </div>
  <p class="error" id="error"></p>
</div>
<div class="toast" id="toast">Copied!</div>
<script>
function copyFp() {{ pywebview.api.copy_fingerprint(); }}
function selectFile() {{ pywebview.api.select_file(); }}
</script>
</body>
</html>"""

    activated = False

    class API:
        def copy_fingerprint(self) -> None:
            text = fp
            try:
                if sys.platform == "darwin":
                    subprocess.run(["pbcopy"], input=text.encode(), check=True)
                elif sys.platform == "win32":
                    subprocess.run(["clip"], input=text.encode(), check=True)
            except Exception:
                pass
            window.evaluate_js(
                "var t=document.getElementById('toast');t.classList.add('show');setTimeout(function(){t.classList.remove('show');},1500);"
            )

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
        width=500,
        height=420,
        resizable=False,
        js_api=API(),
    )
    webview.start()
    return activated
