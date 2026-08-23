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

# Import indexer from skill path
skill_scripts = Path(r"C:\Users\deomo\.gemini\config\skills\codebase-rag-indexer\scripts")
if str(skill_scripts) not in sys.path:
    sys.path.insert(0, str(skill_scripts))

from indexer import CodebaseIndexer, GLOBAL_DB_PATH

WORKSPACE_ALIASES = {
    "oracle": "oracle_mas",
    "oracle_mas": "oracle_mas",
    "saiyan": "AI_Saiyan_System",
    "ai_saiyan": "AI_Saiyan_System",
    "ai_saiyan_system": "AI_Saiyan_System",
    "ui": "agent_office_ui",
    "agent_office_ui": "agent_office_ui",
    "ca": "CA - Copy",
    "ca_copy": "CA - Copy",
    "tnd": "CA - Copy",
    "pod": "CA - Copy",
    "krua": "ครัวพอใจ",
    "pojai": "ครัวพอใจ",
    "ครัวพอใจ": "ครัวพอใจ"
}

def resolve_workspace(name: str):
    if not name:
        return None
    name_clean = name.strip().lower()
    return WORKSPACE_ALIASES.get(name_clean, name)

def query_global_codebase(query_str: str, workspace_filter: str = None, limit: int = 8, symbol_only: bool = False):
    if not GLOBAL_DB_PATH.exists():
        print("[!] Global index database not found. Building index first...")
        indexer = CodebaseIndexer(db_path=str(GLOBAL_DB_PATH))
        indexer.index_all_workspaces()
    else:
        indexer = CodebaseIndexer(db_path=str(GLOBAL_DB_PATH))

    target_ws = resolve_workspace(workspace_filter)
    results = indexer.query(query_str, workspace_filter=target_ws, limit=limit)
    
    if symbol_only:
        results = [r for r in results if r[2] in ('function', 'class', 'symbol')]

    if not results:
        print(f"[*] No matching results found across codebases for '{query_str}' (Filter: {target_ws or 'All'}).")
        return []

    print(f"\n=== Global Codebase Search: '{query_str}' ({len(results)} matches, Workspace: {target_ws or 'ALL'}) ===")
    for ws, filepath, item_type, name, start, end, content in results:
        header = f"[{ws}] [{item_type.upper()}] {filepath}"
        if name:
            header += f" -> {name}"
        header += f" (Lines {start}-{end})"
        print(header)
        print("-" * min(len(header), 80))
        lines = content.splitlines()
        snippet = '\n'.join(lines[:6])
        if len(lines) > 6:
            snippet += "\n..."
        print(snippet)
        print("=" * 60)
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query Antigravity Global Codebase Index")
    parser.add_argument("query_pos", nargs="?", default=None, help="Positional search query")
    parser.add_argument("--query", "-q", help="Search query or symbol")
    parser.add_argument("--workspace", "-w", help="Filter by workspace (e.g. oracle, saiyan, ca, krua)")
    parser.add_argument("--limit", "-l", type=int, default=8, help="Max results")
    parser.add_argument("--symbols", "-s", action="store_true", help="Filter for classes and functions only")
    parser.add_argument("--reindex", action="store_true", help="Rebuild global index across all workspaces")

    args = parser.parse_args()
    search_text = args.query or args.query_pos

    if args.reindex:
        indexer = CodebaseIndexer(db_path=str(GLOBAL_DB_PATH))
        indexer.index_all_workspaces()
        
    if search_text:
        query_global_codebase(search_text, workspace_filter=args.workspace, limit=args.limit, symbol_only=args.symbols)
    elif not args.reindex:
        parser.print_help()
