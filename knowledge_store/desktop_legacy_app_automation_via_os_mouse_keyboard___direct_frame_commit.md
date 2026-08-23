# Knowledge Profile: Desktop Legacy App Automation via OS Mouse/Keyboard & Direct Frame Commit
- **Domain**: Platform & Bot Automation
- **Harvested Date**: 2026-08-16 13:03:17
- **Keywords**: PyAutoGUI, CefSharp DevTools, ExtJS 3 Grid commit, ddddocr CAPTCHA

### [Bot Automation] Resilient Desktop & Web Automation Architecture
- **Core Architecture**: Dual-layer desktop automation combining CDP (Chrome DevTools Protocol) / Selenium with OS-level keyboard/mouse fallback (PyAutoGUI) to eliminate brittle DOM bindings.
- **Key Technique**:
  1. For legacy ExtJS grids: Inject direct store commit scripts into inner IFrames.
  2. For CAPTCHA: Use local `ddddocr` with length check constraints (e.g. exactly 5 chars) to auto-reload bad CAPTCHAs before submission.
- **Production Code Pattern**:
```python
import ddddocr
import time

ocr = ddddocr.DdddOcr(show_ad=False)

def solve_router_captcha(image_bytes, expected_len=5):
    res = ocr.classification(image_bytes)
    cleaned = ''.join(c for c in res if c.isalnum())
    if len(cleaned) == expected_len:
        return cleaned
    return None  # Trigger refresh
```
- **Actionable Application**: Applied in ZTE Router controller (`wifi_control`) and Thailand Post desktop clients.