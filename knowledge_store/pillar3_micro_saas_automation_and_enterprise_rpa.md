# High-Yield Micro-SaaS Automation, Anti-Detect Scrapers & Enterprise RPA Bots
- **Pillar**: Pillar 3: Micro-SaaS & Bot Automation Innovations
- **Generated Date**: 2026-08-23 10:55:11
- **Synthesized By**: 0x Alpha (stealth/ox-alpha) via Antigravity 2.0

---

# Micro‑SaaS Automation Blueprint — Technical Reference Implementation
**Stack baseline:** Python 3.12 · Playwright · httpx · FastAPI · Redis · Postgres · arq · structlog · Prometheus · Docker

---

## §0 System Topology

```
                        ┌──────────────────────────────────────────────┐
                        │                 CONTROL PLANE                │
                        │  Postgres (leads/state) · Redis (queues/     │
                        │  sessions/throttle) · Prometheus · Sentry    │
                        └───────────▲──────────────────▲───────────────┘
                                    │                  │
     ┌──────────────────────────────┴───┐   ┌──────────┴──────────────────┐
     │  DATA ENGINE (§1)                │   │  GATEWAY (§3)               │
     │  ProxyPool → StealthContext →    │   │  FastAPI webhooks           │
     │  Harvesters → Enricher → Sinks   │   │  TG/LINE → Agent(LLM FC) →  │
     └──────────────────────────────────┘   │  Billing (Stripe/PromptPay) │
                                            └─────────────────────────────┘
     ┌──────────────────────────────────┐
     │  RPA WORKERS (§2)                │  Desktop: PyAutoGUI · Web: DOM-Store
     │  OCR solver w/ constraint gates  │  + IFrame resolver + ddddocr
     └──────────────────────────────────┘
```

---

# §1 High-Throughput Extraction & B2B Lead Engine

## 1.1 Stealth Browser Layer (Playwright + CDP patches)

**Principle:** detection is *coherence* — TLS/JA3, HTTP/2 frames, header order, JS surface, and behavior must agree. Patch all layers or none.

```python
# engine/stealth.py
from urllib.parse import urlparse

PERSONAS = [
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
     "platform": "Win32", "cores": 8, "mem": 8, "locale": "en-US",
     "tz": "America/New_York", "webgl_vendor": "Intel Inc.",
     "webgl_renderer": "Intel(R) UHD Graphics 630"},
]

_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage", "--disable-infobars",
    "--no-first-run", "--window-size=1366,768",
]

_STEALTH_TMPL = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.chrome={runtime:{},loadTimes:()=>({}),csi:()=>({})};
const _pq=navigator.permissions.query.bind(navigator.permissions);
navigator.permissions.query=p=>p.name==='notifications'
  ? Promise.resolve({state:Notification.permission}) : _pq(p);
Object.defineProperty(navigator,'plugins',{get:()=>[{name:'Chrome PDF Viewer'},{}]});
Object.defineProperty(navigator,'languages',{get:()=>['__LOCALE__','en']});
Object.defineProperty(navigator,'hardwareConcurrency',{get:()=>__CORES__});
Object.defineProperty(navigator,'deviceMemory',{get:()=>__MEM__});
Object.defineProperty(navigator,'platform',{get:()=>('__PLATFORM__')});
const gp=WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter=function(p){
  if(p===37445)return '__VENDOR__';
  if(p===37446)return '__RENDERER__';
  return gp.call(this,p);};
// canvas: inject sub-pixel noise so hashes vary per-context
const _td=HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext=function(t,a){
  const ctx=_td.apply(this,[t,a]);
  if(ctx&&t==='2d'){const orig=ctx.getImageData.bind(ctx);
    ctx.getImageData=(...args)=>{const d=orig(...args);
      for(let i=0;i<d.data.length;i+=997)d.data[i]^=1;return d;};}
  return ctx;};
"""

def stealth_script(persona: dict) -> str:
    s = _STEALTH_TMPL
    s = s.replace("__LOCALE__", persona["locale"]).replace("__PLATFORM__", persona["platform"])
    s = s.replace("__CORES__", str(persona["cores"])).replace("__MEM__", str(persona["mem"]))
    s = s.replace("__VENDOR__", persona["webgl_vendor"]).replace("__RENDERER__", persona["webgl_renderer"])
    return s

def pw_proxy(url: str) -> dict:
    u = urlparse(url)
    p = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username: p.update(username=u.username, password=u.password)
    return p
```

```python
# engine/context_factory.py
import random
from playwright.async_api import async_playwright, BrowserContext
from engine.stealth import PERSONAS, _CHROME_ARGS, stealth_script, pw_proxy

async def open_context(pw, proxy_url: str | None = None) -> tuple[BrowserContext, dict]:
    persona = random.choice(PERSONAS)
    browser = await pw.chromium.launch(
        headless=True, args=_CHROME_ARGS,
        ignore_default_args=["--enable-automation"],   # kill navigator flag at CDP level
    )
    ctx = await browser.new_context(
        user_agent=persona["ua"], locale=persona["locale"],
        timezone_id=persona["tz"], viewport={"width": 1366, "height": 768},
        proxy=pw_proxy(proxy_url) if proxy_url else None,
    )
    await ctx.add_init_script(stealth_script(persona))   # runs pre-JS in EVERY frame
    return ctx, persona
```

> **Hardening note:** for targets running advanced bot management (Akamai/PerimeterX/DataDome), stock Chromium headless leaks beyond JS — deploy **Patchright** or **rebrowser-patches** (drop-in Playwright forks that fix CDP runtime leaks), or run headed Chromium under **Xvfb** (`xvfb-run`) in your worker containers.

## 1.2 Residential Proxy Pool — Health-Scored, Sticky, Self-Healing

```python
# engine/proxy_pool.py
import time, asyncio, math
from dataclasses import dataclass, field
import httpx

BLOCK_MARKERS = ("just a moment", "cf-challenge", "attention required",
                 "px-captcha", "captcha-delivery", "access denied")

@dataclass
class ProxyNode:
    url: str
    region: str = "us"
    score: float = 1.0                 # EMA success rate
    lat_ema_ms: float = 900.0          # EMA latency
    fails: int = 0
    banned_until: float = 0.0

class ProxyPool:
    """Sticky-per-target rotation with AIMD quarantine and background health checks."""
    def __init__(self, urls: list[str]):
        self.nodes = {u: ProxyNode(u) for u in urls}
        self._sticky: dict[str, ProxyNode] = {}

    def _healthy(self, n: ProxyNode) -> bool:
        return n.score > 0.25 and n.fails < 5 and time.time() >= n.banned_until

    def acquire(self, session_key: str) -> ProxyNode:
        cur = self._sticky.get(session_key)
        if cur and self._healthy(cur):
            return cur
        live = [n for n in self.nodes.values() if self._healthy(n)]
        if not live:
            for n in self.nodes.values():       # full quarantine breach → reset
                n.fails, n.banned_until = 0, 0.0
            live = list(self.nodes.values())
        node = max(live, key=lambda n: n.score / math.log2(400 + n.lat_ema_ms))
        self._sticky[session_key] = node
        return node

    def report(self, node: ProxyNode, ok: bool, status: int = 200, html: str = ""):
        if ok and not any(m in html.lower() for m in BLOCK_MARKERS):
            node.score = round(0.8 * node.score + 0.2 * 1.0, 4)
            node.lat_ema_ms = 0.7 * node.lat_ema_ms + 0.3 * node.lat_ema_ms
            node.fails = 0
        else:
            node.score = round(0.8 * node.score + 0.2 * 0.0, 4)
            node.fails += 1
            if node.fails >= 3:                          # escalating cooldown
                node.banned_until = time.time() + 120 * 2 ** (node.fails - 3)

    async def health_check_loop(self, interval: int = 600):
        while True:
            async with httpx.AsyncClient(timeout=10) as hc:
                for n in list(self.nodes.values()):
                    try:
                        t0 = time.perf_counter()
                        r = await hc.get("https://api.ipify.org", proxy=n.url)
                        ok = r.status_code == 200
                        n.lat_ema_ms = 0.7 * n.lat_ema_ms + 0.3 * (time.perf_counter() - t0) * 1000
                        self.report(n, ok)
                    except Exception:
                        self.report(n, False)
            await asyncio.sleep(interval)
```

## 1.3 Adaptive Rate-Limit Evasion (AIMD + Jitter)

Never fixed sleeps. Treat the WAF as a feedback controller: success ⇒ speed up slightly; any 403/429/challenge ⇒ back off multiplicatively.

```python
# engine/throttle.py
import asyncio, random

class AdaptiveThrottle:
    def __init__(self, start=2.0, floor=0.35, ceiling=90.0, jitter=0.4):
        self.interval, self.floor, self.ceiling, self.jitter = start, floor, ceiling, jitter

    async def wait(self):
        await asyncio.sleep(max(0.05, self.interval * (1 + random.uniform(-self.jitter, self.jitter))))

    def on_success(self): self.interval = max(self.floor,   self.interval * 0.93)
    def on_block(self):   self.interval = min(self.ceiling, self.interval * 2.6)

    def classify(self, status: int, html: str) -> str:
        h = html.lower()
        if status == 429 or any(m in h for m in ("just a moment", "px-captcha")): return "block"
        if status in (403, 503): return "soft_block"
        return "ok"
```

## 1.4 Harvester Core — Response Sniffing First, DOM Second

**Senior-level rule:** intercept the site's own JSON/XHR APIs instead of parsing HTML whenever possible — 10× cheaper, 10× more stable.

```python
# engine/harvester.py
import asyncio, hashlib, json, re
from playwright.async_api import Page
from engine.context_factory import open_context
from engine.proxy_pool import ProxyPool
from engine.throttle import AdaptiveThrottle

EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.I)
JSON_CT = ("application/json", "text/plain")

class DomainHarvester:
    def __init__(self, pool: ProxyPool, sem: asyncio.Semaphore):
        self.pool, self.sem = pool, sem
        self.throttles: dict[str, AdaptiveThrottle] = {}
        self.captured: list[dict] = []

    def _throttle_for(self, domain: str) -> AdaptiveThrottle:
        return self.throttles.setdefault(domain, AdaptiveThrottle())

    async def _sniff(self, resp):
        """Passive capture of XHR payloads — often contains the exact contact dataset."""
        try:
            ct = resp.headers.get("content-type", "")
            if resp.status == 200 and any(ct.startswith(c) for c in JSON_CT) \
               and any(k in resp.url.path for k in ("contact", "people", "team", "staff")):
                self.captured.append({"url": str(resp.url), "data": await resp.json()})
        except Exception:
            pass

    async def harvest(self, url: str) -> dict:
        from urllib.parse import urlparse
        dom = urlparse(url).netloc
        th = self._throttle_for(dom)
        async with self.sem:
            for attempt in range(3):
                node = self.pool.acquire(f"sticky:{dom}")
                th.wait();  await th.wait()
                try:
                    async with open_context(proxy_url=node.url) as (ctx, _):
                        page = await ctx.new_page()
                        page.on("response", self._sniff)
                        r = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                        await page.wait_for_timeout(random_jitter(1500, 3500))
                        # scroll to trigger lazy-loaded team/contact widgets
                        for _ in range(6):
                            await page.mouse.wheel(0, 900)
                            await page.wait_for_timeout(random_jitter(250, 700))
                        html = await page.content()
                        verdict = th.classify(r.status, html)
                        if verdict != "ok":
                            self.pool.report(node, False, r.status, html); th.on_block()
                            continue
                        self.pool.report(node, True, r.status, html); th.on_success()
                        emails = {e.lower().strip("."): None for e in EMAIL_RE.findall(html)}
                        links = await page.eval_on_selector_all(
                            "a[href]", "els => els.map(e=>({t:e.innerText.trim(),h:e.href}))")
                        return {"domain": dom, "emails": list(emails),
                                "xhr": self.captured[-5:], "links": links[:200]}
                except Exception as e:
                    self.pool.report(node, False)
                    th.on_block()
            return {"domain": dom, "emails": [], "xhr": [], "links": []}

def random_jitter(a: int, b: int) -> int:
    import random; return random.randint(a, b)
```

## 1.5 Enrichment → Verification → ICP Scoring → Sink

```python
# engine/enrich.py
import dns.resolver, hashlib, re

TITLE_WEIGHTS = {"ceo":5,"founder":5,"owner":5,"cto":4,"cmo":4,"director":3,
                 "head":3,"manager":2,"vp":3}

def has_mx(domain: str) -> bool:
    try: return bool(dns.resolver.resolve(domain, "MX"))
    except Exception: return False

def normalize_email(e: str) -> str | None:
    e = e.strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", e): return None
    if any(x in e for x in ("noreply","donotreply","example.","postmaster@","abuse@")): return None
    return e

def icp_score(lead: dict) -> float:
    s = has_mx(lead["email_domain"]) * 20
    s += TITLE_WEIGHTS.get(next((k for k in TITLE_WEIGHTS if k in lead.get("title","").lower()), ""), 0) * 4
    s += 15 if lead.get("source_xhr") else 0        # structured source = higher fidelity
    return min(s, 100)

def lead_fingerprint(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()

async def persist_and_push(leads: list[dict], pg_pool, hubspot_key: str | None = None):
    import httpx
    async with pg_pool.acquire() as con:
        for ld in leads:
            await con.execute("""
              INSERT INTO leads (fp,email,name,title,domain,score,raw)
              VALUES ($1,$2,$3,$4,$5,$6,$7)
              ON CONFLICT (fp) DO UPDATE SET score=GREATEST(leads.score,$6), updated_at=now()
            """, lead_fingerprint(ld["email"]), ld["email"], ld.get("name"),
                 ld.get("title"), ld["email_domain"], icp_score(ld), json_dumps(ld))
    # Optional: CRM fan-out with idempotency
    ...
```

**Pipeline DAG (arq worker):**
`seed_urls → harvest → normalize/dedupe(fp) → MX verify → score ≥ threshold → Postgres → HubSpot/Sheets sync → outreach export`

---

## §1 Monetization Workflow — "LeadForge"

| Tier | Price | Deliverable | COGS |
|---|---|---|---|
| Starter | $49/mo | 500 MX-verified leads CSV | ≈$3 proxies |
| Growth | $199/mo | 2.5k leads + enrichment + Sheets/CRM sync | ≈$12 |
| Agency | $999/mo | White-label API, dedicated proxy pools, custom ICP | ≈$60 |

**Unit economics:** residential bandwidth ≈ $3–8/GB; avg page ≈ 0.5 MB ⇒ **cost/verified lead < $0.05** against realized price of **$0.10–0.40/lead** ⇒ 70 %+ gross margin.
**GTM loop (dogfooding):** use the engine itself to build prospect lists of marketing agencies & recruiters → automated cold-email sequence offering a free 100-lead sample → convert to subscription. Add programmatic SEO landers (`"{niche} email list {year}"`).

---

# §2 Enterprise Desktop & Web RPA

## 2.1 Hardened PyAutoGUI Driver (Desktop)

```python
# rpa/desktop_bot.py
import time, random, json, pathlib
import pyautogui
pyautogui.FAILSAFE = True          # slam mouse to corner = emergency stop
pyautogui.PAUSE = 0.02             # we manage pacing ourselves

class DesktopBot:
    def __init__(self, evidence_dir="artifacts"):
        self.evd = pathlib.Path(evidence_dir); self.evd.mkdir(exist_ok=True)
        self.log: list[dict] = []

    # ---- perception -------------------------------------------------------
    def find(self, image: str, timeout=15, conf=0.86) -> tuple[int,int]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            box = pyautogui.locateOnScreen(image, confidence=conf, grayscale=True)
            if box: return pyautogui.center(box)
            time.sleep(0.25)
        self.evidence(f"MISS_{pathlib.Path(image).stem}")
        raise LookupError(f"template not found: {image}")

    # ---- actuation (humanized) --------------------------------------------
    def click_target(self, xy: tuple[int,int], spread=4):
        x, y = xy
        px, py = x + random.randint(-spread, spread), y + random.randint(-spread, spread)
        pyautogui.moveTo(px, py, duration=random.uniform(0.18, 0.45),
                         tween=pyautogui.easeOutQuad)
        pyautogui.click(button=random.choices(["left","left","left","right"],
                                              weights=[97,0,0,3])[0])

    def click_image(self, image, **kw): self.click_target(self.find(image, **kw))

    def type_text(self, text: str, tab_first=True):
        if tab_first: pyautogui.press("tab"); time.sleep(random.uniform(.08,.2))
        for ch in text:
            pyautogui.press(ch) if ch.isalnum() else pyautogui.hotkey(*([]) ) or pyautogui.write(ch, interval=0.001)
            time.sleep(random.uniform(0.045, 0.14))   # per-key jitter ≠ typewrite's flat interval
        pyautogui.press("enter")

    def scroll_until(self, image: str, max_scroll=25):
        for _ in range(max_scroll):
            try: return self.find(image, timeout=1.5)
            except LookupError: pyautogui.scroll(-450); time.sleep(0.3)
        raise LookupError(image)

    # ---- observability ------------------------------------------------------
    def evidence(self, tag: str):
        ts = time.strftime("%Y%m%d_%H%M%S")
        p = self.evd / f"{ts}_{tag}.png"
        pyautogui.screenshot(str(p))
        self.log.append({"t": ts, "event": tag, "shot": str(p)})
        (self.evd / "run.jsonl").open("a").write(json.dumps(self.log[-1]) + "\n")
```

> **Windows-native alternative:** prefer `pywinauto` (UIA backend) over pixels when the target exposes accessibility trees — deterministic handles, no resolution sensitivity. Reserve PyAutoGUI for legacy/VNC/Citrix surfaces.

## 2.2 DOM Store — Auto-Healing Selector Registry (Web RPA)

Selectors rot. Centralize them in a declarative store with **ordered fallback chains**, runtime healing, and hit-telemetry.

```yaml
# rpa/dom_store.yaml
erp.login.username:
  role: {type: textbox, name: "Username"}
  css:  ["#txtUserName", "input[name='user']", "form input[type=text]"]
  xpath:["//label[contains(.,'User')]/following::input[1]"]

erp.login.password:
  role: {type: textbox, name: "Password"}
  css:  ["#txtPassword", "input[type=password]"]

erp.login.submit:
  css:  ["#btnLogin", "button[type=submit]"]
  iframe: ["frame#mainFrame", "iframe[name=content]"]   # nested-frame aware
```

```python
# rpa/dom_store.py
import yaml, json, time
from dataclasses import dataclass, field

@dataclass
class Entry:
    role: dict | None = None
    css: list[str] = field(default_factory=list)
    xpath: list[str] = field(default_factory=list)
    iframe: list[str] = field(default_factory=list)

class DOMStore:
    def __init__(self, path="rpa/dom_store.yaml", telemetry_path="rpa/store_hits.jsonl"):
        self.entries = {k: Entry(**v) for k, v in yaml.safe_load(open(path)).items()}
        self.last_good: dict[str, str] = {}
        self.telemetry_path = telemetry_path

    def candidates(self, key: str) -> list[tuple[str, object]]:
        e = self.entries[key]; out = []
        if key in self.last_good: out.append(("last_good", self.last_good[key]))
        if e.role: out.append(("role", e.role))
        out += [("css", c) for c in e.css] + [("xpath", x) for x in e.xpath]
        return out

    async def resolve(self, page, key: str, timeout=8.0):
        """Try strategies in priority order; heal store on fallback success."""
        for kind, spec in self.candidates(key):
            loc = self._locate(page, kind, spec)
            try:
                el = loc.first
                await el.wait_for(state="visible", timeout=timeout * 1000 / max(len(self.candidates(key)),1))
                if self.last_good.get(key) != f"{kind}:{spec!s}":
                    self._record(key, kind, spec, healed=key in self.last_good or kind != "last_good")
                    self.last_good[key] = f"{kind}:{spec!s}"
                return el
            except Exception:
                continue
        raise KeyError(f"all strategies failed for {key}")

    @staticmethod
    def _locate(page, kind, spec):
        if kind == "last_good":
            _, s = spec.split(":", 1); return DOMStore._locate(page, *DOMStore._parse(s))
        if kind == "role":
            return page.get_by_role(spec["type"], name=spec.get("name"), exact=False)
        if kind == "css":  return page.locator(spec)
        if kind == "xpath":return page.locator(f"xpath={spec}")
        raise ValueError(kind)

    @staticmethod
    def _parse(s: str):
        kind, rest = s.split("|", 1)
        return (kind, json.loads(rest)) if kind == "role" else (kind, rest)

    def _record(self, key, kind, spec, healed: bool):
        with open(self.telemetry_path, "a") as f:
            f.write(json.dumps({"ts": time.time(), "key": key, "strategy": kind,
                                "healed": healed, **({"spec": str(spec)})}) + "\n")
```

**IFrame injection** — chain `frame_locator` through arbitrary nesting:

```python
async def deep_frame(page, frame_specs: list[str]):
    fl = page
    for fs in frame_specs:
        fl = fl.frame_locator(fs)          # supports "iframe#id", "frame[name=x]", nth=
    return fl

# usage: resolve inside entry's declared iframe path
entry = store.entries["erp.login.submit"]
fl = await deep_frame(page, entry.iframe)
await fl.locator("#btnLogin").click()
```

## 2.3 ddddocr CAPTCHA Solver — Constrained, Gated, Retry-Safe

**Design rules that separate toys from production:**
1. **Constraint gate** — never submit a decode violating declared charset/length (a wrong guess burns the session).
2. **Rotate-on-fail** — always refetch a *fresh* image before retrying (most engines rotate per request).
3. **Confidence budget** — cap attempts; fall back to human-in-the-loop task queue.

```python
# rpa/captcha.py
import io, re
import ddddocr

class ConstraintError(ValueError): ...

class CaptchaSolver:
    def __init__(self, charset: str = r"[A-Za-z0-9]", length: tuple[int,int] = (4,6)):
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        self._slide: ddddocr.DdddOcr | None = None
        self.char_re = re.compile(charset)
        self.lo, self.hi = length

    def solve_text(self, png_bytes: bytes) -> str:
        raw = self.ocr.classification(png_bytes)
        cleaned = "".join(c for c in raw if self.char_re.fullmatch(c))
        if not (self.lo <= len(cleaned) <= self.hi):
            raise ConstraintError(f"decode '{raw}' violates charset/len gate ({cleaned!r})")
        return cleaned

    def solve_arithmetic(self, png_bytes: bytes) -> int:
        expr = self.solve_text(png_bytes)                      # e.g. "3+4=?"
        expr = expr.replace("?","").replace("=","").replace("×","*").replace("÷","/")
        if not re.fullmatch(r"[\d+\-*/()\s.]+", expr):          # hard sandbox: never eval raw
            raise ConstraintError(expr)
        return int(eval(expr))                                 # noqa: gated input above

    def solve_slider_offset(self, slider_png: bytes, bg_png: bytes) -> int:
        if self._slide is None:
            self._slide = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        res = self._slide.slide_match(slider_png, bg_png, simple_target=True)
        return res["target"][0]                                # left-edge x of gap
```

```python
# rpa/web_login_flow.py — full composite: DOM Store + iframe + OCR gate
import asyncio
from playwright.async_api import async_playwright
from rpa.dom_store import DOMStore
from rpa.captcha import CaptchaSolver, ConstraintError

store = DOMStore()
solver = CaptchaSolver(charset=r"\d", length=(4,4))   # site profile: exactly 4 digits

async def secure_login(base_url: str, user: str, pwd: str, max_attempts=4):
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch(headless=False)  # headed for desktop-RPA parity
        page = await (await ctx.new_context()).new_page()
        await page.goto(base_url, wait_until="domcontentloaded")

        await (await store.resolve(page, "erp.login.username")).fill(user)
        await (await store.resolve(page, "erp.login.password")).fill(pwd)

        for attempt in range(1, max_attempts + 1):
            cap_loc = await store.resolve(page, "erp.login.captcha_img")
            png = await cap_loc.screenshot()                    # element shot → exact bytes
            try:
                code = solver.solve_text(png)
            except ConstraintError as e:
                await page.reload(wait_until="domcontentloaded")  # rotate challenge
                continue
            await (await store.resolve(page, "erp.login.captcha_input")).fill(code)
            await (await store.resolve(page, "erp.login.submit")).click()
            err = page.locator("[class*=error],[class*=alert]")
            await page.wait_for_timeout(1200)
            if not await err.count():
                return page                                        # ✅ authenticated
            await cap_loc.screenshot(path=f"artifacts/fail_{attempt}.png")  # evidence
        raise RuntimeError("captcha budget exhausted → enqueue human review")
```

**Track `captcha_pass_ratio` as a first-class Prometheus metric** — degradation below 80 % usually means the target changed font/rendering, not model quality.

---

## §2 Monetization Workflow — "OpsPilot"

- **Model:** implementation fee ($2k–10k per process) + retainer ($300–1k/mo per bot fleet) or outcome pricing ($0.05–0.25/invoice processed).
- **Target ICP:** accounting firms, freight forwarders, property managers, hospital back-offices drowning in dual-entry between portals and ERPs.
- **Delivery loop:** free 2-week pilot on ONE process → measurable hours saved report (screenshots + timing logs from the evidence dir double as the ROI deck) → annual contract.
- **Moat:** the DOM Store + run-evidence artifacts become proprietary process documentation competitors can't replicate cheaply.

---

# §3 Conversational AI Secretary & Sales Gateway

## 3.1 Multi-Tenant Webhook Gateway (Telegram + LINE)

```python
# gateway/main.py
import os, hmac, hashlib, base64, json
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
import httpx, redis.asyncio as aioredis

app = FastAPI(title="secretary-gateway")
rds = aioredis.from_url(os.environ["REDIS_URL"])

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"
LINE_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

def verify_line(body: bytes, sig_header: str) -> None:
    mac = hmac.new(LINE_SECRET.encode(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(base64.b64encode(mac).decode(), sig_header):
        raise HTTPException(403, "bad signature")

@app.post("/webhooks/telegram/{secret}")
async def telegram_hook(secret: str, req: Request, bg: BackgroundTasks):
    if secret != os.environ["TG_WEBHOOK_SECRET"]: raise HTTPException(403)
    upd = await req.json()
    msg = upd.get("message") or upd.get("callback_query", {}).get("message")
    if msg:
        bg.add_task(process_message, "tg", str(msg["chat"]["id"]),
                    (upd["message"]["text"] if "message" in upd
                     else f"action:{upd['callback_query']['data']}"))
    return {"ok": True}

@app.post("/webhooks/line")
async def line_hook(req: Request, bg: BackgroundTasks):
    body = await req.body()
    verify_line(body, req.headers.get("X-Line-Signature", ""))
    events = json.loads(body)["events"]
    for ev in events:
        if ev["type"] == "message" and ev["message"]["type"] == "text":
            bg.add_task(process_message, "line", ev["source"]["userId"], ev["message"]["text"], ev["replyToken"])
    return {"ok": True}

async def process_message(channel: str, uid: str, text: str, reply_token: str | None = None):
    from gateway.agent import orchestrator
    outs = await orchestrator.handle(channel, uid, text)
    if channel == "tg":
        async with httpx.AsyncClient() as c:
            for o in outs:
                await c.post(f"{TG_API}/sendMessage", json={
                    "chat_id": uid, "text": o["text"], "parse_mode": "Markdown",
                    **({"reply_markup": o["kb"]} if o.get("kb") else {})})
    else:
        async with httpx.AsyncClient() as c:
            await c.post("https://api.line.me/v2/bot/message/reply",
                headers={"Authorization": f"Bearer {LINE_TOKEN}"},
                json={"replyToken": reply_token, "messages":
                      [{"type": "text", "text": o["text"]} for o in outs[:5]]})
```

## 3.2 Session Store + Funnel State Machine

```python
# gateway/session.py
import json, time, enum
STAGES = ["NEW","QUALIFYING","QUOTED","PAYMENT_PENDING","PAID","ONBOARDED"]
TRANSITIONS = {
  "NEW":{"QUALIFYING"}, "QUALIFYING":{"QUOTED","NEW"},
  "QUOTED":{"PAYMENT_PENDING","QUALIFYING"},
  "PAYMENT_PENDING":{"PAID","QUALIFYING"}, "PAID":{"ONBOARDED"},
}

class SessionStore:
    def __init__(self, rds): self.rds = rds
    def _k(self, ch, uid): return f"sess:{ch}:{uid}"
    async def load(self, ch, uid) -> dict:
        raw = await self.rds.get(self._k(ch, uid))
        s = json.loads(raw) if raw else {"stage":"NEW","msgs":[],"quote":None,"paid":False}
        return s
    async def save(self, ch, uid, s: dict, ttl=60*60*72):
        await self.rds.set(self._k(ch, uid), json.dumps(s, ensure_ascii=False), ex=ttl)
    async def advance(self, ch, uid, to: str):
        s = await self.load(ch, uid)
        assert to in TRANSITIONS[s["stage"]], f"illegal {s['stage']}→{to}"
        s["stage"] = to
        await self.rds.zadd("followups", {f"{ch}:{uid}": time.time() + 36*3600})  # nudge timer
        await self.save(ch, uid, s); return s
```

## 3.3 LLM Orchestrator with Tool Calling

```python
# gateway/agent.py
import json, os
from openai import AsyncOpenAI
from gateway.session import SessionStore

llm = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
MAX_TOOL_ROUNDS = 4

TOOLS = [
 {"type":"function","function":{
   "name":"create_checkout","description":"Create a Stripe subscription checkout link",
   "parameters":{"type":"object","properties":{
       "plan":{"enum":["pro","business"]},"email":{"type":"string"}},
     "required":["plan","email"]}}},
 {"type":"function","function":{
   "name":"issue_promptpay_qr","description":"Generate Thai PromptPay QR for one-time invoice",
   "parameters":{"type":"object","properties":{
       "amount_thb":{"type":"number"},"memo":{"type":"string"}},"required":["amount_thb"]}}},
 {"type":"function","function":{
   "name":"book_demo","description":"Book a sales call slot",
   "parameters":{"type":"object","properties":{
       "slot_iso":{"type":"string"},"topic":{"type":"string"}},"required":["slot_iso"]}}},
 {"type":"function","function":{
   "name":"escalate_human","description":"Hand off to human operator",
   "parameters":{"type":"object","properties":{"reason":{"type":"string"}},"required":["reason"]}}},
]

SYSTEM = """You are Sara, the sales & operations secretary. Qualify leads (use case, team size,
budget timeline), quote plans, then drive to payment. Be concise (<120 words), warm, and always
end with one concrete next step. Never invent prices — call tools."""

class Orchestrator:
    def __init__(self, store: SessionStore):
        self.store = store

    async def dispatch(self, ch, uid, name: str, args: dict) -> dict:
        if name == "create_checkout":
            from gateway.billing import stripe_checkout
            url = stripe_checkout(plan=args["plan"], email=args["email"], uid=f"{ch}:{uid}")
            await self.store.advance(ch, uid, "PAYMENT_PENDING")
            return {"url": url, "kb_tg": {"inline_keyboard":[[{"text":"Pay securely 💳","url":url}]]}}
        if name == "issue_promptpay_qr":
            from gateway.billing import promptpay_png_b64
            await self.store.advance(ch, uid, "PAYMENT_PENDING")
            return {"qr_b64": promptpay_png_b64(args["amount_thb"]), "text": "Scan to pay via PromptPay 🇹🇭"}
        if name == "book_demo":
            await self.store.advance(ch, uid, "QUOTED")
            return {"confirmed": args["slot_iso"]}
        if name == "escalate_human":
            from gateway.notify import pager_duty
            await pager_duty(f"{ch}:{uid}: {args['reason']}")
            return {"status": "operator notified"}
        return {"error": "unknown tool"}

    async def handle(self, ch, uid, text) -> list[dict]:
        s = await self.store.load(ch, uid)
        msgs = ([{"role":"system","content":SYSTEM}] +
                s["msgs"][-14:] + [{"role":"user","content":text}])
        outputs: list[dict] = []
        for _ in range(MAX_TOOL_ROUNDS):
            resp = await llm.chat.completions.create(model=os.environ.get("LLM_MODEL","gpt-4o-mini"),
                                                     messages=msgs, tools=TOOLS)
            m = resp.choices[0].message
            if m.tool_calls:
                msgs.append(m.model_dump())
                for tc in m.tool_calls:
                    result = await self.dispatch(ch, uid, tc.function.name,
                                                 json.loads(tc.function.arguments))
                    outputs.append(result)
                    msgs.append({"role":"tool","tool_call_id":tc.id,
                                 "content": json.dumps({k:v for k,v in result.items() if k!="qr_b64"})})
                continue
            msgs.append({"role":"assistant","content":m.content})
            outputs.insert(0, {"text": m.content}); break
        s["msgs"] = msgs[1:]
        await self.store.save(ch, uid, s)
        return outputs

orchestrator = Orchestrator(SessionStore(None))  # wire rds in DI at startup
```

## 3.4 Billing: Stripe Subscriptions + PromptPay QR (EMVCo-compliant)

```python
# gateway/billing.py
import os, io, re, base64, qrcode, stripe
import httpx
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
PRICE_IDS = {"pro": os.environ["PRICE_PRO"], "business": os.environ["PRICE_BUSINESS"]}

def stripe_checkout(plan: str, email: str, uid: str) -> str:
    s = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=email,
        line_items=[{"price": PRICE_IDS[plan], "quantity": 1}],
        metadata={"internal_uid": uid},
        success_url=os.environ["SUCCESS_URL"]+"?sid={CHECKOUT_SESSION_ID}",
        cancel_url=os.environ["CANCEL_URL"],
    )
    return s.url

@app_webhook := None  # registered separately in main.py:
# @app.post("/stripe/webhook")
# async def stripe_wh(req: Request):
#     event = stripe.Webhook.construct_event(await req.body(),
#                req.headers["stripe-signature"], os.environ["STRIPE_WHSEC"])
#     if event.type == "checkout.session.completed":
#         uid = event.data.object.metadata["internal_uid"]
#         ch, ident = uid.split(":", 1)
#         await session_store.advance(ch, ident, "PAID")
#         → provision workspace, send onboarding DM

# ---------------- PromptPay (Thai EMVCo MPM) ----------------
def _tlv(tag: str, val: str) -> str:
    return f"{tag}{len(val):02d}{val}"

def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for b in data.encode():
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"

def promptpay_payload(target: str, amount: float | None = None) -> str:
    t = re.sub(r"[\s\-]", "", target)
    if   re.fullmatch(r"0\d{9}", t):   acct = "00" + "66" + t[1:]   # mobile → 66 prefix
    elif re.fullmatch(r"\d{13}", t):   acct = "01" + t              # citizen ID
    elif re.fullmatch(r"\d{15}", t):   acct = "03" + t              # e-wallet
    else: raise ValueError("unsupported PromptPay target")
    tag29 = _tlv("29", _tlv("00", "A000000677010111") + _tlv("01", acct))
    p  = _tlv("00","01") + _tlv("01", "12" if amount else "11") + tag29
    p += _tlv("53","764")
    if amount: p += _tlv("54", f"{amount:.2f}")
    p += _tlv("58","TH") + "6304"
    return p + crc16_ccitt(p)

def promptpay_png_b64(amount: float, target: str | None = None) -> str:
    tgt = target or os.environ["PROMPTPAY_ID"]
    buf = io.BytesIO()
    qrcode.make(promptpay_payload(tgt, amount), box_size=8).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
```

**Follow-up nudge worker** (recovers stalled deals):

```python
# workers/followups.py
import time, json, redis
rds = redis.Redis.from_url("redis://redis:6379/0")
NUDGE = {"QUALIFYING": "Still evaluating? Want me to send the 2-min ROI sheet?",
         "PAYMENT_PENDING": "Your checkout link expires soon — want a PromptPay QR instead?"}

async def run_forever():
    while True:
        items = await rds.zrangebyscore("followups", "-inf", time.time(), start=0, num=20)
        for item in items:
            ch, uid = item.decode().split(":", 1)
            s = json.loads(await rds.get(f"sess:{item.decode()}") or "{}")
            if txt := NUDGE.get(s.get("stage")):
                await deliver(ch, uid, txt)          # same sender as gateway
            await rds.zrem("followups", item)
        await asyncio.sleep(60)
```

---

## §3 Monetization Workflow — "SaraAI Secretary"

| Plan | Price/mo | Limits | Marginal cost |
|---|---|---|---|
| Free | $0 | 100 msgs, 1 channel | ~$0.06 |
| Pro | $19 | Unlimited chat, calendar booking, 1 Stripe product | ~$0.40 |
| Business | $79 | Multi-agent, invoicing + PromptPay, CRM sync, human escalation SLA | ~$1.50 |

- **Metering:** increment `msg_count:{uid}` in Redis per turn; hard-stop at tier quota with upsell CTA.
- **Channels = distribution:** Telegram Mini-App listing + LINE Official Account partner marketplace (TH/JP/TW). Verticalize: clinics (appointment + deposit via PromptPay), real estate agents (lead qualify + viewing bookings), tutoring centers.
- **Key lever:** the *tool calls themselves* are the product surface — each added integration (Google Calendar, Zoho, Shopee order lookup) raises willingness-to-pay faster than model upgrades do.

---

# §4 Production Templates & Ops Baseline

## 4.1 Repository Layout

```
platform/
├── app/
│   ├── config.py            # pydantic-settings, typed env
│   ├── db.py                # asyncpg pool + migrations
│   ├── engine/              # §1 crawler package
│   ├── rpa/                 # §2 package
│   ├── gateway/             # §3 FastAPI app
│   └── workers/             # arq tasks (harvest, enrich, followups, provisioning)
├── tests/                   # pytest + respx (HTTP mocks) + fake-LLM fixture
├── infra/docker-compose.yml
├── pyproject.toml
└── Makefile
```

```python
# app/config.py
from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://app:app@postgres/app"
    stripe_secret_key: str; stripe_whsec: str
    tg_bot_token: str; tg_webhook_secret: str
    line_channel_secret: str; line_channel_access_token: str
    promptpay_id: str
    llm_model: str = "gpt-4o-mini"; openai_api_key: str
    max_global_concurrency: int = 8
    class Config: env_file = ".env"
settings = Settings()
```

```python
# app/workers/__init__.py — arq wiring (single worker image runs all task groups)
from arq.connections import RedisSettings
from app.config import settings

async def startup(ctx): 
    ctx["pool"] = await make_pg_pool(); ctx["http"] = make_httpx()
WorkerSettings = dict(
    functions=[harvest_domain, enrich_lead, provision_paid_user],
    redis_settings=RedisSettings(host="redis"),
    on_startup=startup, max_jobs=10, job_timeout=600,
)
```

```yaml
# infra/docker-compose.yml
services:
  redis:    { image: redis:7-alpine, command: redis-server --appendonly yes }
  postgres: { image: postgres:16-alpine, environment: {POSTGRES_USER: app, POSTGRES_PASSWORD: app, POSTGRES_DB: app}, volumes: [pgdata:/var/lib/postgresql/data] }
  api:      { build: ., command: uvicorn app.gateway.main:app --host 0.0.0.0 --port 8000, env_file: ../.env, depends_on: [redis, postgres] }
  worker:   { build: ., command: arq app.workers.WorkerSettings, env_file: ../.env, depends_on: [redis, postgres] }
  scraper:  { build: {context: .., dockerfile: infra/Dockerfile.scraper}, shm_size: "1gb", env_file: ../.env }  # Playwright + Xvfb
volumes: { pgdata: {} }
```

## 4.2 Observability You Will Actually Use

```python
# app/metrics.py
from prometheus_client import Counter, Histogram
SCRAPE_TOTAL   = Counter("scrape_requests_total", "pages fetched", ["domain","verdict"])
CAPTCHA_PASS   = Counter("captcha_attempts_total", "captcha outcomes", ["result"])  # pass|gate_fail|exhausted
TOOL_CALLS     = Counter("agent_tool_calls_total", "LLM tool invocations", ["tool","channel"])
FUNNEL_STAGE   = Counter("funnel_transitions_total", "stage moves", ["from","to"])
LATENCY        = Histogram("gateway_latency_seconds", "webhook e2e", buckets=[0.5,1,2,5,10])
```

Alert rules worth paging on: `rate(scrape_requests_total{verdict="block"}[10m]) / rate(...total[10m]) > 0.3` → rotate pool/region; `captcha_pass ratio < 0.75/15m` → site changed; `funnel PAYMENT_PENDING aging > 48h count > 10` → billing friction.

## 4.3 Reliability Patterns (non-negotiable)

```python
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

@retry(stop=stop_after_attempt(4), wait=wait_exponential_jitter(1, 30),
       retry=retry_if_exception_type((httpx.TransportError, TimeoutError)))
async def resilient_post(url: str, **kw): ...
```

- **Idempotency everywhere:** Stripe `metadata.internal_uid`, lead `fp` unique index, RPA runs keyed `(process_id, business_date)` — safe re-runs are what let you sleep.
- **Secrets:** env-injected at runtime (compose secrets / AWS SSM), never in images; rotate proxy credentials quarterly.
- **Testing:** `respx` mocks for LINE/TG/Stripe; golden-file fixtures of captured XHR payloads for parser regression tests; a `fake-llm` ASGI app returning scripted tool_calls for gateway CI.

---

# §5 Risk Register & Compliance Guardrails

| Risk | Control |
|---|---|
| Target-site ToS violations / legal exposure | Scrape only public data, honor opt-outs, maintain per-domain allowlist reviewed by counsel; never circumvent authentication or paywalls |
| PII in lead data (GDPR/PDPA — critical for LINE markets) | Store minimum viable fields, lawful-basis tagging, documented erasure pipeline (`DELETE FROM leads WHERE fp=$1` exposed as internal API) |
| Email outreach reputation | Verified-MX-only sends, SPF/DKIM/DMARC on sending domains, CAN-SPAM unsubscribe footer, warm-up schedules |
| CAPTCHA automation legality | Deploy OCR solver **only** against systems you own or are contractually licensed to automate (your own QA environments, client-owned ERPs with written authorization); enterprise RPA vendors require this clause |
| Platform bans (TG/LINE) | Use official Bot APIs exclusively; rate-limit broadcasts; never buy/spam-add users |
| Payment disputes | Stripe Radar + hosted Checkout (SAQ-A scope); PromptPay = bank-guaranteed push, zero chargeback |

**Scale sequence:** single VPS → compose split (scraper nodes isolated, GPU-free) → K8s with KEDA autoscaling on queue depth → regional proxy egress matching customer geography.

---

**Build order recommendation (fastest path to revenue):** ship §3 first (2-week MVP, recurring revenue from day one) → reinvest into §1 as a productized data service (cash-flow engine) → package §2 wins from consulting engagements into licensed bots. Each module feeds the others' distribution: leads power outreach, outreach sells the secretary, the secretary books the RPA demos.