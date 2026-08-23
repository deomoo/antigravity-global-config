import os
import sys
import time
import argparse
import subprocess
from pathlib import Path

# Fix Windows stdout encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

CONFIG_DIR = Path(r"C:\Users\deomo\.gemini\config")
sys.path.insert(0, str(CONFIG_DIR / "scripts"))

from quota_guard import QuotaGuard
from knowledge_harvester import KnowledgeHarvester

def run_daily_evolution(max_cycles: int = 5, delay_between_sec: float = 1.0):
    print("=" * 65)
    print(" Antigravity 2.0 Daily Continuous Evolution & Learning Loop")
    print("=" * 65)
    
    guard = QuotaGuard()
    harvester = KnowledgeHarvester()
    
    can_proceed, remaining, state = guard.check_quota_available()
    print(f"[*] Daily Quota Status: {state['requests_made']} calls used today. Usable remaining: {remaining} calls.")
    
    if not can_proceed:
        print("[!] Daily usable quota is already exhausted. All tasks pausing to preserve safety floor.")
        return

    cycles_to_run = min(max_cycles, remaining)
    print(f"[*] Scheduled to execute {cycles_to_run} autonomous knowledge cycles today.\n")
    
    successful_harvests = []
    
    for i in range(1, cycles_to_run + 1):
        print(f"--- [Evolution Cycle {i}/{cycles_to_run}] ---")
        item = harvester.harvest_next_topic()
        if item:
            successful_harvests.append(item['topic'])
        else:
            break
        time.sleep(delay_between_sec)
        
    print("\n" + "=" * 65)
    print(f"[+] Continuous Evolution Cycle Complete: {len(successful_harvests)} topics harvested & indexed into FTS5.")
    for topic in successful_harvests:
        print(f"    - {topic}")
    print("=" * 65)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Antigravity 2.0 Daily Continuous Evolution Loop")
    parser.add_argument("--max-cycles", type=int, default=3, help="Maximum learning cycles to run in this batch")
    parser.add_argument("--status-only", action="store_true", help="Print quota status only")
    args = parser.parse_args()

    if args.status_only:
        QuotaGuard().print_status()
    else:
        run_daily_evolution(max_cycles=args.max_cycles)
