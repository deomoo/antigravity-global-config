import os
import re
import sqlite3
import argparse
from pathlib import Path

# Ignore patterns
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', 'venv', '.env', 
    '.onboard', '.agent_office', '.agents', 'dist', 'build'
}

IGNORE_EXTENSIONS = {
    '.exe', '.dll', '.so', '.pyc', '.png', '.jpg', '.jpeg', 
    '.gif', '.zip', '.tar', '.gz', '.db', '.sqlite', '.log'
}

SUPPORTED_EXTENSIONS = {
    '.py', '.js', '.ts', '.go', '.java', '.c', '.cpp', '.h', 
    '.md', '.txt', '.yaml', '.yml', '.json', '.html', '.css'
}

def clean_path(path):
    return str(Path(path).resolve()).replace('\\', '/')

class CodebaseIndexer:
    def __init__(self, workspace_path, db_path=None):
        self.workspace = Path(workspace_path).resolve()
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            self.db_path = self.workspace / '.agents' / 'codebase_index.db'
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
        self.conn = None
        self.cursor = None

    def open_db(self):
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        # Enable FTS5 virtual table
        self.cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS codebase_search USING fts5(
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

    def clear_index(self):
        self.cursor.execute("DELETE FROM codebase_search;")
        self.conn.commit()

    def parse_python_file(self, filepath, content):
        """Simple indentation-based Python parser to extract classes and functions."""
        lines = content.splitlines()
        chunks = []
        
        # Regexes
        class_re = re.compile(r'^class\s+(\w+)')
        def_re = re.compile(r'^(\s*)def\s+(\w+)')
        
        current_class = None
        
        for idx, line in enumerate(lines):
            line_num = idx + 1
            
            # Match class
            class_match = class_re.match(line)
            if class_match:
                class_name = class_match.group(1)
                # Find end of class (until indentation returns to 0)
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
                
            # Match def
            def_match = def_re.match(line)
            if def_match:
                indent = len(def_match.group(1))
                def_name = def_match.group(2)
                
                # Check end of function based on indentation
                end_idx = idx
                for j in range(idx + 1, len(lines)):
                    next_line = lines[j]
                    if next_line.strip():
                        # Count indentation of next non-empty line
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

    def chunk_file(self, filepath, content):
        chunks = []
        rel_path = clean_path(filepath.relative_to(self.workspace))
        
        # Always index the whole file first
        chunks.append({
            'filepath': rel_path,
            'type': 'file',
            'name': filepath.name,
            'content': content,
            'start_line': 1,
            'end_line': len(content.splitlines())
        })
        
        # Extract specific structures for Python
        if filepath.suffix == '.py':
            try:
                structures = self.parse_python_file(filepath, content)
                for struct in structures:
                    struct['filepath'] = rel_path
                    chunks.append(struct)
            except Exception as e:
                # Fallback on parsing error
                pass
                
        return chunks

    def index_all(self, dry_run=False):
        self.open_db()
        if not dry_run:
            self.clear_index()
            
        file_count = 0
        chunk_count = 0
        
        for root, dirs, files in os.walk(self.workspace):
            # Prune directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix in IGNORE_EXTENSIONS:
                    continue
                if file_path.suffix not in SUPPORTED_EXTENSIONS:
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    chunks = self.chunk_file(file_path, content)
                    file_count += 1
                    chunk_count += len(chunks)
                    
                    if not dry_run:
                        for chunk in chunks:
                            self.cursor.execute(
                                "INSERT INTO codebase_search (filepath, type, name, content, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?);",
                                (chunk['filepath'], chunk['type'], chunk['name'], chunk['content'], chunk['start_line'], chunk['end_line'])
                            )
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    
        if not dry_run:
            self.conn.commit()
            print(f"Indexed {file_count} files into {chunk_count} search segments.")
        else:
            print(f"[Dry-Run] Scanned {file_count} files yielding {chunk_count} search segments.")
            
        self.close_db()

    def query(self, search_term):
        self.open_db()
        self.cursor.execute("""
            SELECT filepath, type, name, start_line, end_line, content
            FROM codebase_search 
            WHERE content MATCH ? 
            LIMIT 15;
        """, (search_term,))
        results = self.cursor.fetchall()
        self.close_db()
        return results

def main():
    parser = argparse.ArgumentParser(description="SQLite-based local codebase indexer & RAG query tool.")
    parser.add_argument("--workspace", required=True, help="Path to workspace root directory.")
    parser.add_argument("--db", help="Path to custom SQLite DB.")
    parser.add_argument("--index", action="store_true", help="Perform indexing of codebase.")
    parser.add_argument("--dry-run", action="store_true", help="Index dry-run (no database writes).")
    parser.add_argument("--query", help="Search the codebase using the index.")
    
    args = parser.parse_args()
    
    indexer = CodebaseIndexer(args.workspace, args.db)
    
    if args.index or args.dry_run:
        indexer.index_all(dry_run=args.dry_run)
    elif args.query:
        results = indexer.query(args.query)
        if not results:
            print("No matching results found.")
            return
            
        print(f"Found {len(results)} matches:\n" + "="*60)
        for filepath, item_type, name, start, end, content in results:
            header = f"[{item_type.upper()}] {filepath}"
            if name:
                header += f" -> {name}"
            header += f" (Lines {start}-{end})"
            print(header)
            print("-"*len(header))
            
            # Print first 5 lines of content as snippet
            lines = content.splitlines()
            snippet = '\n'.join(lines[:8])
            if len(lines) > 8:
                snippet += "\n..."
            print(snippet)
            print("="*60)

if __name__ == "__main__":
    main()
