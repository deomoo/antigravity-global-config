import os
import sys
import re
import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, Any, List

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

sys.path.insert(0, str(CONFIG_DIR / "scripts"))
from model_router import ModelRouter

BLUEPRINT_PILLARS = [
    # Pillar 1: Quantitative Trading (Multi-Strategy: Scalping, Swing, SMC, ML Alpha, Risk)
    {
        "pillar": "Pillar 1: Multi-Horizon Quantitative Trading",
        "title": "Institutional Multi-Strategy Trading Engine (Scalping, SMC Swing, ML Alpha & Sentinel Risk)",
        "file_name": "pillar1_institutional_multi_strategy_trading_engine.md",
        "prompt": """You are an elite quantitative hedge fund architect and institutional algorithmic trader.
Generate a comprehensive, production-ready technical blueprint and implementation guide for an Institutional Multi-Strategy Trading Engine covering:
1. Multi-Strategy Taxonomy:
   - Ultra-Fast Scalping (Volume Profile POC/VAH/VAL & Order Flow Delta)
   - Day & Swing Trading (Smart Money Concepts / ICT Liquidity Sweeps & Fair Value Gaps)
   - Trend Following & Statistical Mean Reversion (Z-score & ATR trailing channels)
2. Machine Learning Alpha & Feature Engineering (XGBoost / LightGBM classification for market regime filtering)
3. Quantitative Risk Management & Sentinel Guard:
   - Dynamic Fractional Kelly Criterion & Volatility-Adjusted Lot Sizing
   - Hard Maximum Drawdown Circuit Breakers & Trailing Profit Locks
4. Production-Ready Python & MetaTrader 5 (MT5) Execution Engine code snippets with robust error handling and slippage controls.

Format with clear markdown headings, bullet points, mathematical formulas, and complete Python code blocks."""
    },
    # Pillar 2: Media & Content Automation Engine
    {
        "pillar": "Pillar 2: Media & Content Automation",
        "title": "Headless Faceless Video Production & Multi-Platform Auto-Publisher Pipeline",
        "file_name": "pillar2_headless_faceless_video_production_pipeline.md",
        "prompt": """You are an expert media automation engineer and viral content systems architect.
Generate a complete, production-grade technical blueprint and implementation guide for an Autonomous Short-Form Video Production & Distribution Pipeline (YouTube Shorts, TikTok, Instagram Reels, Telegram):
1. End-to-End Headless Pipeline Architecture:
   - Viral Topic Mining & Hook Generator
   - Neural Voiceover Synthesis (Edge-TTS / Kokoro)
   - Whisper Word-Level Timestamps with Karaoke Highlight Subtitle Rendering (ASS / SRT)
   - Hardware-Accelerated Video Composition (MoviePy / FFmpeg with h264_nvenc)
2. Multi-Platform Auto-Publisher Gateway (YouTube Data API v3, Meta Graph API, Telegram Broadcast Bot with token auto-refresh and rate-limit backoff).
3. Production-Ready Python Scripts with full code examples for batch video rendering and multi-platform publishing.

Format with clean markdown, architectural diagrams, and copy-paste ready Python code."""
    },
    # Pillar 3: Micro-SaaS & High-Value Bot Automation
    {
        "pillar": "Pillar 3: Micro-SaaS & Bot Automation Innovations",
        "title": "High-Yield Micro-SaaS Automation, Anti-Detect Scrapers & Enterprise RPA Bots",
        "file_name": "pillar3_micro_saas_automation_and_enterprise_rpa.md",
        "prompt": """You are an elite software architect specializing in profitable Micro-SaaS systems and enterprise business process automation.
Generate an in-depth technical blueprint and implementation guide for building high-yield automation bots and Micro-SaaS platforms:
1. High-Throughput Web Data Extraction & B2B Lead Gen Engine:
   - Anti-detect browser orchestration (Playwright / CDP stealth)
   - Dynamic residential proxy rotation, fingerprint spoofing & rate-limit evasion
2. Enterprise Desktop & Web RPA (PyAutoGUI + DOM Store/IFrame Injection + ddddocr OCR CAPTCHA auto-solver with length constraint checks).
3. Conversational AI Secretary & Sales Gateway (Telegram & LINE Messaging Webhook Gateway with LLM Function Calling and Stripe/PromptPay billing integration).
4. Production-Ready Python architectural templates and modular code snippets.

Format with clear headers, production code patterns, and actionable monetization workflows."""
    },
    # Pillar 4: Advanced Multi-Agent & Cognitive Architecture
    {
        "pillar": "Pillar 4: Advanced Multi-Agent & Cognitive Architecture",
        "title": "Self-Evolving Cognitive Multi-Agent Swarm & Long-Context Architecture",
        "file_name": "pillar4_self_evolving_cognitive_multi_agent_swarm.md",
        "prompt": """You are a lead AI research engineer specializing in Autonomous Multi-Agent Systems and Cognitive Agent Architectures.
Generate a state-of-the-art technical blueprint and implementation guide for building a Self-Evolving Cognitive AI Assistant (inspired by Human Brain modularity):
1. Modular Cognitive Architecture:
   - Sensory & Perception Filter (Noise removal & High-Signal extraction)
   - Working Memory (1M Token Context Buffer with 0x Alpha / Gemini)
   - Dual Long-Term Memory (Episodic Experience Memory + SQLite FTS5 Semantic RAG Store)
   - Executive Planning & Critic Swarm (Director, CodeCraft, Sentinel Risk Reviewer)
   - Sleep / Consolidation Engine (Daily Memory Compaction & Self-Evolution)
2. Parallel Subagent Swarm Orchestration with isolated branch workspaces and non-blocking inter-agent messaging.
3. Production-Ready Python implementation with complete code for Model Router, Memory Compaction, and SQLite FTS5 RAG integration.

Format with clear markdown, architectural diagrams, and robust production-ready code."""
    }
]

class BlueprintHarvester:
    def __init__(self):
        self.router = ModelRouter()
        self.db_path = GLOBAL_DB_PATH

    def index_to_fts5(self, pillar: str, title: str, file_path: Path, content: str):
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
                (f"KnowledgeBase:{pillar}", str(file_path).replace('\\', '/'), "blueprint", title, content, 1, len(content.splitlines()))
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[!] Warning: Could not index to SQLite FTS5: {e}")

    def run_harvest(self):
        print("=" * 70)
        print(" Antigravity 2.0 - 0x Alpha Mega Knowledge Ingestion & Blueprint Engine")
        print("=" * 70)
        
        system_prompt = "You are an elite senior technical architect. Output high-density, production-grade technical blueprints with clean markdown and runnable Python code."
        
        for idx, item in enumerate(BLUEPRINT_PILLARS, 1):
            target_file = KNOWLEDGE_STORE_DIR / item['file_name']
            if target_file.exists() and target_file.stat().st_size > 10000:
                print(f"\n[{idx}/{len(BLUEPRINT_PILLARS)}] [SKIPPING - ALREADY COMPLETE] {item['pillar']} ({target_file.stat().st_size} bytes)")
                continue

            print(f"\n[{idx}/{len(BLUEPRINT_PILLARS)}] Generating Blueprint for: {item['pillar']}")
            print(f"[*] Title: {item['title']}")
            print(f"[*] Target File: {item['file_name']}")
            print(f"[*] Querying OpenRouter (stealth/ox-alpha)...")
            
            start_t = time.time()
            try:
                content = self.router.call_openrouter(
                    model_name="stealth/ox-alpha",
                    prompt=item['prompt'],
                    system_prompt=system_prompt,
                    timeout=360
                )
                elapsed = time.time() - start_t
                print(f"[+] Response received in {elapsed:.2f}s (Length: {len(content)} chars)")
                
                header = f"""# {item['title']}\n- **Pillar**: {item['pillar']}\n- **Generated Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n- **Synthesized By**: 0x Alpha (stealth/ox-alpha) via Antigravity 2.0\n\n---\n\n"""
                full_text = header + content
                
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(full_text)
                
                self.index_to_fts5(item['pillar'], item['title'], target_file, full_text)
                print(f"[+] [SAVED & INDEXED] {target_file.name}")
                
            except Exception as e:
                print(f"[!] Error generating blueprint for {item['title']}: {e}")
            
            time.sleep(3)

        print("\n" + "=" * 70)
        print(" All 4 Revenue-Generating Blueprints Synthesized & Indexed!")
        print("=" * 70)
        
        # Git Backup & Cloud Sync
        self.sync_to_github()

    def sync_to_github(self):
        print("\n[*] [DISASTER RECOVERY] Syncing knowledge blueprints to GitHub...")
        import subprocess
        try:
            subprocess.run(["git", "add", "knowledge_store/", "scripts/"], cwd=str(CONFIG_DIR), check=True)
            subprocess.run(["git", "commit", "-m", "feat: 0x-Alpha 4-pillar revenue knowledge blueprints & cloud sync"], cwd=str(CONFIG_DIR), check=False)
            res = subprocess.run(["git", "push", "origin", "main"], cwd=str(CONFIG_DIR), capture_output=True, text=True)
            if res.returncode == 0:
                print("[+] [GITHUB BACKUP SUCCESS] All knowledge blueprints safely synced to Cloud/GitHub!")
            else:
                print(f"[!] Git push warning: {res.stderr.strip()}")
        except Exception as e:
            print(f"[!] Git sync error: {e}")

if __name__ == "__main__":
    harvester = BlueprintHarvester()
    harvester.run_harvest()
