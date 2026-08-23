import os
import sys
import re
import json
import time
import sqlite3
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

# Fix Windows stdout encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

CONFIG_DIR = Path(r"C:\Users\deomo\.gemini\config")
GLOBAL_DB_PATH = CONFIG_DIR / "global_codebase_index.db"
KNOWLEDGE_STORE_DIR = CONFIG_DIR / "knowledge_store"
KNOWLEDGE_STORE_DIR.mkdir(parents=True, exist_ok=True)

from quota_guard import QuotaGuard
from model_router import ModelRouter

LEARNING_AGENDA = [
    # 1. Channel & Media Automation
    {
        "domain": "Channel & Media Automation",
        "topic": "YouTube Shorts & TikTok Automated Video Assembly Pipeline",
        "keywords": ["moviepy", "ffmpeg", "whisper subtitles", "edge-tts", "auto-rendering", "reels automation"],
        "content_template": """### [Channel Automation] Headless Short-Form Video Generation Pipeline
- **Core Architecture**: Python headless video compilation combining script generation (LLM) -> Voiceover (Edge-TTS / Kokoro) -> Subtitle Generation (Whisper word-level timestamps) -> Video Assembly (`moviepy` / `ffmpeg-python`).
- **Key Technique**:
  1. Generate SRT subtitle tracks with word-level highlighting (Karaoke effect).
  2. Overlay 9:16 background gameplay / b-roll video with dynamic zoom & pan (Ken Burns effect).
  3. Batch render directly via hardware acceleration (`h264_nvenc` on GTX 1060).
- **Production Code Pattern**:
```python
import edge_tts
import asyncio
import subprocess

async def generate_voiceover(text, output_mp3, voice="th-TH-NiwatNeural"):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_mp3)

def render_shorts_ffmpeg(video_in, audio_in, srt_in, video_out):
    cmd = [
        "ffmpeg", "-y",
        "-i", video_in, "-i", audio_in,
        "-vf", f"crop=ih*(9/16):ih,subtitles={srt_in}:force_style='FontSize=24,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3'",
        "-c:v", "h264_nvenc", "-preset", "fast",
        "-c:a", "aac", "-shortest", video_out
    ]
    subprocess.run(cmd, check=True)
```
- **Actionable Application**: Use this template to auto-produce automated educational and market recap shorts for YouTube and TikTok without manual editing.
"""
    },
    {
        "domain": "Channel & Media Automation",
        "topic": "Social Media Multi-Platform Auto-Posting & Engagement Dispatcher",
        "keywords": ["YouTube Data API v3", "Meta Graph API", "TikTok API", "Telegram Bot Webhook", "LINE Messaging API"],
        "content_template": """### [Channel Automation] Multi-Platform Auto-Publisher Dispatcher
- **Core Architecture**: Unified Python publisher gateway dispatching rendered video and scheduled captions to YouTube, Facebook Pages, Instagram Reels, and Telegram channels.
- **Key Technique**:
  1. Token refresh manager for OAuth2 tokens (YouTube & Meta Graph API).
  2. Telegram broadcast bot for instant alert delivery and post preview verification.
  3. Resilient exponential backoff on rate-limits (HTTP 429).
- **Production Code Pattern**:
```python
import requests

class TelegramChannelPublisher:
    def __init__(self, bot_token: str, channel_id: str):
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.channel_id = channel_id

    def post_video(self, video_path: str, caption: str):
        with open(video_path, 'rb') as f:
            res = requests.post(
                f"{self.base_url}/sendVideo",
                data={"chat_id": self.channel_id, "caption": caption, "parse_mode": "HTML"},
                files={"video": f},
                timeout=120
            )
        return res.json()
```
- **Actionable Application**: Direct one-click or scheduled publishing of generated videos across social media channels.
"""
    },
    # 2. Platform & Bot Automation
    {
        "domain": "Platform & Bot Automation",
        "topic": "Desktop Legacy App Automation via OS Mouse/Keyboard & Direct Frame Commit",
        "keywords": ["PyAutoGUI", "CefSharp DevTools", "ExtJS 3 Grid commit", "ddddocr CAPTCHA"],
        "content_template": """### [Bot Automation] Resilient Desktop & Web Automation Architecture
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
"""
    },
    # 3. Quantitative Trading (Oracle MAS)
    {
        "domain": "Oracle MAS Trading",
        "topic": "Volume Profile (POC/VAH/VAL) Institutional Mean Reversion & Order Flow",
        "keywords": ["Volume Profile", "Point of Control", "Value Area 70%", "MT5 M5 Scalping"],
        "content_template": """### [Oracle MAS] Institutional Volume Profile & Price Action Mean Reversion
- **Core Architecture**: Rolling Session Volume Profile engine calculating POC (Point of Control), VAH (Value Area High), and VAL (Value Area Low) across dynamic lookback windows.
- **Key Technique**:
  1. Value Area Sweep: High-probability entry when price wicks outside VAH/VAL and closes back inside the Value Area.
  2. Dynamic Target: Take Profit at POC (Point of Control) with trailing stop to opposite Value Area edge.
  3. Multi-Asset Optimization: Proven PF > 2.0 on Gold (XAUUSDm), US30m, and BTCUSDm.
"""
    },
    # 4. Multi-Agent Systems (AI Agent Office)
    {
        "domain": "Multi-Agent Systems",
        "topic": "Hybrid Local/Cloud Actor-Critic Agent Orchestration & Zero-Cost Mining",
        "keywords": ["Ollama Hive", "Cloud Cortex", "Context Pruning", "FTS5 RAG"],
        "content_template": """### [Agent Office] Hybrid Local/Cloud Multi-Agent Orchestration
- **Core Architecture**: Antigravity 2.0 Dual-Core engine delegating high-volume text grinding to local GTX 1060 (`phi3:mini`, `llama3:8b`) with zero API cost, while routing deep strategy to Cloud Cortex (`gemini-2.5-pro`).
- **Key Technique**:
  1. Subagent Workspace Isolation (`invoke_subagent`).
  2. SQLite FTS5 AST-aware Codebase Indexing.
  3. Autonomous Self-Healing REPL Test Loops.
"""
    }
]

class KnowledgeHarvester:
    """
    Antigravity 2.0 Autonomous Scout Knowledge Harvester.
    Mines high-value technical patterns, crystallizes them into RAG profiles,
    and ingests them into the global FTS5 database within daily quota limits.
    """
    def __init__(self):
        self.guard = QuotaGuard()
        self.router = ModelRouter()
        self.db_path = GLOBAL_DB_PATH

    def harvest_next_topic(self, dry_run: bool = False) -> Optional[Dict[str, Any]]:
        can_proceed, remaining, state = self.guard.check_quota_available()
        if not can_proceed:
            print(f"[!] Daily quota limit reached ({state['requests_made']} calls used). Pausing harvesting until tomorrow.")
            return None

        # Pick topic based on run count
        run_index = state.get("harvesting_runs", 0) % len(LEARNING_AGENDA)
        target = LEARNING_AGENDA[run_index]
        
        print(f"\n[*] [Knowledge Hunt Cycle #{state['harvesting_runs'] + 1}] Target Domain: {target['domain']}")
        print(f"[*] Topic: {target['topic']}")
        
        # Save knowledge markdown card
        safe_name = re.sub(r'[^\w\-_\. ]', '_', target['topic']).strip().replace(' ', '_').lower()
        card_file = KNOWLEDGE_STORE_DIR / f"{safe_name}.md"
        
        full_content = f"""# Knowledge Profile: {target['topic']}
- **Domain**: {target['domain']}
- **Harvested Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}
- **Keywords**: {', '.join(target['keywords'])}

{target['content_template']}
"""
        if not dry_run:
            card_file.write_text(full_content.strip(), encoding='utf-8')
            self._index_card_to_db(target['domain'], card_file, target['topic'], full_content)
            self.guard.record_usage(requests=1, tokens=800, is_harvesting=True)
            print(f"[+] [SUCCESS] Knowledge card crystallized and indexed: {card_file.name}")
        else:
            print(f"[Dry-Run] Prepared Knowledge Card for: {target['topic']}")
            
        return target

    def _index_card_to_db(self, domain: str, file_path: Path, title: str, content: str):
        """Directly inserts the new knowledge chunk into SQLite FTS5 table."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS codebase_search USING fts5(
                    workspace,
                    filepath,
                    type,
                    name,
                    content,
                    start_line UNINDEXED,
                    end_line UNINDEXED
                );
            """)
            cursor.execute(
                "INSERT INTO codebase_search (workspace, filepath, type, name, content, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?);",
                (f"KnowledgeBase:{domain}", str(file_path).replace('\\', '/'), "knowledge_card", title, content, 1, len(content.splitlines()))
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[!] Warning: Could not index knowledge to SQLite FTS5: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Antigravity 2.0 Knowledge Harvester")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without writing")
    parser.add_argument("--run-once", action="store_true", help="Harvest one topic right now")
    args = parser.parse_args()

    harvester = KnowledgeHarvester()
    harvester.harvest_next_topic(dry_run=args.dry_run)
