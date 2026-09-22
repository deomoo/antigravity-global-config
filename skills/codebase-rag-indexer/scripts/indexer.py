import os
import sys
import re
import sqlite3
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Fix Windows stdout encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

# Default Known Workspaces
KNOWN_WORKSPACES = [
    r"c:\Users\deomo\oracle_mas",
    r"d:\AI_Saiyan_System",
    r"d:\AI_Saiyan_System\agent_office_ui",
    r"d:\CA - Copy",
    r"c:\Users\deomo\OneDrive\ครัวพอใจ"
]

GLOBAL_DB_PATH = Path(r"C:\Users\deomo\.gemini\config\global_codebase_index.db")

# Ignore patterns
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', 'venv', '.env', 
    '.onboard', '.agent_office', '.agents', 'dist', 'build',
    '.dart_tool', '.idea', '.vscode'
}

IGNORE_EXTENSIONS = {
    '.exe', '.dll', '.so', '.pyc', '.png', '.jpg', '.jpeg', 
    '.gif', '.zip', '.tar', '.gz', '.db', '.sqlite', '.log',
    '.ico', '.pdf', '.bin', '.parquet'
}

SUPPORTED_EXTENSIONS = {
    '.py', '.js', '.ts', '.go', '.java', '.c', '.cpp', '.h', 
    '.md', '.txt', '.yaml', '.yml', '.json', '.html', '.css',
    '.dart', '.sql'
}

def clean_path(path):
    return str(Path(path).resolve()).replace('\\', '/')

class CodebaseIndexer:
    def __init__(self, workspace_path: Optional[str] = None, db_path: Optional[str] = None):
        self.workspace = Path(workspace_path).resolve() if workspace_path else None
        if db_path:
            self.db_path = Path(db_path).resolve()
        elif self.workspace:
            self.db_path = self.workspace / '.agents' / 'codebase_index.db'
        else:
            self.db_path = GLOBAL_DB_PATH
            
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.cursor = None

    def open_db(self):
        self.conn = sqlite3.connect(str(self.db_path))
        self.cursor = self.conn.cursor()
        # Enable FTS5 virtual table
        self.cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS codebase_search USING fts5(
                workspace,
                filepath,
                type,        -- 'file', 'class', 'function', 'block'
                name,        -- name of class/function/symbol
                content,     -- code or text content
                start_line UNINDEXED,
                end_line UNINDEXED
            );
        """)
        self.conn.commit()

    def close_db(self):
        if self.conn:
            self.conn.close()

    def clear_index(self, workspace_filter: Optional[str] = None):
        if workspace_filter:
            self.cursor.execute("DELETE FROM codebase_search WHERE workspace = ?;", (workspace_filter,))
        else:
            self.cursor.execute("DELETE FROM codebase_search;")
        self.conn.commit()

    def parse_python_file(self, filepath: Path, content: str) -> List[Dict[str, Any]]:
        """Extract classes and functions from Python files."""
        lines = content.splitlines()
        chunks = []
        class_re = re.compile(r'^class\s+(\w+)')
        def_re = re.compile(r'^(\s*)def\s+(\w+)')
        
        current_class = None
        
        for idx, line in enumerate(lines):
            line_num = idx + 1
            class_match = class_re.match(line)
            if class_match:
                class_name = class_match.group(1)
                end_idx = idx
                for j in range(idx + 1, len(lines)):
                    if lines[j].strip() and not lines[j].startswith(' '):
                        break
                    end_idx = j
                
                class_content = '\n'.join(lines[idx:end_idx+1])
                chunks.append({
                    'type': 'class',
                    'name': class_name,
                    'content': class_content,
                    'start_line': line_num,
                    'end_line': end_idx + 1
                })
                current_class = class_name
                continue
                
            def_match = def_re.match(line)
            if def_match:
                indent = len(def_match.group(1))
                def_name = def_match.group(2)
                end_idx = idx
                for j in range(idx + 1, len(lines)):
                    next_line = lines[j]
                    if next_line.strip():
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if next_indent <= indent:
                            break
                    end_idx = j
                
                def_content = '\n'.join(lines[idx:end_idx+1])
                full_name = f"{current_class}.{def_name}" if (current_class and indent > 0) else def_name
                chunks.append({
                    'type': 'function',
                    'name': full_name,
                    'content': def_content,
                    'start_line': line_num,
                    'end_line': end_idx + 1
                })
                
        return chunks

    def chunk_file(self, target_workspace: Path, filepath: Path, content: str) -> List[Dict[str, Any]]:
        chunks = []
        try:
            rel_path = clean_path(filepath.relative_to(target_workspace))
        except ValueError:
            rel_path = clean_path(filepath)
            
        chunks.append({
            'workspace': target_workspace.name,
            'filepath': rel_path,
            'type': 'file',
            'name': filepath.name,
            'content': content,
            'start_line': 1,
            'end_line': len(content.splitlines())
        })
        
        if filepath.suffix == '.py':
            try:
                structures = self.parse_python_file(filepath, content)
                for struct in structures:
                    struct['workspace'] = target_workspace.name
                    struct['filepath'] = rel_path
                    chunks.append(struct)
            except Exception:
                pass
                
        return chunks

    def index_workspace(self, workspace_path: Path, dry_run: bool = False) -> Tuple[int, int]:
        target_ws = Path(workspace_path).resolve()
        if not target_ws.exists():
            print(f"[!] Skipping non-existent workspace: {target_ws}")
            return 0, 0
            
        file_count = 0
        chunk_count = 0
        
        for root, dirs, files in os.walk(target_ws):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix in IGNORE_EXTENSIONS or file_path.suffix not in SUPPORTED_EXTENSIONS:
                    continue
                if file_path.stat().st_size > 1024 * 1024:  # Skip files larger than 1MB
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    chunks = self.chunk_file(target_ws, file_path, content)
                    file_count += 1
                    chunk_count += len(chunks)
                    
                    if not dry_run:
                        for chunk in chunks:
                            self.cursor.execute(
                                "INSERT INTO codebase_search (workspace, filepath, type, name, content, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?);",
                                (chunk['workspace'], chunk['filepath'], chunk['type'], chunk['name'], chunk['content'], chunk['start_line'], chunk['end_line'])
                            )
                except Exception as e:
                    pass
                    
        return file_count, chunk_count

    def index_all_workspaces(self, dry_run: bool = False):
        self.open_db()
        if not dry_run:
            self.clear_index()
            
        total_files = 0
        total_chunks = 0
        print(f"[*] Starting Global Codebase Indexing across active workspaces...")
        
        for ws_str in KNOWN_WORKSPACES:
            ws_path = Path(ws_str)
            if ws_path.exists():
                f_count, c_count = self.index_workspace(ws_path, dry_run=dry_run)
                total_files += f_count
                total_chunks += c_count
                print(f"    [+] Workspace [{ws_path.name}]: {f_count} files, {c_count} indexed chunks.")
                
        if not dry_run:
            self.conn.commit()
            print(f"\n[+] Successfully created Global Index: {total_files} files, {total_chunks} chunks stored at {self.db_path}")
        self.close_db()

    def query(self, search_term: str, workspace_filter: Optional[str] = None, limit: int = 10) -> List[Tuple]:
        self.open_db()
        # Clean search term for FTS5 (escape special chars)
        clean_query = re.sub(r'[^\w\s]', ' ', search_term).strip()
        if not clean_query:
            self.close_db()
            return []
            
        # Format for FTS5 prefix match
        terms = clean_query.split()
        fts_query = " ".join([f'"{t}"*' for t in terms])
        
        if workspace_filter:
            sql = """
                SELECT workspace, filepath, type, name, start_line, end_line, content
                FROM codebase_search 
                WHERE workspace = ? AND codebase_search MATCH ? 
                LIMIT ?;
            """
            self.cursor.execute(sql, (workspace_filter, fts_query, limit))
        else:
            sql = """
                SELECT workspace, filepath, type, name, start_line, end_line, content
                FROM codebase_search 
                WHERE codebase_search MATCH ? 
                LIMIT ?;
            """
            self.cursor.execute(sql, (fts_query, limit))
            
        results = self.cursor.fetchall()
        self.close_db()
        return results

def main():
    parser = argparse.ArgumentParser(description="SQLite FTS5 Local Codebase Indexer")
    parser.add_argument("--workspace", help="Path to workspace root directory.")
    parser.add_argument("--all-workspaces", action="store_true", help="Index all known active workspaces into global DB.")
    parser.add_argument("--db", help="Path to custom SQLite DB.")
    parser.add_argument("--index", action="store_true", help="Perform indexing.")
    parser.add_argument("--dry-run", action="store_true", help="Index dry-run.")
    parser.add_argument("--query", help="Search the codebase using the index.")
    
    args = parser.parse_args()
    
    indexer = CodebaseIndexer(workspace_path=args.workspace, db_path=args.db)
    
    if args.all_workspaces or (args.index and not args.workspace):
        indexer.index_all_workspaces(dry_run=args.dry_run)
    elif args.workspace and args.index:
        indexer.open_db()
        if not args.dry_run:
            indexer.clear_index()
        f_c, c_c = indexer.index_workspace(Path(args.workspace), dry_run=args.dry_run)
        if not args.dry_run:
            indexer.conn.commit()
        indexer.close_db()
        print(f"Indexed {f_c} files and {c_c} chunks for workspace {args.workspace}")
    elif args.query:
        results = indexer.query(args.query)
        if not results:
            print(f"No matching results found for '{args.query}'.")
            return
            
        print(f"Found {len(results)} matches for '{args.query}':\n" + "="*60)
        for ws, filepath, item_type, name, start, end, content in results:
            header = f"[{ws}] [{item_type.upper()}] {filepath}"
            if name:
                header += f" -> {name}"
            header += f" (Lines {start}-{end})"
            print(header)
            print("-" * len(header))
            
            lines = content.splitlines()
            snippet = '\n'.join(lines[:6])
            if len(lines) > 6:
                snippet += "\n..."
            print(snippet)
            print("="*60)

if __name__ == "__main__":
    main()
