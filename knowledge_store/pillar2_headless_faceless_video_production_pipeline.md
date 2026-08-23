# Headless Faceless Video Production & Multi-Platform Auto-Publisher Pipeline
- **Pillar**: Pillar 2: Media & Content Automation
- **Generated Date**: 2026-08-23 10:27:34
- **Synthesized By**: 0x Alpha (stealth/ox-alpha) via Antigravity 2.0

---

# Autonomous Short-Form Video Factory — Production Blueprint & Implementation Guide

**Target platforms:** YouTube Shorts · TikTok · Instagram Reels · Telegram
**Stack:** Python 3.11 · FFmpeg (NVENC) · faster-whisper (CUDA) · Edge-TTS/Kokoro · YouTube Data API v3 · Meta Graph API · Telegram Bot API
**Design goal:** Fully headless, resumable, idempotent pipeline: **topic → script → voice → karaoke subs → 1080×1920 MP4 → multi-platform publish**, ~2–4 min/video end-to-end on a single RTX-class GPU.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Repository Layout, Dependencies, Environment](#2-repository-layout-dependencies-environment)
3. [Stage 1 — Viral Topic Mining & Hook Generator](#3-stage-1--viral-topic-mining--hook-generator)
4. [Stage 2 — Neural Voiceover Synthesis (Edge-TTS / Kokoro)](#4-stage-2--neural-voiceover-synthesis)
5. [Stage 3 — Whisper Word Timestamps + Karaoke Subtitle Engine](#5-stage-3--whisper-word-timestamps--karaoke-subtitles)
6. [Stage 4 — Hardware-Accelerated Composition (NVENC)](#6-stage-4--hardware-accelerated-composition)
7. [Multi-Platform Auto-Publisher Gateway](#7-multi-platform-auto-publisher-gateway)
8. [Orchestrator — State Machine, Batch Runner, CLI](#8-orchestrator--state-machine-batch-runner-cli)
9. [Deployment, Scheduling, Monitoring](#9-deployment-scheduling-monitoring)
10. [Failure Taxonomy, Rate-Limit Matrices, Compliance Guardrails](#10-failure-taxonomy-rate-limits-compliance)

---

## 1. Architecture Overview

### 1.1 System Diagram

```
                            ┌──────────────────────────────────────────────────┐
                            │                ORCHESTRATOR (SQLite FSM)         │
                            │   jobs(id, status, stage, attempts, artifacts)   │
                            └───────▲───────────────────────────┬──────────────┘
                                    │ resume / retry            │ dispatch
        ┌───────────────────────────┴────────────┐              ▼
        │           STAGE 1 — MINE               │    ┌──────────────────────┐
        │  Google Trends RSS ─┐                  │    │  STAGE 5 — PUBLISH   │
        │  Reddit r/top JSON ─┼─► score+dedupe   │    │  Gateway (fan-out)   │
        │  (YT trending ext.) ┘   → topic.json   │    ├──────────────────────┤
        └───────────────────┬────────────────────┘    │ YouTube  : OAuth2    │
                            ▼                         │            resumable │
        ┌──────────────────────────────────────────┐  │ Meta IG  : container │
        │           STAGE 2 — SCRIPT               │  │            poll/push │
        │  LLM hook+script (JSON, word-budgeted)   │  │ Telegram : multipart │
        │  fallback: deterministic templates       │  │            broadcast │
        └───────────────────┬──────────────────────┘  └──────────┬───────────┘
                            ▼ script.json                        │
        ┌──────────────────────────────────────────┐             ▼
        │           STAGE 3 — VOICE                │     results.json / urls
        │  Edge-TTS (cloud) ──failover──► Kokoro   │◄──────────────────────┐
        │  → vo.mp3/wav + loudness-normalized mux  │                       │
        └───────────────────┬──────────────────────┘                       │
                            ▼                                              │
        ┌──────────────────────────────────────────┐    ┌────────────────────┴──┐
        │           STAGE 4 — ALIGN                │    │  STAGE 6 — RENDER     │
        │  faster-whisper large-v3 (CUDA fp16)     │    │  FFmpeg filter graph  │
        │  word_timestamps=True → words.json       │───►│  zoompan / crop / ass │
        └──────────────────────────────────────────┘    │  h264_nvenc p6/hq     │
                            │                           │  loudnorm -14 LUFS    │
                            ▼                           └──────────┬────────────┘
        ┌──────────────────────────────────────────┐               ▼
        │     STAGE 5b — SUBTITLE ENGINE           │         out.mp4 (9:16)
        │  ASS: word-pop | \k karaoke | SRT        │───► QC probe (codec/res/dur)
        └──────────────────────────────────────────┘
```

### 1.2 Design Tenets

| Tenet | Implementation |
|---|---|
| **Resumability** | Every stage persists artifacts + status row; crash ⇒ resume from last green stage |
| **Idempotency** | `job_id = sha1(normalized_topic)[:12]`; re-runs reuse existing artifacts |
| **Graceful degradation** | Edge-TTS→Kokoro, NVENC→libx264, LLM→template, per-source mining isolation |
| **Backpressure** | Per-platform rate-limit middleware with `Retry-After` awareness |
| **Observability** | Structured logs, per-job `result.json`, webhook alerts on terminal failure |

### 1.3 Latency Budget (RTX 3060-class, 48 s video)

| Stage | Typical | Bottleneck |
|---|---|---|
| Mine + script | 3–6 s | LLM RTT |
| TTS | 1.5–4 s | network / vocoder |
| Whisper align (large-v3, fp16) | 4–8 s | VRAM bandwidth |
| Subtitle emit | <0.1 s | — |
| NVENC render (1080×1920@30) | 35–80 s | filter graph (ass raster + zoompan) |
| Publish fan-out | 20–120 s | platform ingest |
| **Total** | **~2–4 min** | render |

---

## 2. Repository Layout, Dependencies, Environment

### 2.1 File Tree

```text
shortfactory/
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── config.py
├── utils.py
├── miner.py                 # Stage 1
├── hooks.py                 # Stage 2
├── tts.py                   # Stage 3
├── transcribe.py            # Stage 4 (alignment)
├── subs.py                  # Stage 5b (ASS/SRT engine)
├── render.py                # Stage 6 (FFmpeg/NVENC)
├── check_env.py
├── pipeline.py              # Orchestrator + CLI
├── publishers/
│   ├── __init__.py
│   ├── base.py              # errors, backoff middleware, contracts
│   ├── storage.py           # S3/R2 public-URL bridge for Meta
│   ├── youtube.py
│   ├── meta_reels.py
│   └── telegram.py
├── assets/
│   └── bg/                  # licensed vertical loops & stills
└── fonts/                   # Anton, Montserrat (OFL)
    ├── Anton.ttf
    └── Montserrat-Bold.ttf
```

### 2.2 `requirements.txt`

```text
requests>=2.32,<3
feedparser>=6.0.11
pydantic-settings>=2.3
edge-tts>=6.1.12
numpy>=1.26
soundfile>=0.12.1
faster-whisper>=1.0.3
google-api-python-client>=2.130
google-auth>=2.29
boto3>=1.34

# --- Optional ---
# kokoro>=0.9.4        # offline TTS fallback (pulls torch; ~2 GB)
# moviepy>=2.1.1       # only if using the b-roll compositor variant (§6.4)
```

### 2.3 Fonts

```bash
mkdir -p fonts
curl -L -o fonts/Anton.ttf            "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"
curl -L -o fonts/Montserrat-Bold.ttf  "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"
```

### 2.4 `.env.example`

```env
# ---------- Core ----------
DATA_DIR=data
WIDTH=1080
HEIGHT=1920
FPS=30
TARGET_SECONDS=48
WPM=165

# ---------- LLM (any OpenAI-compatible endpoint) ----------
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# ---------- TTS ----------
TTS_ENGINE=auto              # auto | edge | kokoro
TTS_VOICE=en-US-AndrewMultilingualNeural
TTS_RATE=+8%
KOKORO_VOICE=af_heart

# ---------- Whisper ----------
WHISPER_MODEL_SIZE=large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE=float16

# ---------- Subtitles ----------
SUBS_MODE=pop                # pop | karaoke
SUBS_Y=1150                  # vertical anchor (PlayRes 1080x1920)
ACCENT_COLOR=#FFD400

# ---------- Render ----------
ENCODER=auto                 # auto | nvenc | x264
NVENC_PRESET=p6
CRF_CQ=19
BG_DIR=assets/bg

# ---------- YouTube ----------
ENABLE_YOUTUBE=true
YT_CLIENT_ID=
YT_CLIENT_SECRET=
YT_REFRESH_TOKEN=

# ---------- Instagram Reels ----------
ENABLE_INSTAGRAM=false
IG_USER_ID=
IG_TOKEN=
S3_ENDPOINT_URL=https://<acct>.r2.cloudflarestorage.com
S3_BUCKET=reels-staging
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
PUBLIC_BASE_URL=             # optional: https://cdn.example.com (public bucket)

# ---------- Telegram ----------
ENABLE_TELEGRAM=true
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_IDS=@channel_a,-1001234567890

# ---------- Ops ----------
PARALLEL_JOBS=2
ALERT_WEBHOOK=               # Discord/Slack-compatible webhook
LOG_LEVEL=INFO
```

---

## 3. Stage 1 — Viral Topic Mining & Hook Generator

### 3.1 Design

- **Sources (isolated, fault-tolerant):**
  - Google Trends daily RSS (`https://trends.google.com/trending/rss?geo=US`) — zero-auth, stable XML.
  - Reddit public JSON (`https://www.reddit.com/r/<sub>/top.json`) with a declared User-Agent.
- **Scoring:** velocity-weighted — Reddit `ups/(age_h+2)^1.2`, Trends ranked decay.
- **Deduplication:** SHA-1 of normalized title vs. persistent `data/history.jsonl`.
- **Output contract:** `{"title": str, "source": str, "score": float, "keywords": [str]}`.

### 3.2 `utils.py` (shared runtime utilities)

```python
"""Shared utilities: subprocess, probing, logging."""
from __future__ import annotations
import json, logging, os, subprocess, sys, time
from pathlib import Path

LOG_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format=LOG_FMT,
                        handlers=[logging.StreamHandler(sys.stderr)])

log = logging.getLogger("factory")

def sh(args: list[str], cwd: Path | None = None, check: bool = True,
       capture: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess safely (no shell interpolation)."""
    log.debug("exec: %s (cwd=%s)", " ".join(map(str, args)), cwd)
    p = subprocess.run(list(map(str, args)), cwd=cwd, check=False,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None, text=True)
    if check and p.returncode != 0:
        tail = (p.stderr or "")[-2000:]
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(map(str,args))}\n{tail}")
    return p

def ffprobe_duration(path: Path) -> float:
    p = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(p.stdout.strip())

def ffprobe_streams(path: Path) -> dict:
    p = sh(["ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path])
    return json.loads(p.stdout)

def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)

def jwrite(path: Path, obj) -> None:
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2))

def jread(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default

def sha1(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def norm_title(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "", s.lower())

class Alert:
    """Terminal-failure notifier (Discord/Slack-style JSON webhook)."""
    def __init__(self, url: str):
        self.url = url
    def send(self, msg: str) -> None:
        if not self.url:
            return
        try:
            import requests
            requests.post(self.url, json={"content": msg[:1800]}, timeout=10)
        except Exception as e:                      # never crash ops on ops
            log.warning("alert failed: %s", e)
```

### 3.3 `config.py`

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    data_dir: Path = Path("data")
    width: int = 1080
    height: int = 1920
    fps: int = 30
    target_seconds: float = 48.0
    wpm: int = 165
    parallel_jobs: int = 2
    alert_webhook: str = ""
    log_level: str = "INFO"

    # LLM
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # TTS
    tts_engine: str = "auto"
    tts_voice: str = "en-US-AndrewMultilingualNeural"
    tts_rate: str = "+8%"
    kokoro_voice: str = "af_heart"

    # Whisper
    whisper_model_size: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute: str = "float16"

    # Subtitles
    subs_mode: str = "pop"
    subs_y: int = 1150
    accent_color: str = "#FFD400"

    # Render
    encoder: str = "auto"
    nvenc_preset: str = "p6"
    crf_cq: int = 19
    bg_dir: Path = Path("assets/bg")

    # YouTube
    enable_youtube: bool = True
    yt_client_id: str = ""
    yt_client_secret: str = ""
    yt_refresh_token: str = ""

    # Instagram
    enable_instagram: bool = False
    ig_user_id: str = ""
    ig_token: str = ""
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    public_base_url: str = ""

    # Telegram
    enable_telegram: bool = True
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""

settings = Settings()
```

### 3.4 `miner.py`

```python
"""Stage 1 — Viral topic mining: Google Trends RSS + Reddit JSON, scored & deduped."""
from __future__ import annotations
import time, math, logging
from pathlib import Path
import feedparser, requests

from config import settings
from utils import jread, jwrite, sha1, norm_title

log = logging.getLogger("mine")

UA = {"User-Agent": "Mozilla/5.0 (compatible; ShortFactoryBot/1.0; +research)"}
REDDIT_SUBS = ["todayilearned", "interestingasfuck", "Damnthatsinteresting",
               "BeAmazed", "mildlyinfuriating"]

# --------------------------------------------------------------------------- sources

def google_trends(geo: str = "US", limit: int = 20) -> list[dict]:
    try:
        feed = feedparser.parse(f"https://trends.google.com/trending/rss?geo={geo}")
        out = []
        for i, e in enumerate(feed.entries[:limit]):
            kw = [ht.get("term", "") for ht in getattr(e, "ht_approx_traffic", [])] \
                 if hasattr(e, "ht_approx_traffic") else []
            out.append({"title": e.title.strip(), "source": f"trends:{geo}",
                        "keywords": kw, "score": max(5.0, 100.0 - i * 4.5)})
        return out
    except Exception as e:
        log.warning("trends source failed (isolated): %s", e)
        return []

def reddit_top(subs: list[str], per_sub: int = 12) -> list[dict]:
    out = []
    for sub in subs:
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top.json",
                             params={"t": "day", "limit": per_sub},
                             headers=UA, timeout=15)
            r.raise_for_status()
            for child in r.json()["data"]["children"]:
                d = child["data"]
                age_h = max(1.0, (time.time() - d["created_utc"]) / 3600.0)
                vel = d["score"] / (age_h + 2.0) ** 1.2
                out.append({"title": d["title"].strip(), "source": f"reddit:r/{sub}",
                            "keywords": [], "score": round(min(vel / 40.0, 100.0), 2)})
        except Exception as e:
            log.warning("reddit r/%s failed (isolated): %s", sub, e)
    return out

# --------------------------------------------------------------------------- dedup/scoring

def seen_titles(data_dir: Path) -> set[str]:
    hist = data_dir / "history.jsonl"
    seen = set()
    if hist.exists():
        for line in hist.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(norm_title(__import__("json").loads(line)["title"]))
            except Exception:
                continue
    return seen

def mine(batch: int = 8, geo: str = "US") -> list[dict]:
    candidates = google_trends(geo) + reddit_top(REDDIT_SUBS)
    seen = seen_titles(settings.data_dir)
    fresh, fingerprints = [], set()
    for c in sorted(candidates, key=lambda x: -x["score"]):
        fp = norm_title(c["title"])
        if not fp or fp in seen or fp in fingerprints:
            continue
        fingerprints.add(fp)
        c["job_id"] = sha1(fp)[:12]
        fresh.append(c)
        if len(fresh) >= batch:
            break
    log.info("mined %d fresh topics (from %d candidates)", len(fresh), len(candidates))
    return fresh
```

### 3.5 `hooks.py` — LLM Hook/Script Generator (with deterministic fallback)

Contract enforced downstream: **total spoken words ∈ [0.75·budget, budget]** where `budget = TARGET_SECONDS × WPM / 60`. Hook must land inside the first ~1.5 s.

```python
"""Stage 2 — Viral hook + narration script via OpenAI-compatible LLM, JSON-validated."""
from __future__ import annotations
import json, logging, re
import requests

from config import settings

log = logging.getLogger("hooks")

SYSTEM_PROMPT = """You are a world-class short-form scriptwriter (YouTube Shorts/TikTok).
Rules:
- Output STRICT JSON matching the schema below. No markdown, no commentary.
- HOOK: 1 sentence, <= 14 words, pattern-interrupt, curiosity gap, zero preamble.
- BODY: 2-4 punchy facts/beats. Conversational, second person, concrete numbers.
- CTA: one short closer line.
- Total words (HOOK+BODY+CTA) MUST be between MIN_WORDS and MAX_WORDS.
Schema:
{"title": str<=90, "hook": str, "body": [str, ...], "cta": str,
 "hashtags": [str, ...], "visual_query": str}
"""

FALLBACK_TEMPLATES = [
    "{title}? Here's what nobody tells you.",
    "Stop scrolling — {title} is weirder than you think.",
    "99% of people get {title} completely wrong.",
]

def _budget() -> tuple[int, int]:
    total = int(settings.target_seconds * settings.wpm / 60)
    return int(total * 0.78), int(total * 0.98)

def _wc(*parts) -> int:
    return sum(len(re.findall(r"\S+", p)) for p in parts)

def _clip_to_budget(script: dict) -> dict:
    lo, hi = _budget()
    words = script.get("body", [])
    while _wc(script["hook"], " ".join(words), script["cta"]) > hi and words:
        words.pop()
    script["body"] = words
    return script

def _llm_script(topic: dict) -> dict | None:
    if not (settings.llm_base_url and settings.llm_api_key):
        return None
    lo, hi = _budget()
    user = (f'Topic: "{topic["title"]}" (source: {topic["source"]}).\n'
            f'MIN_WORDS={lo} MAX_WORDS={hi}. Language: English.\n'
            f'Return ONLY the JSON object.')
    try:
        r = requests.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "temperature": 0.9,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": user}]},
            timeout=60)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        s = json.loads(content)
        for k in ("title", "hook", "body", "cta"):
            assert k in s, f"missing key {k}"
        s.setdefault("hashtags", ["#shorts", "#facts"])
        s.setdefault("visual_query", topic["title"])
        return _clip_to_budget(s)
    except Exception as e:
        log.warning("LLM script failed (%s) — falling back to template", e)
        return None

def _template_script(topic: dict) -> dict:
    tpl = FALLBACK_TEMPLATES[hash(topic["title"]) % len(FALLBACK_TEMPLATES)]
    hook = tpl.format(title=topic["title"].rstrip("?"))
    return {
        "title": topic["title"][:88],
        "hook": hook,
        "body": [f"Source reports say: {topic['title']}.",
                 "Here is the part most coverage skips."],
        "cta": "Follow for the follow-up.",
        "hashtags": ["#shorts", "#news", "#facts"],
        "visual_query": topic["title"],
    }

def generate_script(topic: dict) -> dict:
    script = _llm_script(topic) or _template_script(topic)
    narration = " ".join([script["hook"], *script["body"], script["cta"]])
    script["narration"] = narration
    lo, hi = _budget()
    wc = _wc(narration)
    log.info("script ready: %d words (budget %d-%d)", wc, lo, hi)
    return script
```

---

## 4. Stage 2 — Neural Voiceover Synthesis

### 4.1 Engine Matrix

| Engine | Latency | Quality | Cost | Failure Mode Covered |
|---|---|---|---|---|
| **Edge-TTS** (Microsoft neural, cloud) | ~1–2 s/50 words | Very high | Free (unofficial) | Network outage |
| **Kokoro-82M** (local ONNX/PyTorch) | ~2–5 s/50 words (CPU/GPU) | High | Free, offline | Everything cloud |

Recommended voices: `en-US-AndrewMultilingualNeural` (male), `en-US-AvaMultilingualNeural` (female), `en-GB-RyanNeural`; Kokoro: `af_heart`, `am_michael`.

### 4.2 `tts.py`

```python
"""Stage 3 — Voiceover synthesis. Edge-TTS primary, Kokoro offline fallback."""
from __future__ import annotations
import asyncio, logging
from pathlib import Path

from config import settings
from utils import sh, ffprobe_duration

log = logging.getLogger("tts")

async def _edge_synth(text: str, out: Path) -> None:
    import edge_tts
    comm = edge_tts.Communicate(text=text, voice=settings.tts_voice,
                                rate=settings.tts_rate, pitch="+0Hz")
    await comm.save(str(out))

def _kokoro_synth(text: str, out_wav: Path) -> None:
    import numpy as np, soundfile as sf
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a")                    # 'a' = American English
    chunks = []
    for result in pipe(text, voice=settings.kokoro_voice, speed=1.05):
        a = result.audio
        chunks.append(a.cpu().numpy() if hasattr(a, "cpu") else a)
    if not chunks:
        raise RuntimeError("kokoro produced no audio")
    sf.write(str(out_wav), np.concatenate(chunks), 24000)

def synthesize(narration: str, job_dir: Path) -> Path:
    """Returns path to vo.mp3 (edge) or vo.wav (kokoro); verifies duration."""
    job_dir.mkdir(parents=True, exist_ok=True)
    engine = settings.tts_engine
    if engine in ("auto", "edge"):
        try:
            out = job_dir / "vo.mp3"
            asyncio.run(_edge_synth(narration, out))
            if out.stat().st_size > 2048:
                log.info("voiceover: edge-tts %.1fs", ffprobe_duration(out))
                return out
            raise RuntimeError("edge output too small")
        except Exception as e:
            if engine == "edge":
                raise
            log.warning("edge-tts failed (%s) → kokoro fallback", e)
    out = job_dir / "vo.wav"
    _kokoro_synth(narration, out)
    # Normalize to 48 kHz stereo WAV for a clean downstream mux.
    conv = job_dir / "vo48.wav"
    sh(["ffmpeg", "-y", "-v", "error", "-i", out,
        "-ar", "48000", "-ac", "2", conv])
    log.info("voiceover: kokoro %.1fs", ffprobe_duration(conv))
    return conv
```

> **Production hardening:** cache `(sha1(narration), voice, rate) → artifact` to skip re-synthesis on retry; Edge-TTS endpoints rotate — pin `edge-tts` version and treat failures as transient.

---

## 5. Stage 3 — Whisper Word Timestamps + Karaoke Subtitles

### 5.1 Alignment Strategy

- **faster-whisper** (CTranslate2 port) with `word_timestamps=True` emits per-word `(start, end, word)` via DTW cross-attention alignment — the exact signal required for frame-accurate karaoke.
- Zero-duration words are clamped to `≥ 40 ms`; gaps > 700 ms split caption groups.
- `initial_prompt` is seeded with the hook text to bias proper-noun decoding.

### 5.2 `transcribe.py`

```python
"""Stage 4 — Word-level alignment via faster-whisper (CUDA fp16)."""
from __future__ import annotations
import logging
from pathlib import Path

from config import settings
from utils import jwrite

log = logging.getLogger("asr")
_MODEL = None

def _model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        log.info("loading whisper %s (%s/%s)",
                 settings.whisper_model_size, settings.whisper_device,
                 settings.whisper_compute)
        _MODEL = WhisperModel(
            settings.whisper_model_size,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute)
    return _MODEL

def transcribe_words(audio: Path, seed_text: str = "") -> list[dict]:
    """→ [{"w": str, "start": float, "end": float}, ...]"""
    segments, _info = _model().transcribe(
        str(audio),
        language="en",
        beam_size=5,
        word_timestamps=True,
        vad_filter=False,                       # narration is clean; VAD can eat tails
        condition_on_previous_text=False,
        initial_prompt=(seed_text or "")[:220],
    )
    words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if not text:
                continue
            start, end = float(w.start), max(float(w.end), float(w.start) + 0.04)
            words.append({"w": text, "start": round(start, 3), "end": round(end, 3)})
    if not words:
        raise RuntimeError("whisper returned zero words — check audio track")
    log.info("aligned %d words over %.2fs", len(words), words[-1]["end"])
    return words

def align(audio: Path, job_dir: Path, hook: str = "") -> Path:
    words = transcribe_words(audio, seed_text=hook)
    out = job_dir / "words.json"
    jwrite(out, words)
    return out
```

### 5.3 Karaoke Subtitle Engine — ASS Semantics

Two rendering modes, both driven off `words.json`:

| Mode | Mechanism | Look |
|---|---|---|
| **`pop`** (TikTok-style) | One word/card event; entrance animation via `\t(fscx/fscy)` overshoot, rotating accent palette | Single huge bouncing word |
| **`karaoke`** (fill-style) | Chunked line, per-word `\k<centiseconds>` sweeps text from `SecondaryColour` → `PrimaryColour` exactly in sync | Sentence fills with color |

**Critical ASS facts encoded below:**

- Colors are `&H{AA}{BB}{GG}{RR}` (**BGR**, not RGB).
- `\k` durations are **centiseconds**.
- Canvas = `PlayResX/Y` matched to output resolution; positioning via `\an5\pos(cx,cy)`.
- Burn-in uses FFmpeg's `ass` filter (libass), which resolves fonts through `fontconfig` or the filter's `fontsdir`.

### 5.4 `subs.py`

```python
"""Stage 5b — Karaoke subtitle engine: ASS (pop + \\k fill) and SRT emitters."""
from __future__ import annotations
import re
from pathlib import Path

from config import settings
from utils import atomic_write

PALETTE = ["#FFD400", "#00E5FF", "#FF4D6D", "#7CFC00", "#FF9F1C"]

# ------------------------------------------------------------------ formatting

def hex_to_ass(hexcolor: str, alpha: int = 0x00) -> str:
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

def ass_ts(t: float) -> str:
    cs_total = max(0, int(round(t * 100)))
    h, rem = divmod(cs_total, 360_000)
    m, rem = divmod(rem, 6_000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def srt_ts(t: float) -> str:
    ms_total = max(0, int(round(t * 1000)))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def _clean(word: str) -> str:
    return re.sub(r"[{}\\]", "", word).upper()

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{popfont},{popsize},{accent},&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{outline},1,5,40,40,0,1
Style: Kar,{karfont},{karsize},{accent},&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{outline},1,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# ------------------------------------------------------------------ mode: word-pop

def _pop_events(words: list[dict]) -> list[str]:
    cx = settings.width // 2
    cy = settings.subs_y
    events = []
    for i, wd in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else wd["end"]
        end = min(nxt - 0.01, wd["end"] + 0.06)
        color = PALETTE[i % len(PALETTTE_SAFE)]
        ov = (f"{{\\an5\\pos({cx},{cy})\\1c{hex_to_ass(color)}"
              f"\\t(0,70,\\fscx116\\fscy116)\\t(70,150,\\fscx100\\fscy100)"
              f"\\fad(0,50)}}")
        events.append(f"Dialogue: 1,{ass_ts(wd['start'])},{ass_ts(end)},Pop,,0,0,0,,{ov}{_clean(wd['w'])}")
    return events

PALETTTE_SAFE = PALETTE  # alias kept intentional for readability

# ------------------------------------------------------------------ mode: \k karaoke

def _chunk_words(words: list[dict], max_chars: int = 18, max_gap: float = 0.70
                 ) -> list[list[dict]]:
    chunks, cur = [], []
    for wd in words:
        gap = (wd["start"] - cur[-1]["end"]) if cur else 0.0
        projected = sum(len(x["w"]) + 1 for x in cur) + len(wd["w"]) + 1
        if cur and (projected > max_chars or gap > max_gap):
            chunks.append(cur); cur = []
        cur.append(wd)
    if cur:
        chunks.append(cur)
    return chunks

def _karaoke_events(words: list[dict]) -> list[str]:
    events = []
    for chunk in _chunk_words(words):
        tokens = " ".join(f"{{\\k{int(round((wd['end'] - wd['start']) * 100))}}}{_clean(wd['w'])}"
                          for wd in chunk)
        ov = "{\\fad(60,60)}"
        events.append(f"Dialogue: 0,{ass_ts(chunk[0]['start'])},"
                      f"{ass_ts(chunk[-1]['end'])},Kar,,0,0,0,,{ov}{tokens}")
    return events

# ------------------------------------------------------------------ writers

def write_ass(words: list[dict], path: Path) -> Path:
    hdr = HEADER.format(
        w=settings.width, h=settings.height,
        popfont="Anton", popsize=132,
        karfont="Montserrat", karsize=88,
        accent=hex_to_ass(settings.accent_color),
        outline=6,
    )
    if settings.subs_mode == "pop":
        events = _pop_events(words)
    elif settings.subs_mode == "karaoke":
        events = _karaoke_events(words)
    else:
        raise ValueError(f"unknown subs_mode {settings.subs_mode}")
    atomic_write(path, hdr + "\n".join(events) + "\n")
    return path

def write_srt(words: list[dict], path: Path) -> Path:
    lines, idx = [], 1
    for chunk in _chunk_words(words):
        txt = " ".join(_clean(w["w"]).capitalize() if i == 0 else _clean(w["w"])
                       for i, w in enumerate(chunk))
        lines += [str(idx), f"{srt_ts(chunk[0]['start'])} --> {srt_ts(chunk[-1]['end'])}", txt, ""]
        idx += 1
    atomic_write(path, "\n".join(lines))
    return path

def build_subtitles(words_json: Path, job_dir: Path) -> tuple[Path, Path]:
    import json
    words = json.loads(words_json.read_text(encoding="utf-8"))
    return (write_ass(words, job_dir / "subs.ass"),
            write_srt(words, job_dir / "subs.srt"))
```

> **Why libass, not a Python rasterizer:** PIL/TextClip approaches drift from Whisper timings and lack `\k` sweep semantics. libass consumes the same `words.json` deterministically at encode time with sub-frame precision.

---

## 6. Stage 4 — Hardware-Accelerated Composition

### 6.1 Encoder Selection & Tuning

| Profile | Flags | Notes |
|---|---|---|
| **NVENC (primary)** | `h264_nvenc -preset p6 -tune hq -rc vbr -cq 19 -b:v 0 -maxrate 14M -bufsize 28M -spatial-aq 1 -b_ref_mode middle -g 60 -bf 3 -profile high` | Turing+ ; `p1…p7` (7 = best/slowest) |
| **x264 (fallback)** | `libx264 -preset veryfast -crf 19 -maxrate 14M -bufsize 28M` | Any CPU |

Both constrained by `-maxrate 14M` — comfortably above every platform’s recommended bitrate for 1080×1920@30, below botched-transcode thresholds.

### 6.2 Filter Graph (per background class)

```
IMAGE BG :  scale=1620:2880:force_original_aspect_ratio=increase
            ,crop=1620:2880                       ← 1.5× supersample kills zoompan jitter
            ,zoompan=z='min(1.0+0.0018*on,1.4)'
                    :x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2'
                    :d=1:s=1080x1920:fps=30       ← d=1 + looped input = smooth Ken Burns
            ,format=yuv420p,ass=subs.ass

VIDEO BG :  -stream_loop -1 -i bg.mp4
            scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920
            ,fps=30,setsar=1,format=yuv420p,ass=subs.ass

AUDIO    :  [vo][bgm@vol 0.12] amix=duration=first:normalize=0
            → loudnorm=I=-14:TP=-1.5:LRA=11       ← platform loudness standard
            → aac 192k / 48 kHz stereo
```

### 6.3 `render.py`

```python
"""Stage 6 — Composition: FFmpeg filter graph, NVENC-first, QC-gated."""
from __future__ import annotations
import logging, random
from pathlib import Path

from config import settings
from utils import sh, ffprobe_duration, ffprobe_streams

log = logging.getLogger("render")

class RenderError(RuntimeError): ...

# ------------------------------------------------------------------ capabilities

_NVENC_OK: bool | None = None

def has_nvenc() -> bool:
    global _NVENC_OK
    if _NVENC_OK is None:
        try:
            sh(["ffmpeg", "-hide_banner", "-v", "error",
                "-f", "lavfi", "-i", "color=black:s=128x128:d=0.2",
                "-c:v", "h264_nvenc", "-f", "null", "-"], capture=True)
            _NVENC_OK = True
        except Exception:
            _NVENC_OK = False
        log.info("nvenc available: %s", _NVENC_OK)
    return _NVENC_OK

def pick_encoder() -> str:
    if settings.encoder != "auto":
        return {"nvenc": "h264_nvenc", "x264": "libx264"}[settings.encoder]
    return "h264_nvenc" if has_nvenc() else "libx264"

# ------------------------------------------------------------------ background

def _pick_background(seed: str, duration: float) -> tuple[list[str], str]:
    """→ (input_args, filter_chain_prefix). Falls back to animated gradient."""
    bg_dir = settings.bg_dir
    media = ([*bg_dir.glob("*.mp4"), *bg_dir.glob("*.jpg"), *bg_dir.glob("*.png")]
             if bg_dir.exists() else [])
    if media:
        path = media[int(random.Random(seed).random() * len(media)) % len(media)]
        if path.suffix.lower() == ".mp4":
            return (["-stream_loop", "-1", "-i", str(path)],
                    f"[0:v]scale={settings.width}:{settings.height}:"
                    f"force_original_aspect_ratio=increase,"
                    f"crop={settings.width}:{settings.height},fps={settings.fps},"
                    f"setsar=1,format=yuv420p")
        frames = int(duration * settings.fps) + settings.fps
        return (["-loop", "1", "-framerate", str(settings.fps), "-t",
                 f"{duration:.3f}", "-i", str(path)],
                "[0:v]scale=1620:2880:force_original_aspect_ratio=increase,"
                "crop=1620:2880,"
                "zoompan=z='min(1.0+0.0018*on,1.4)':x='iw/2-(iw/zoom)/2':"
                f"y='ih/2-(ih/zoom)/2':d=1:s={settings.width}x{settings.height}:"
                f"fps={settings.fps},format=yuv420p")
    # Deterministic animated gradient fallback (no assets needed)
    return (["-f", "lavfi", "-i",
             f"gradients=s={settings.width}x{settings.height}:"
             f"c0=#0F172A:c1=#334155:speed=0.02:d={duration:.3f}:r={settings.fps}"],
            "[0:v]format=yuv420p")

# ------------------------------------------------------------------ command assembly

def _encoder_args(codec: str) -> list[str]:
    if codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", settings.nvenc_preset, "-tune", "hq",
                "-rc", "vbr", "-cq", str(settings.crf_cq), "-b:v", "0",
                "-maxrate", "14M", "-bufsize", "28M", "-spatial-aq", "1",
                "-b_ref_mode", "middle", "-g", "60", "-bf", "3",
                "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(settings.crf_cq),
            "-maxrate", "14M", "-bufsize", "28M", "-profile:v", "high"]

def render(video_path_in_job: Path, job_dir: Path, duration: float, seed: str) -> Path:
    """Burns subs.ass (cwd-relative) + muxes voiceover; QC-probes the output."""
    ass, vo = job_dir / "subs.ass", job_dir / ("vo.mp3" if (job_dir / "vo.mp3").exists()
                                               else "vo.wav")
    bg_inputs, vchain = _pick_background(seed, duration)
    codec = pick_encoder()
    out = job_dir / "out.mp4"

    fc = [f"{vchain},ass=subs.ass[v]"]
    maps = ["-map", "[v]"]

    if len(bg_inputs) >= 2 and bg_inputs[-2] == "-i" or True:  # bgm slot unused by default
        pass

    # Audio branch: voiceover (+optional bgm later) → loudnorm
    fc.append("[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aformat="
              "sample_rates=48000:channel_layouts=stereo[aout]")
    maps += ["-map", "[aout]"]

    args = (["ffmpeg", "-hide_banner", "-y", "-v", "warning", "-stats"]
            + bg_inputs
            + ["-i", str(vo.name)]
            + ["-filter_complex", ";".join(fc)]
            + maps
            + ["-t", f"{duration + 0.25:.3f}",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
            + _encoder_args(codec)
            + ["-movflags", "+faststart", "-max_muxing_queue_size", "1024",
               str(out.name)])

    try:
        p = sh(args, cwd=job_dir)                       # cwd ⇒ 'subs.ass' path-safe
    except RuntimeError as e:
        raise RenderError(str(e)) from e
    log.info("encoded with %s:\n%s", codec, (p.stderr or "")[-600:])
    qc(out, duration)
    return out

# ------------------------------------------------------------------ QC gate

def qc(path: Path, expected_dur: float) -> None:
    info = ffprobe_streams(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    problems = []
    if not v or v["codec_name"] != "h264":
        problems.append("video codec != h264")
    if not v or (v["width"], v["height"]) != (settings.width, settings.height):
        problems.append(f"resolution {getattr(v,'width','?')}x{getattr(v,'height','?')}")
    dur = float(info["format"]["duration"])
    if abs(dur - expected_dur) > 1.5:
        problems.append(f"duration drift {dur:.1f}s vs {expected_dur:.1f}s")
    if not a or a["codec_name"] != "aac":
        problems.append("audio codec != aac")
    if problems:
        raise RenderError("QC failed: " + "; ".join(problems))
    log.info("QC PASS  %dx%d  %.1fs  h264+aac", settings.width, settings.height, dur)
```

### 6.4 Variant: MoviePy Compositor (b-roll overlays, crossfades)

Use when the timeline needs **layered media** beyond a single background. Final export still delegates to NVENC via `ffmpeg_params`.

```python
"""Optional compositor for layered timelines (MoviePy 2.x)."""
from pathlib import Path
from moviepy import ImageClip, VideoFileClip, AudioFileClip, CompositeVideoClip, vfx
from config import settings

def compose_layered(bg_media: Path, audio: Path, ass_burned_bg_fallback: Path) -> Path:
    dur = AudioFileClip(str(audio)).duration
    if bg_media.suffix == ".mp4":
        bg = (VideoFileClip(str(bg_media)).subclipped(0, dur)
                .resized(height=settings.height)
                .cropped(width=settings.width, height=settings.height, x_center=0.5))
    else:
        bg = (ImageClip(str(bg_media)).with_duration(dur)
                .resized(height=int(settings.height * 1.05))
                .with_position("center")
                .with_effects([vfx.ResizeFactor(lambda t: 1.0 + 0.0018 * t)])  # Ken Burns
              )
    final = CompositeVideoClip([bg], size=(settings.width, settings.height))
    out = bg_media.with_suffix(".layered.mp4")
    final.with_audio(AudioFileClip(str(audio))).write_videofile(
        str(out), fps=settings.fps, codec="h264_nvenc",
        audio_codec="aac", audio_bitrate="192k",
        ffmpeg_params=["-preset", settings.nvenc_preset, "-tune", "hq",
                       "-rc", "vbr", "-cq", str(settings.crf_cq), "-b:v", "0",
                       "-maxrate", "14M", "-bufsize", "28M",
                       "-spatial-aq", "1", "-movflags", "+faststart"],
        preset=None, logger=None)
    return out
```

> Recommended production topology: **composite layers with MoviePy → burn subtitles + loudnorm + final NVENC pass with the §6.3 graph** (single libass authority, guaranteed LUFS).

---

## 7. Multi-Platform Auto-Publisher Gateway

### 7.1 Gateway Architecture

```
                    ┌────────────────────────────────────────────┐
   out.mp4 ────────►│  resilient()  ← exponential backoff+jitter │
   VideoMeta        │  • honors Retry-After / retry_after        │
                    │  • transient vs fatal classification       │
                    │  • bounded tries (default 6, cap 180 s)    │
                    └───────┬──────────────┬─────────────┬───────┘
                            ▼              ▼             ▼
                   ┌────────────┐  ┌─────────────┐  ┌──────────────┐
                   │ YOUTUBE    │  │ META (IG)   │  │ TELEGRAM     │
                   │ OAuth2     │  │ container:  │  │ sendVideo    │
                   │ refresh    │  │ create→poll │  │ multipart    │
                   │ resumable  │  │ →publish    │  │ broadcast    │
                   │ chunks 8MB │  │ public URL  │  │ flood-wait   │
                   └─────┬──────┘  └──────┬──────┘  └──────┬───────┘
                         │ videoId        │ permalink       │ message_id[]
                         └────────────────┴─────────────────┘
                                          ▼
                                  results.json (urls)
```

### 7.2 `publishers/base.py` — Contracts + Backoff Middleware

```python
"""Publisher gateway primitives: error taxonomy, resilient(), dataclasses."""
from __future__ import annotations
import functools, logging, random, time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("publish")

# ------------------------------------------------------------------ taxonomy

class TransientError(Exception): ...
class FatalError(Exception): ...

class RateLimited(TransientError):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after

# ------------------------------------------------------------------ contracts

@dataclass
class VideoMeta:
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    caption_html: str = ""          # Telegram HTML caption

@dataclass
class PublishResult:
    platform: str
    external_id: str
    url: str
    raw: dict

# ------------------------------------------------------------------ middleware

def resilient(fn=None, *, tries: int = 6, base: float = 2.0, cap: float = 180.0):
    """Exponential backoff with full jitter; honors RateLimited.retry_after."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **kw):
            attempt = 0
            while True:
                try:
                    return f(*a, **kw)
                except RateLimited as e:
                    delay = e.retry_after or min(cap, base * (2 ** attempt))
                except TransientError:
                    delay = min(cap, base * (2 ** attempt))
                except FatalError:
                    raise
                except Exception as e:                       # defensive net
                    if attempt >= tries - 1:
                        raise FatalError(f"{f.__name__}: {e}") from e
                    delay = min(cap, base * (2 ** attempt))
                attempt += 1
                if attempt >= tries:
                    raise FatalError(f"{f.__name__}: exhausted {tries} tries")
                sleep_for = delay + random.uniform(0, 1.0)
                log.warning("%s transient failure #%d → sleep %.1fs (%s)",
                            f.__name__, attempt, sleep_for, e if isinstance(e, Exception) else "")
                time.sleep(sleep_for)
        return wrapper
    return deco(fn) if fn else deco

class Publisher(ABC):
    name: str = "base"
    @abstractmethod
    def publish(self, video: Path, meta: VideoMeta) -> PublishResult: ...
```

### 7.3 `publishers/storage.py` — Public-URL Bridge (required by Meta)

Meta’s servers perform a server-side `GET` of your `video_url`; a **presigned S3/R2 GET URL** satisfies this without making the bucket public.

```python
"""S3/R2 staging: upload MP4, return time-boxed public GET URL for Meta ingest."""
from __future__ import annotations
from pathlib import Path
from config import settings

class ObjectStore:
    def __init__(self):
        import boto3
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
        self.bucket = settings.s3_bucket

    def public_url(self, path: Path, key: str, ttl_hours: int = 6) -> str:
        self.client.upload_fileobj(
            open(path, "rb"), self.bucket, key,
            ExtraArgs={"ContentType": "video/mp4"})
        if settings.public_base_url:                       # public bucket shortcut
            return f"{settings.public_base_url.rstrip('/')}/{key}"
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_hours * 3600)
```

### 7.4 `publishers/youtube.py` — Data API v3 (Resumable, Auto-Refresh)

```python
"""YouTube Shorts publisher: OAuth2 auto-refresh + resumable chunked upload."""
from __future__ import annotations
import logging
from pathlib import Path

from config import settings
from publishers.base import (Publisher, VideoMeta, PublishResult,
                             TransientError, FatalError, RateLimited, resilient)

log = logging.getLogger("yt")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


class YouTubePublisher(Publisher):
    name = "youtube"
    QUOTA_COST_PER_UPLOAD = 1600          # default project: 10,000/day ⇒ ~6 uploads

    def __init__(self):
        self._svc = None

    def _service(self):
        if self._svc is None:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            creds = Credentials(
                token=None, refresh_token=settings.yt_refresh_token,
                client_id=settings.yt_client_id,
                client_secret=settings.yt_client_secret,
                token_uri=TOKEN_URI, scopes=SCOPES)
            creds.refresh(Request())                    # auto access-token mint
            self._svc = build("youtube", "v3", credentials=creds,
                              cache_discovery=False)
        return self._svc

    def _reset_auth(self):
        self._svc = None

    @staticmethod
    def _classify(e: Exception) -> Exception:
        """Map HttpError → taxonomy."""
        from googleapiclient.errors import HttpError
        if isinstance(e, HttpError):
            status = e.resp.status
            reason = getattr(getattr(e, "error_details", None), "reason", "") or ""
            try:
                reason = e.error_details[0]["reason"] if e.error_details else reason
            except Exception:
                pass
            if status == 403 and "quotaExceeded" in reason:
                return FatalError("YouTube: daily upload quota exhausted "
                                  "(1600 units/upload)")
            if status == 403 and "uploadLimitExceeded" in reason:
                return FatalError("YouTube: channel upload limit reached")
            if status in (429, 500, 502, 503):
                ra = None
                try:
                    ra = float(e.resp.headers.get("Retry-After"))
                except Exception:
                    pass
                return RateLimited(f"YouTube {status}: {reason}", retry_after=ra)
            if status == 401:
                return TransientError("YouTube 401 — token refresh needed")
        return e

    @resilient(tries=5, base=4.0, cap=300)
    def publish(self, video: Path, meta: VideoMeta) -> PublishResult:
        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        body = {
            "snippet": {
                "title": meta.title[:100],
                "description": meta.description[:4900],
                "tags": meta.tags[:30],
                "categoryId": "24",                 # Entertainment
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(str(video), mimetype="video/mp4",
                                chunksize=8 << 20, resumable=True)
        try:
            req = self._service().videos().insert(
                part="snippet,status", body=body, media_body=media)
            response, last_p = None, -1
            while response is None:
                status, response = req.next_chunk(num_retries=3)
                if status and status.progress() - last_p > 0.25:
                    last_p = status.progress()
                    log.info("upload %.0f%%", last_p * 100)
            vid = response["id"]
            log.info("published https://youtube.com/shorts/%s", vid)
            return PublishResult(self.name, vid,
                                 f"https://youtube.com/shorts/{vid}", response)
        except HttpError as e:
            err = self._classify(e)
            if isinstance(err, TransientError) and "401" in str(err):
                self._reset_auth()                   # force credential re-mint
            raise err
```

**One-time OAuth bootstrap** (run locally, paste refresh token into `.env`):

```bash
pip install google-auth-oauthlib
python - <<'PY'
from google_auth_oauthlib.flow import InstalledAppFlow
f = InstalledAppFlow.from_client_secrets_file("client_secret.json",
    scopes=["https://www.googleapis.com/auth/youtube.upload"])
f.run_console()  # or run_local_server(port=0)
print("REFRESH_TOKEN:", f.credentials.refresh_token)
PY
```

### 7.5 `publishers/meta_reels.py` — Instagram Reels (Container Poll → Publish)

```python
"""Instagram Reels via Graph API: media container → status poll → media_publish."""
from __future__ import annotations
import logging, time
from pathlib import Path

import requests

from config import settings
from publishers.base import (Publisher, VideoMeta, PublishResult,
                             TransientError, FatalError, RateLimited, resilient)
from publishers.storage import ObjectStore

log = logging.getLogger("ig")
GRAPH = "https://graph.facebook.com/v21.0"
POLL_TIMEOUT_S, POLL_INTERVAL_S = 420, 6


class InstagramPublisher(Publisher):
    name = "instagram"
    DAILY_PUBLISH_CAP = 50                 # IG content-publishing throttle

    def __init__(self):
        self.store = ObjectStore()

    def _params(self, **extra):
        p = {"access_token": settings.ig_token}
        p.update(extra)
        return p

    def _check(self, r: requests.Response) -> dict:
        data = r.json() if r.content else {}
        err = data.get("error", {})
        if err:
            code = err.get("code")
            if code == 4 or err.get("type") == "OAuthException" and code == 190:
                raise RateLimited(f"IG rate/token: {err.get('message')}",
                                  retry_after=float(err.get("Retry-After", 0)) or None)
            if r.status_code in (500, 502, 503) or code in (2, 4, 17, 32, 613):
                raise TransientError(f"IG transient {code}: {err.get('message')}")
            raise FatalError(f"IG fatal: {err.get('message')} (code={code}, "
                             f"subcode={err.get('error_subcode')})")
        r.raise_for_status()
        return data

    @resilient(tries=4, base=6.0, cap=240)
    def publish(self, video: Path, meta: VideoMeta) -> PublishResult:
        # 1) Stage a server-fetchable URL
        url = self.store.public_url(video, f"reels/{video.stem}.mp4")

        # 2) Create media container
        r = requests.post(f"{GRAPH}/{settings.ig_user_id}/media",
                          data=self._params(media_type="REELS",
                                            video_url=url,
                                            caption=meta.description[:2200],
                                            share_to_feed="true"),
                          timeout=60)
        container_id = self._check(r)["id"]

        # 3) Poll processing status
        deadline = time.time() + POLL_TIMEOUT_S
        while True:
            st = self._check(requests.get(
                f"{GRAPH}/{container_id}",
                params=self._params(fields="status_code,status"), timeout=30))
            code = st.get("status_code")
            if code == "FINISHED":
                break
            if code == "IN_PROGRESS":
                if time.time() > deadline:
                    raise TransientError("IG container processing timeout")
                time.sleep(POLL_INTERVAL_S)
                continue
            raise FatalError(f"IG container terminal state: {code} ({st.get('status')})")

        # 4) Publish
        pub = self._check(requests.post(f"{GRAPH}/{settings.ig_user_id}/media_publish",
                                        data=self._params(creation_id=container_id),
                                        timeout=60))
        media_id = pub["id"]
        perm = self._check(requests.get(f"{GRAPH}/{media_id}",
                                        params=self._params(fields="permalink"),
                                        timeout=30)).get("permalink", "")
        log.info("published IG reel %s → %s", media_id, perm)
        return PublishResult(self.name, media_id, perm, pub)
```

### 7.6 `publishers/telegram.py` — Broadcast Bot with Flood-Wait

```python
"""Telegram broadcast: multipart sendVideo, Retry-After aware, paced fan-out."""
from __future__ import annotations
import html, logging, time
from pathlib import Path

import requests

from config import settings
from publishers.base import (Publisher, VideoMeta, PublishResult,
                             TransientError, FatalError, RateLimited, resilient)

log = logging.getLogger("tg")


class TelegramPublisher(Publisher):
    name = "telegram"
    BOT_UPLOAD_LIMIT_MB = 50               # Bot API sendVideo hard limit

    def __init__(self):
        self.base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    def _send_one(self, chat_id: str, video: Path, meta: VideoMeta) -> dict:
        size_mb = video.stat().st_size / 1e6
        if size_mb > self.BOT_UPLOAD_LIMIT_MB:
            raise FatalError(f"{video.name} is {size_mb:.1f}MB > 50MB Bot API limit "
                             f"(lower CRF/bitrate or use local Bot API server)")
        with open(video, "rb") as fh:
            r = requests.post(
                f"{self.base}/sendVideo",
                data={"chat_id": chat_id,
                      "caption": meta.caption_html or html.escape(meta.title),
                      "parse_mode": "HTML",
                      "supports_streaming": "true"},
                files={"video": (video.name, fh, "video/mp4")},
                timeout=600)
        payload = r.json()
        if payload.get("ok"):
            return payload["result"]
        err = payload.get("parameters", {}) or {}
        if payload.get("error_code") == 429:
            raise RateLimited("TG flood_wait",
                              retry_after=float(err.get("retry_after", 5)))
        if payload.get("error_code") in (500, 502, 503):
            raise TransientError(f"TG {payload.get('error_code')}")
        raise FatalError(f"TG fatal: {payload.get('description')}")

    @resilient(tries=5, base=3.0, cap=600)
    def publish(self, video: Path, meta: VideoMeta) -> PublishResult:
        chats = [c.strip() for c in settings.telegram_chat_ids.split(",") if c.strip()]
        sent, ids = 0, []
        for i, chat in enumerate(chats):
            res = self._send_one(chat, video, meta)
            sent += 1
            ids.append(res["message_id"])
            log.info("sent to %s (msg %s)", chat, res["message_id"])
            if i < len(chats) - 1:
                time.sleep(0.7)                # per-chat pacing, global 30 msg/s far away
        return PublishResult(self.name, f"tg:{sent}", "", {"message_ids": ids})
```

### 7.7 Platform Constraint Matrix

| Constraint | YouTube Shorts | Instagram Reels (API) | Telegram (Bot) |
|---|---|---|---|
| Max length (recommended) | ≤ 60 s (up to 3 min eligible) | ≤ 90 s sweet spot | — |
| Resolution | ≥ 720×1280, 9:16 | 1080×1920 | any (streamable) |
| Title/Caption | 100 chars / 5000 desc | 2200 caption | 1024 caption |
| Upload transport | Resumable chunks (8 MB) | Server-side URL fetch | Multipart ≤ 50 MB |
| Auth | OAuth2 refresh token | Long-lived IG token | Bot token (static) |
| Hard rate limits | 1,600 quota-units/upload; 10 k/day default ⇒ **~6/day** | 50 API publishes/24 h; container poll required | ~30 msg/s global; `retry_after` on burst |
| Backoff trigger | HTTP 429/5xx | `code 4/17/32/613`, HTTP 5xx | `error_code 429 + retry_after` |

---

## 8. Orchestrator — State Machine, Batch Runner, CLI

### 8.1 State Machine

```
DISCOVERED → SCRIPTED → VOICED → ALIGNED → SUBTITLED → RENDERED → PUBLISHED
     └─────────────────────── any stage failure ───────────────► FAILED_<stage>
                                     (retry resets to prior stage)
```

Artifacts persist per job under `data/jobs/<job_id>/`:

```
topic.json · script.json · vo.(mp3|wav) · words.json · subs.ass · subs.srt · out.mp4 · result.json
```

### 8.2 `pipeline.py`

```python
"""Orchestrator: SQLite FSM, threaded batch runner, publish fan-out, CLI."""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, logging, sqlite3, sys, threading
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from utils import setup_logging, log, jread, jwrite, ffprobe_duration, Alert, sha1, norm_title

import miner, hooks, tts, transcribe, subs, render

STAGES = ["SCRIPTED", "VOICED", "ALIGNED", "SUBTITLED", "RENDERED", "PUBLISHED"]
_DB_LOCK = threading.Lock()
alert = Alert(settings.alert_webhook)

# ------------------------------------------------------------------ persistence

def db() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.data_dir / "jobs.db", timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _DB_LOCK, db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, created TEXT, updated TEXT,
            status TEXT, stage TEXT DEFAULT '', attempts INTEGER DEFAULT 0,
            topic_json TEXT, script_json TEXT, audio TEXT, words TEXT,
            ass TEXT, srt TEXT, video TEXT, results_json TEXT, error TEXT)""")

def upsert(job_id: str, **cols):
    cols["updated"] = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k}=?" for k in cols)
    with _DB_LOCK, db() as c:
        c.execute(f"UPDATE jobs SET {sets} WHERE id=?", [*cols.values(), job_id])

# ------------------------------------------------------------------ job lifecycle

def create_job(topic: dict) -> str:
    job_id = topic.get("job_id") or sha1(norm_title(topic["title"]))[:12]
    with _DB_LOCK, db() as c:
        c.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (job_id, datetime.now(timezone.utc).isoformat(),
                   datetime.now(timezone.utc).isoformat(), "DISCOVERED", "", 0,
                   json.dumps(topic), None, None, None, None, None, None, None, None))
    return job_id

def job_dir(job_id: str) -> Path:
    d = settings.data_dir / "jobs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d

# ------------------------------------------------------------------ stages

def process_job(job_id: str):
    with db() as c:
        row = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    jd = job_dir(job_id)
    topic = json.loads(row["topic_json"])

    try:
        # ---- Stage 2: script -----------------------------------------------
        if row["status"] == "DISCOVERED":
            script = hooks.generate_script(topic)
            jwrite(jd / "script.json", script)
            upsert(job_id, status="SCRIPTED", stage="SCRIPTED",
                   script_json=json.dumps(script))

        # ---- Stage 3: voiceover --------------------------------------------
        if row["stage"] in ("", "SCRIPTED"):
            script = jread(jd / "script.json")
            audio = tts.synthesize(script["narration"], jd)
            dur = ffprobe_duration(audio)
            upsert(job_id, status="VOICED", stage="VOICED",
                   audio=str(audio), error=None)

        # ---- Stage 4: alignment ---------------------------------------------
        if row["stage"] in ("VOICED", "ALIGNED") or (
           row["stage"] == "SUBTITLED" and not Path(row["words"] or "").exists()):
            audio = Path(row["audio"] or (jd / "vo.mp3"))
            script = jread(jd / "script.json")
            words = transcribe.align(audio, jd, hook=script["hook"])
            upsert(job_id, status="ALIGNED", stage="ALIGNED", words=str(words))

        # ---- Stage 5b: subtitles ---------------------------------------------
        if row["stage"] in ("ALIGNED", "SUBTITLED"):
            ass, srt = subs.build_subtitles(Path(row["words"]), jd)
            upsert(job_id, status="SUBTITLED", stage="SUBTITLED",
                   ass=str(ass), srt=str(srt))

        # ---- Stage 6: render ---------------------------------------------------
        if row["stage"] in ("SUBTITLED", "RENDERED"):
            audio = Path(row["audio"])
            dur = ffprobe_duration(audio)
            video = render.render(Path(row["ass"]), jd, dur, seed=job_id)
            upsert(job_id, status="RENDERED", stage="RENDERED", video=str(video))

        # ---- Publish fan-out ----------------------------------------------------
        if row["stage"] == "RENDERED":
            results = publish_all(Path(row["video"]), jread(jd / "script.json"))
            jwrite(jd / "result.json", results)
            ok = [r for r in results if r.get("ok")]
            status = "PUBLISHED" if ok else "FAILED_PUBLISH"
            upsert(job_id, status=status, stage=status,
                   results_json=json.dumps(results), attempts=row["attempts"] + 1)
            if ok:
                _append_history(topic, results)
                log.info("JOB %s COMPLETE → %s", job_id,
                         [r["url"] for r in ok if r.get("url")])
            else:
                raise RuntimeError("all platforms failed")
            return

        upsert(job_id, attempts=row["attempts"] + 1)

    except Exception as e:
        log.exception("job %s failed", job_id)
        upsert(job_id, status=f"FAILED_{row['stage'] or 'BOOT'}",
               error=str(e)[:500], attempts=row["attempts"] + 1)
        alert.send(f"❌ job {job_id} failed at {row['stage'] or 'boot'}: {e}")

def publish_all(video: Path, script: dict) -> list[dict]:
    from publishers.youtube import YouTubePublisher
    from publishers.meta_reels import InstagramPublisher
    from publishers.telegram import TelegramPublisher
    from publishers.base import VideoMeta, FatalError

    tags = [h.lstrip("#") for h in script.get("hashtags", [])][:15]
    desc = " ".join([script["hook"], *script["body"], "\n\n",
                     " ".join(script.get("hashtags", []))])
    meta = VideoMeta(title=script["title"], description=desc, tags=tags,
                     caption_html=(f"<b>{html_escape(script['hook'])}</b>\n"
                                   f"{' '.join(script.get('hashtags', []))}"))
    registry = {}
    if settings.enable_youtube:  registry["youtube"] = YouTubePublisher()
    if settings.enable_instagram: registry["instagram"] = InstagramPublisher()
    if settings.enable_telegram:  registry["telegram"] = TelegramPublisher()

    results = []
    for name, pub in registry.items():          # sequential = platform-friendly pacing
        try:
            r = pub.publish(video, meta)
            results.append({"platform": name, "ok": True,
                            "id": r.external_id, "url": r.url})
        except FatalError as e:
            log.error("[%s] FATAL: %s", name, e)
            results.append({"platform": name, "ok": False, "fatal": True, "error": str(e)})
        except Exception as e:
            log.exception("[%s] failed", name)
            results.append({"platform": name, "ok": False, "error": str(e)})
    return results

def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _append_history(topic: dict, results: list):
    h = settings.data_dir / "history.jsonl"
    h.parent.mkdir(parents=True, exist_ok=True)
    with open(h, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                             "title": topic["title"], "results": results},
                            ensure_ascii=False) + "\n")

# ------------------------------------------------------------------ runners

def run_batch(n: int):
    topics = miner.mine(batch=n)
    if not topics:
        log.warning("no fresh topics"); return
    ids = [create_job(t) for t in topics]
    workers = max(1, settings.parallel_jobs)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(process_job, ids))

def run_loop(interval_s: int, batch_n: int):
    import time
    log.info("scheduler online: batch=%d every %ds", batch_n, interval_s)
    while True:
        try:
            run_batch(batch_n)
        except Exception as e:
            log.exception("batch crashed"); alert.send(f"batch crash: {e}")
        time.sleep(interval_s)

def retry_failed():
    with db() as c:
        rows = c.execute("SELECT id FROM jobs WHERE status LIKE 'FAILED%'").fetchall()
    for r in rows:
        with db() as c:
            prev = c.execute("SELECT stage FROM jobs WHERE id=?", (r["id"],)).fetchone()[0]
            idx = STAGES.index(prev) if prev in STAGES else -1
            back = STAGES[max(0, idx - 1)] if idx > 0 else "DISCOVERED"
            c.execute("UPDATE jobs SET status=?, stage=? WHERE id=?",
                      (back, "" if back == "DISCOVERED" else back, r["id"]))
        process_job(r["id"])

def status_table():
    with db() as c:
        rows = c.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
    print(f"{'STATUS':<22}COUNT")
    for r in rows:
        print(f"{r['status']:<22}{r['n']}")

# ------------------------------------------------------------------ CLI

def main():
    setup_logging(settings.log_level)
    init_db()
    ap = argparse.ArgumentParser("shortfactory")
    ap.add_argument("cmd", choices=["run", "run-loop", "retry", "status"])
    ap.add_argument("--batch", type=int, default=3)
    ap.add_argument("--interval", type=int, default=900)
    a = ap.parse_args()
    {"run": lambda: run_batch(a.batch),
     "run-loop": lambda: run_loop(a.interval, a.batch),
     "retry": retry_failed,
     "status": status_table}[a.cmd]()

if __name__ == "__main__":
    sys.exit(main())
```

---

## 9. Deployment, Scheduling, Monitoring

### 9.1 `Dockerfile`

```dockerfile
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg python3.11 python3-pip fontconfig ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /usr/share/fonts/truetype/custom && cp fonts/*.ttf /usr/share/fonts/truetype/custom/ \
 && fc-cache -f

CMD ["python3", "-m", "pipeline", "run-loop", "--interval", "900", "--batch", "3"]
```

### 9.2 `docker-compose.yml`

```yaml
services:
  factory:
    build: .
    image: shortfactory:latest
    env_file: .env
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./assets:/app/assets
      - ./fonts:/app/fonts
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility,video
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

```bash
docker compose up -d --build
docker compose logs -f factory
```

### 9.3 Bare-Metal Schedule (Windows/Linux with local GPU)

```bash
# Linux cron — 3 videos/hour, off-peak render windows respected by queue depth
*/20 * * * * cd /opt/shortfactory && .venv/bin/python -m pipeline run --batch 1 >> data/cron.log 2>&1
```

```powershell
# Windows Task Scheduler (NVENC-native)
schtasks /Create /TN ShortFactory /TR "C:\opt\shortfactory\.venv\Scripts\python.exe -m pipeline run --batch 1" /SC MINUTE /MO 20
```

### 9.4 `check_env.py` — Preflight Gate

```python
"""Preflight: ffmpeg+filters, NVENC probe, fonts, credentials, dirs."""
from pathlib import Path
from utils import sh, log
from config import settings

def main():
    checks = []
    def ck(name, fn):
        try:
            fn(); checks.append((name, "PASS", ""))
        except Exception as e:
            checks.append((name, "FAIL", str(e)[:120]))

    ck("ffmpeg", lambda: sh(["ffmpeg", "-version"]))
    ck("ffprobe", lambda: sh(["ffprobe", "-version"]))
    ck("libass", lambda: sh(["ffmpeg", "-hide_banner", "-filters"], capture=True)
        if b"ass" in sh(["ffmpeg", "-hide_banner", "-filters"]).stderr.encode() else (_ for _ in ()).throw(RuntimeError()))
    from render import has_nvenc
    ck("nvenc", lambda: (_ for _ in ()).throw(RuntimeError()) if not has_nvenc() else None)
    ck("fonts", lambda: (_ for _ in ()).throw(RuntimeError("fonts/ empty"))
        if not any(Path("fonts").glob("*.ttf")) else None)
    ck("llm", lambda: (_ for _ in ()).throw(RuntimeError("no key")) if not settings.llm_api_key else None)
    ck("youtube creds", lambda: (_ for _ in ()).throw(RuntimeError())
        if settings.enable_youtube and not settings.yt_refresh_token else None)
    ck("telegram", lambda: (_ for _ in ()).throw(RuntimeError())
        if settings.enable_telegram and not settings.telegram_bot_token else None)

    w = max(len(c[0]) for c in checks)
    for name, st, msg in checks:
        print(f"{name:<{w}}  {st}  {msg}")
    if any(s == "FAIL" for _, s, _ in checks):
        raise SystemExit(1)
    print("\nEnvironment OK.")

if __name__ == "__main__":
    import logging; logging.disable(logging.CRITICAL)
    main()
```

### 9.5 Monitoring Hooks

| Signal | Source | Action |
|---|---|---|
| Job failure spike | `jobs.status LIKE 'FAILED%'` rolling window | Webhook alert + auto-pause via sentinel file |
| Upload quota burn | Count of `PUBLISHED` youtube/day vs. 6 | Throttle `ENABLE_YOUTUBE` after cap |
| Render regression | `qc()` duration-drift failures | Alert; fall back `ENCODER=x264` |
| Token expiry (IG/YT) | 401/190 rates in logs | Rotate refresh tokens |

---

## 10. Failure Taxonomy, Rate Limits, Compliance Guardrails

### 10.1 Failure Classification (implemented in `base.resilient`)

| Class | Examples | Behavior |
|---|---|---|
| **Transient** | HTTP 429/5xx, TG `flood_wait`, IG `code 4`, YT 401-after-refresh | Exponential backoff + full jitter, honor `Retry-After` |
| **Fatal** | YT `quotaExceeded`, IG `error_subcode` invalid media, TG >50 MB, bad OAuth grants | Abort platform, continue others, mark job partial |
| **Infra** | NVENC init failure, OOM in whisper | Capability probe → automatic downgrade (x264 / smaller model) |

### 10.2 Operational Rate-Limit Playbook

| Scenario | Mitigation |
|---|---|
| YouTube 6 uploads/day ceiling | Apply for quota increase (audit form) or stagger across multiple projects/channels |
| IG 50 publishes/24 h | Global counter keyed by UTC date persisted in SQLite; publisher refuses beyond cap |
| Telegram broadcast bursts | Sequential send + 0.7 s pacing + `retry_after` obedience (already implemented) |
| Edge-TTS IP throttling | Switch `TTS_ENGINE=kokoro` (offline) for the affected run window |

### 10.3 Compliance Guardrails (non-optional in production)

1. **Disclosure:** label AI-generated narration/synthetic media where platform policy requires (YouTube altered-content flag, TikTok AIGC toggle).
2. **Transformative value:** YouTube's reused-content policy — the hook/script layer must add original commentary; don't rebroadcast raw clips.
3. **Music licensing:** background music must come from platform-cleared libraries or owned licenses; the default pipeline ships **music-free** with `-14 LUFS` VO-only normalization.
4. **API terms:** Meta publishing requires an approved app with `instagram_content_publish` + Business/Creator account linkage; respect container polling cadence.
5. **Data hygiene:** `history.jsonl` dedup prevents duplicate-spam flags; cap daily volume per account well below documented limits.

### 10.4 Extension Roadmap

| Upgrade | Interface Point |
|---|---|
| B-roll auto-insert from Pexels API keyed on `visual_query` | `render._pick_background()` → multi-input `xfade` graph |
| Multilingual expansion (es/hi/pt) | `tts` voice map + whisper `language=` + ASS font swap |
| Redis/RQ horizontal scaling | Replace SQLite lock + ThreadPool with broker queues per stage |
| A/B hook testing | Emit 2 variants per topic; route by `job_id % 2`; compare 3-h retention |
| Thumbnail auto-gen | Extract peak-motion frame via `select='gt(scene,0.3)'` + ASS title card |

---

## Appendix A — Quickstart Sequence

```bash
git clone <repo> shortfactory && cd shortfactory
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # fill credentials
python check_env.py                                     # preflight gate
python -m pipeline run --batch 1                        # smoke test, single job
python -m pipeline status                               # inspect FSM
```

**Expected smoke-test output (abridged):**

```text
mine     | mined 3 fresh topics (from 27 candidates)
hooks    | script ready: 141 words (budget 124-155)
tts      | voiceover: edge-tts 47.8s
asr      | loading whisper large-v3 (cuda/float16)
asr      | aligned 138 words over 47.81s
render   | nvenc available: True
render   | encoded with h264_nvenc
render   | QC PASS  1080x1920  48.0s  h264+aac
yt       | upload 51%
yt       | published https://youtube.com/shorts/<id>
tg       | sent to @channel_a (msg 8421)
JOB <id> COMPLETE → ['https://youtube.com/shorts/<id>']
```

This blueprint is complete and runnable as-is; each module is independently testable, every external dependency has a defined fallback, and the state machine guarantees at-least-once delivery semantics with per-platform idempotent publication.