import os
import sys
import urllib.request
import json
import base64
import time
from datetime import datetime

TOKEN = "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"
REPO = "deomoo/antigravity-global-config"
CONFIG_DIR = r"C:\Users\deomo\.gemini\config"
BRANCH = "main"

def request_github(url, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("User-Agent", "Python-urllib")
    req.add_header("Accept", "application/vnd.github.v3+json")
    if data:
        req.add_header("Content-Type", "application/json")
        req_data = json.dumps(data).encode("utf-8")
    else:
        req_data = None
    try:
        with urllib.request.urlopen(req, data=req_data) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        return {"error": str(e)}

def pull_files(force=False):
    last_pull_file = os.path.join(CONFIG_DIR, ".last_pull")
    if not force and os.path.exists(last_pull_file):
        mtime = os.path.getmtime(last_pull_file)
        if time.time() - mtime < 900: # 15 minutes cache
            print("Recently pulled. Skipping.")
            return
            
    try:
        with open(last_pull_file, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass
        
    print("Pulling memory changes from GitHub...")
    tree_url = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
    tree_data = request_github(tree_url)
    if "error" in tree_data or "tree" not in tree_data:
        print(f"Failed to fetch tree: {tree_data}")
        return
        
    for item in tree_data["tree"]:
        if item.get("type") == "blob":
            path = item.get("path")
            # Skip updating the sync script itself if it's running
            if path == "scripts/sync_memory.py":
                continue
            local_path = os.path.join(CONFIG_DIR, path.replace("/", os.sep))
            
            content_url = f"https://api.github.com/repos/{REPO}/contents/{path}"
            content_data = request_github(content_url)
            if isinstance(content_data, dict) and "content" in content_data:
                try:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    decoded = base64.b64decode(content_data["content"].replace("\n", "").replace("\r", ""))
                    
                    write_file = True
                    if os.path.exists(local_path):
                        with open(local_path, "rb") as f:
                            local_content = f.read()
                        if local_content == decoded:
                            write_file = False
                            
                    if write_file:
                        with open(local_path, "wb") as f:
                            f.write(decoded)
                        print(f"Pulled {path}")
                except Exception as err:
                    print(f"Error saving {path}: {err}")

def push_files(commit_msg):
    print(f"Pushing memory changes to GitHub: {commit_msg}")
    
    # Priority 1: Try native Git CLI (uses Windows Credential Manager)
    try:
        import subprocess
        subprocess.run(["git", "-C", CONFIG_DIR, "add", "."], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", CONFIG_DIR, "commit", "-m", commit_msg], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        push_res = subprocess.run(["git", "-C", CONFIG_DIR, "push"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if push_res.returncode == 0:
            print("Pushed memory changes via Git successfully.")
            return
        else:
            print(f"Git CLI push returned code {push_res.returncode}. Falling back to REST API...")
    except Exception as git_err:
        print(f"Git CLI failed ({git_err}). Falling back to REST API...")

    # Priority 2: Fallback to GitHub REST API
    files_to_push = []
    for root, dirs, files in os.walk(CONFIG_DIR):
        if ".git" in root:
            continue
        for file in files:
            if file in (".last_pull", "github_token.txt"):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, CONFIG_DIR).replace(os.sep, "/")
            files_to_push.append((full_path, rel_path))
            
    for local_path, rel_path in files_to_push:
        try:
            with open(local_path, "rb") as f:
                local_content = f.read()
                
            content_url = f"https://api.github.com/repos/{REPO}/contents/{rel_path}"
            remote_data = request_github(content_url)
            
            remote_sha = None
            remote_content = None
            if isinstance(remote_data, dict) and "sha" in remote_data:
                remote_sha = remote_data["sha"]
                if "content" in remote_data:
                    remote_content = base64.b64decode(remote_data["content"].replace("\n", "").replace("\r", ""))
                    
            if remote_content == local_content:
                continue
                
            print(f"Uploading {rel_path}...")
            payload = {
                "message": commit_msg,
                "content": base64.b64encode(local_content).decode("utf-8"),
                "branch": BRANCH
            }
            if remote_sha:
                payload["sha"] = remote_sha
                
            res = request_github(content_url, method="PUT", data=payload)
            if "error" in res:
                print(f"Failed to push {rel_path}: {res['error']}")
            else:
                print(f"Pushed {rel_path}")
        except Exception as e:
            print(f"Error pushing {rel_path}: {e}")

def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "pull":
            pull_files(force=True)
        elif len(sys.argv) > 1 and sys.argv[1] == "pull_lazy":
            pull_files(force=False)
        else:
            commit_msg = sys.argv[1] if len(sys.argv) > 1 else f"Auto-update memory: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            push_files(commit_msg)
    except Exception as e:
        print(f"Global sync script error: {e}")
        sys.exit(0)

if __name__ == "__main__":
    main()

