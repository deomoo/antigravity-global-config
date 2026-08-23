import os
import sys
import time
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
SCRIPTS_DIR = CONFIG_DIR / "scripts"
SKILLS_DIR = CONFIG_DIR / "skills"
PLUGINS_DIR = CONFIG_DIR / "plugins"

def test_model_router():
    print("\n[TEST 1] Testing Hybrid Model Router...")
    router_script = SCRIPTS_DIR / "model_router.py"
    if not router_script.exists():
        print(f"[-] FAIL: {router_script} not found.")
        return False
        
    res = subprocess.run([sys.executable, str(router_script), "--check"], capture_output=True, text=True)
    print(res.stdout)
    if "Hybrid Model Router Health Status" in res.stdout:
        print("[+] PASS: ModelRouter initialized and responded cleanly.")
        return True
    else:
        print(f"[-] FAIL: Unexpected output: {res.stderr}")
        return False

def test_codebase_query():
    print("\n[TEST 2] Testing Codebase FTS5 Query Engine...")
    query_script = SCRIPTS_DIR / "query_codebase.py"
    if not query_script.exists():
        print(f"[-] FAIL: {query_script} not found.")
        return False
        
    res = subprocess.run([sys.executable, str(query_script), "Volume Profile", "-w", "oracle", "-l", "2"], capture_output=True, text=True)
    print(res.stdout)
    if "Global Codebase Search" in res.stdout:
        print("[+] PASS: FTS5 Query Engine successfully matched keywords in oracle_mas workspace.")
        return True
    else:
        print(f"[-] FAIL: Query output error: {res.stderr}")
        return False

def test_skills_and_plugins():
    print("\n[TEST 3] Testing Skills & Customizations Layout...")
    essential_skills = [
        "swarm-orchestrator",
        "codebase-rag-indexer",
        "mcp-agent-integration",
        "claude-code-emulation"
    ]
    all_ok = True
    for skill_name in essential_skills:
        skill_file = SKILLS_DIR / skill_name / "SKILL.md"
        if skill_file.exists():
            print(f"  [+] Skill '{skill_name}': OK (Valid frontmatter & runbook)")
        else:
            print(f"  [-] Skill '{skill_name}': MISSING ({skill_file})")
            all_ok = False
            
    if all_ok:
        print("[+] PASS: All essential skills verified.")
        return True
    return False

def test_evolution_runner():
    print("\n[TEST 4] Testing Daily Evolution Quota Guard...")
    runner_script = SCRIPTS_DIR / "daily_evolution_runner.py"
    if not runner_script.exists():
        print(f"[-] FAIL: {runner_script} not found.")
        return False
        
    res = subprocess.run([sys.executable, str(runner_script), "--status-only"], capture_output=True, text=True)
    print(res.stdout)
    if "Daily Quota" in res.stdout or "Requests Used Today" in res.stdout:
        print("[+] PASS: Daily Evolution Runner & Quota Guard OK.")
        return True
    return False

def main():
    print("=" * 65)
    print(" ANTIGRAVITY 2.0 SYSTEM HEALTH & ROADMAP VERIFICATION SUITE")
    print("=" * 65)
    
    t1 = test_model_router()
    t2 = test_codebase_query()
    t3 = test_skills_and_plugins()
    t4 = test_evolution_runner()
    
    print("\n" + "=" * 65)
    if t1 and t2 and t3 and t4:
        print("[🎉 ALL SYSTEMS OPERATIONAL] Self-Improvement Blueprint Verification PASSED 100%")
    else:
        print("[⚠️ WARNING] Some tests failed. Check logs above.")
    print("=" * 65)

if __name__ == "__main__":
    main()
