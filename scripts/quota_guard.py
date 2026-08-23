import os
import sys
import json
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Tuple

# Fix Windows stdout encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

CONFIG_DIR = Path(r"C:\Users\deomo\.gemini\config")
USAGE_LOG_PATH = CONFIG_DIR / "daily_quota_usage.json"

class QuotaGuard:
    """
    Antigravity 2.0 Daily Quota & Usage Monitor.
    Tracks daily request counts, estimated token usage, and protects a safety margin
    so user direct requests are never blocked by background tasks.
    """
    def __init__(self, daily_request_limit: int = 1500, safety_reserve_pct: float = 0.20):
        self.daily_request_limit = daily_request_limit
        self.safety_reserve_pct = safety_reserve_pct
        self.usable_ceiling = int(daily_request_limit * (1.0 - safety_reserve_pct))
        self.log_file = USAGE_LOG_PATH
        self._load_state()

    def _get_today_str(self) -> str:
        return date.today().isoformat()

    def _load_state(self) -> Dict[str, Any]:
        today_str = self._get_today_str()
        if self.log_file.exists():
            try:
                data = json.loads(self.log_file.read_text(encoding='utf-8'))
                if data.get("date") == today_str:
                    return data
            except Exception:
                pass
        # Reset state for a new day
        new_state = {
            "date": today_str,
            "requests_made": 0,
            "tokens_estimated": 0,
            "harvesting_runs": 0,
            "last_updated": datetime.now().isoformat()
        }
        self._save_state(new_state)
        return new_state

    def _save_state(self, state: Dict[str, Any]):
        try:
            state["last_updated"] = datetime.now().isoformat()
            self.log_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            print(f"[!] Warning: Could not save quota state: {e}")

    def record_usage(self, requests: int = 1, tokens: int = 500, is_harvesting: bool = False):
        state = self._load_state()
        state["requests_made"] += requests
        state["tokens_estimated"] += tokens
        if is_harvesting:
            state["harvesting_runs"] += 1
        self._save_state(state)

    def check_quota_available(self) -> Tuple[bool, int, Dict[str, Any]]:
        """
        Check if quota is available for autonomous learning.
        Returns: (can_proceed, remaining_usable_requests, state)
        """
        state = self._load_state()
        requests_made = state.get("requests_made", 0)
        remaining = max(0, self.usable_ceiling - requests_made)
        can_proceed = remaining > 0
        return can_proceed, remaining, state

    def print_status(self):
        state = self._load_state()
        requests = state.get("requests_made", 0)
        tokens = state.get("tokens_estimated", 0)
        harvests = state.get("harvesting_runs", 0)
        can_proceed, remaining, _ = self.check_quota_available()
        
        print("=" * 60)
        print(" Antigravity 2.0 Daily Quota & Learning Budget Status")
        print("=" * 60)
        print(f"[*] Date:                  {state.get('date')}")
        print(f"[*] Daily Ceiling Limit:   {self.daily_request_limit} calls")
        print(f"[*] Usable Limit (w/ Reserve): {self.usable_ceiling} calls (Safety Floor: {int(self.safety_reserve_pct*100)}%)")
        print(f"[*] Requests Used Today:   {requests} calls")
        print(f"[*] Remaining for Learning: {remaining} calls")
        print(f"[*] Est. Tokens Used:      {tokens:,} tokens")
        print(f"[*] Harvesting Runs Done:  {harvests} cycles")
        print(f"[*] Knowledge Hunt Status: {'[ACTIVE / PERMITTED]' if can_proceed else '[PAUSED - QUOTA CEILING REACHED]'}")
        print("=" * 60)

if __name__ == "__main__":
    guard = QuotaGuard()
    guard.print_status()
