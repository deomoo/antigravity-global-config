---
name: claude-code-emulation
description: High-precision agent execution guidelines based on Claude Code principles (Opus 4.8 level), focusing on line-range file reading, local symbol indexing, and strict context pruning for maximum token savings.
---

# Claude Code Emulation Skill (Opus 4.8 level)

This skill instructs the agent on how to emulate high-performance, token-efficient, and precise code execution workflows similar to Claude Code.

## Core Rules for Token Saving & Precision

### 1. targeted File Viewing (Context Pruning)
Do NOT read entire files. Reading 500-1000 lines of code consumes vast amounts of tokens and fills the context with noise.
- **Rule:** Use local search/indexing (e.g. `codebase-rag-indexer`) or `grep_search` to find the exact line numbers of functions or blocks.
- **Action:** Specify `StartLine` and `EndLine` in the `view_file` tool call. Limit reading to 30-100 lines at a time.

### 2. Pre-Commit Syntax Validation
Always verify the syntax of any file you create or edit before reporting back to the user.
- **Python:** Run `python -m py_compile <filepath>`
- **Node.js/JS:** Run `node --check <filepath>`
- **Compilation check:** Run the compiler command if the language is compiled.

### 3. Step-by-Step Executions
Never bundle multiple actions into a single large step unless they are well-defined.
- Run a command, analyze the result, then run the next.
- Validate that previous files are saved successfully before launching builds or tests.
