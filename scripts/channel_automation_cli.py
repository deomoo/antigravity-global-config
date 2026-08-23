import os
import sys
import argparse
from pathlib import Path

# Fix Windows stdout encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

from channel_series_pipeline import ChannelSeriesEngine, OUTPUT_BASE_DIR

def list_all_series():
    print("\n=== Antigravity Channel Automation: Existing Series ===")
    topics = list(OUTPUT_BASE_DIR.glob("*"))
    if not topics:
        print("[*] No video series created yet.")
        return
        
    for p in topics:
        if p.is_dir():
            manifest = p / "topic_manifest.json"
            if manifest.exists():
                import json
                data = json.loads(manifest.read_text(encoding='utf-8'))
                print(f"- [{data.get('topic_title', p.name)}] ({data.get('total_episodes', 0)} Episodes)")
                print(f"  Path: {p}")
                for ep in data.get("episodes", []):
                    status_icon = "[OK]" if ep.get("status") == "rendered" else "[..]"
                    print(f"    * EP.{ep['episode_number']:02d}: {ep['phase']} {status_icon}")
            else:
                print(f"- {p.name}")
    print("=" * 55)

def main():
    parser = argparse.ArgumentParser(description="Antigravity 2.0 Topic-Based Channel Video Automation CLI")
    parser.add_argument("--create-series", help="Title of the topic/series to build")
    parser.add_argument("--episodes", type=int, default=3, help="Number of coherent episodes to generate")
    parser.add_argument("--list", action="store_true", help="List all generated topic series")

    args = parser.parse_args()
    engine = ChannelSeriesEngine()

    if args.create_series:
        engine.build_full_series(args.create_series, args.episodes)
    elif args.list:
        list_all_series()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
