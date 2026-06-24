import subprocess
import os
import sys
from datetime import datetime

CONFIG_DIR = r"C:\Users\deomo\.gemini\config"

def run_git(args):
    result = subprocess.run(["git"] + args, cwd=CONFIG_DIR, capture_output=True, text=True)
    return result

def main():
    commit_msg = sys.argv[1] if len(sys.argv) > 1 else f"Auto-update memory: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    # Check if .git exists
    git_dir = os.path.join(CONFIG_DIR, ".git")
    if not os.path.exists(git_dir):
        print("Git is not initialized in the configuration directory.")
        return
        
    status = run_git(["status", "--porcelain"])
    if not status.stdout.strip():
        print("No changes detected in config/memory.")
        return
        
    print("Changes detected. Staging files...")
    run_git(["add", "."])
    
    print(f"Committing with message: '{commit_msg}'")
    commit_res = run_git(["commit", "-m", commit_msg])
    if commit_res.returncode != 0:
        print(f"Commit failed: {commit_res.stderr.strip()}")
        return
        
    print("Pushing to remote repository...")
    push_res = run_git(["push", "origin", "main"])
    if push_res.returncode == 0:
        print("✅ Successfully synced memory and skills to GitHub!")
    else:
        print(f"❌ Push failed:\n{push_res.stderr.strip()}")

if __name__ == "__main__":
    main()
