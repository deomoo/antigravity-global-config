import os
import sys
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple

# Fix Windows cp874/cp1252 stdout encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

class ModelRouter:
    """
    Antigravity 2.0 Hybrid Model Router.
    Intelligently routes requests between Local Hive (Ollama), OpenRouter Stealth Cortex, and Cloud Cortex.
    Handles instant auto-failover, health checks, and latency measurement.
    """
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434"):
        self.ollama_url = ollama_url.rstrip('/')
        self._load_env()
        self.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.local_models = {
            "fast_workhorse": "phi3:mini",
            "heavy_local": "llama3:8b",
            "ocr_miner": "llama3.2-vision:latest"
        }
        self.openrouter_models = {
            "ox_alpha": "stealth/ox-alpha",
            "long_context_coder": "stealth/ox-alpha"
        }
        self.cloud_models = {
            "primary": "gemini-2.5-flash",
            "pro_reasoning": "gemini-2.5-pro",
            "claude_code": "claude-3-5-sonnet-20240620"
        }
        self._local_health_cache: Optional[Tuple[bool, float, list]] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 10.0  # cache health check for 10 seconds

    def _load_env(self):
        """Loads .env file from config directory if present without requiring python-dotenv."""
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ[k.strip()] = v.strip().strip('"\'')
            except Exception:
                pass

    def check_ollama_health(self, force_refresh: bool = False) -> Tuple[bool, float, list]:
        """
        Check if Ollama is running and responsive.
        Returns: (is_alive, latency_ms, available_model_names)
        """
        now = time.time()
        if not force_refresh and self._local_health_cache and (now - self._cache_time < self._cache_ttl):
            return self._local_health_cache

        start_time = time.time()
        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/tags",
                headers={"User-Agent": "Antigravity-ModelRouter/2.0"},
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=1.5) as response:
                if response.status == 200:
                    latency = (time.time() - start_time) * 1000.0
                    data = json.loads(response.read().decode('utf-8'))
                    models = [m.get("name") for m in data.get("models", [])]
                    self._local_health_cache = (True, round(latency, 2), models)
                    self._cache_time = now
                    return self._local_health_cache
        except Exception:
            pass

        self._local_health_cache = (False, -1.0, [])
        self._cache_time = now
        return self._local_health_cache

    def select_model(self, task_type: str = "general", prefer_local: bool = False) -> Dict[str, Any]:
        """
        Select the best model based on task type, preference, and local server availability.
        
        task_types:
          - 'grind' / 'mining' / 'ocr': Data extraction, web scraping, logs, summaries (Local Hive)
          - 'ox_alpha' / 'long_context' / 'stealth': 1M token heavy context reasoning (OpenRouter stealth/ox-alpha)
          - 'architecture' / 'heavy_reasoning': Deep reasoning, multi-file refactors (Gemini Pro / Claude)
          - 'quick_fix' / 'general': General coding and fast verification
        """
        is_local_alive, latency_ms, installed_models = self.check_ollama_health()
        
        # Rule 1: High-Volume Grind / Mining tasks -> Prefer Local Hive (Zero Token Cost)
        if (prefer_local or task_type in ("grind", "mining", "ocr")) and is_local_alive:
            preferred_local_model = self.local_models["fast_workhorse"]
            matched_model = next((m for m in installed_models if preferred_local_model.split(':')[0] in m), None)
            if matched_model:
                return {
                    "backend": "ollama",
                    "model_name": matched_model,
                    "target_tier": "Local Hive (Zero Cost)",
                    "latency_ms": latency_ms,
                    "url": f"{self.ollama_url}/api/generate"
                }

        # Rule 2: 0x-Alpha 1M Long-Context Reasoning
        if task_type in ("ox_alpha", "long_context", "stealth") and self.openrouter_api_key:
            return {
                "backend": "openrouter",
                "model_name": self.openrouter_models["ox_alpha"],
                "target_tier": "Stealth Cortex (0x Alpha 1M Context)",
                "local_status": "[ONLINE]" if is_local_alive else "[OFFLINE]"
            }

        # Rule 3: Deep Architecture / Critical Strategy
        if task_type in ("architecture", "heavy_reasoning"):
            return {
                "backend": "gemini",
                "model_name": self.cloud_models["pro_reasoning"],
                "target_tier": "Cloud Cortex (Pro Reasoning)",
                "local_status": "[ONLINE]" if is_local_alive else "[OFFLINE]"
            }

        # Rule 4: Default Fast Cloud Cortex
        return {
            "backend": "gemini",
            "model_name": self.cloud_models["primary"],
            "target_tier": "Cloud Cortex (Fast Flash)",
            "local_status": "[ONLINE]" if is_local_alive else "[OFFLINE]"
        }

    def call_ollama(self, model_name: str, prompt: str, system_prompt: str = "") -> str:
        """Invokes local Ollama model directly via REST API."""
        payload = {
            "model": model_name,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False
        }
        req = urllib.request.Request(
            f"{self.ollama_url}/api/generate",
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("response", "")

    def call_openrouter(self, model_name: str = "stealth/ox-alpha", prompt: str = "", system_prompt: str = "", timeout: int = 300, max_retries: int = 3) -> str:
        """Invokes OpenRouter model directly via requests with robust retry logic."""
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured in .env or environment.")

        import requests
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_name,
            "messages": messages
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "HTTP-Referer": "https://github.com/antigravity",
            "X-Title": "Antigravity 2.0"
        }
        
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=timeout
                )
                response.raise_for_status()
                result = response.json()
                choices = result.get("choices", [])
                if choices and "message" in choices[0]:
                    return choices[0]["message"].get("content", "")
                return str(result)
            except Exception as e:
                last_err = e
                print(f"[!] OpenRouter attempt {attempt}/{max_retries} failed: {e}. Retrying in 5s...")
                time.sleep(5)
                
        raise RuntimeError(f"OpenRouter call failed after {max_retries} attempts. Last error: {last_err}")

if __name__ == "__main__":
    router = ModelRouter()
    
    if "--test-ox" in sys.argv or "--ask-ox" in sys.argv:
        prompt = "Hello! Please confirm your model name, capabilities, and token context window in 2 sentences."
        if "--ask-ox" in sys.argv:
            idx = sys.argv.index("--ask-ox")
            if len(sys.argv) > idx + 1:
                prompt = " ".join(sys.argv[idx + 1:])
        
        print(f"[*] Dispatching query to OpenRouter (stealth/ox-alpha)...")
        print(f"[*] Prompt: {prompt}\n")
        try:
            start_t = time.time()
            reply = router.call_openrouter(model_name="stealth/ox-alpha", prompt=prompt)
            elapsed = time.time() - start_t
            print(f"[+] Response received in {elapsed:.2f}s:\n")
            print(reply)
        except Exception as e:
            print(f"[!] Error calling OpenRouter: {e}")
        sys.exit(0)

    if "--check" in sys.argv or len(sys.argv) == 1:
        alive, latency, models = router.check_ollama_health(force_refresh=True)
        print("=" * 60)
        print(" Antigravity 2.0 Hybrid Model Router Health Status")
        print("=" * 60)
        print(f"[*] Ollama Status:      {'[ONLINE]' if alive else '[OFFLINE]'}")
        if alive:
            print(f"[*] Ping Latency:       {latency} ms")
            print(f"[*] Local Models:       {', '.join(models) if models else 'None installed'}")
        else:
            print("[!] Note: Local Hive offline. All tasks gracefully route to Cloud Cortex.")
        
        has_or = bool(router.openrouter_api_key)
        print(f"[*] OpenRouter Key:     {'[CONFIGURED]' if has_or else '[NOT CONFIGURED]'}")
        print(f"[*] Stealth 0x Alpha:   {'[READY]' if has_or else '[NEEDS KEY]'}")
        
        print("\n--- Routing Decisions Simulation ---")
        for task in ["grind", "ox_alpha", "architecture", "coding"]:
            decision = router.select_model(task_type=task)
            print(f"Task: {task:<15} -> Backend: {decision['backend']} ({decision['model_name']}) [{decision['target_tier']}]")
        print("=" * 60)
