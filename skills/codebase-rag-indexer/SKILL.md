---
name: codebase-rag-indexer
description: Installs and manages a local codebase indexing and search engine using Python and SQLite FTS5. Allows fast keyword and semantic-like queries across workspace files.
---

# Codebase RAG Indexer Skill

This skill allows the agent to index, parse, and search codebases locally using a lightweight Python script (`scripts/indexer.py`) and SQLite FTS5 virtual tables.

## Purpose & Advantages
- **100% Local:** No data is sent to external LLMs or vector databases.
- **Fast Search:** Uses SQLite's virtual Full-Text Search (FTS5) for sub-second keyword and symbol matching.
- **AST-Aware Chunking:** Chunks files by classes and functions (supporting Python, Go, JS, TS) instead of arbitrary line boundaries.
- **Zero Dependencies:** Runs on standard Python libraries (`sqlite3`, `re`, `argparse`, `pathlib`).

## Usage Instructions

### 1. Indexing a Workspace
To scan and index all code files inside a workspace:
```bash
python scripts/indexer.py --workspace "c:/Users/deomo/oracle_mas" --index
```
This scans all `.py`, `.js`, `.ts`, `.go`, `.java` files, extracts classes and functions, and indexes them in `c:/Users/deomo/oracle_mas/.agents/codebase_index.db`.

### 2. Searching the Index
To search the codebase for specific functions, keywords, or variables:
```bash
python scripts/indexer.py --workspace "c:/Users/deomo/oracle_mas" --query "ema_cross"
```
Returns a list of matching filepaths, type (file/class/function), start/end lines, and matching snippets.
