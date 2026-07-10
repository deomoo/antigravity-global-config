---
name: mcp-agent-integration
description: Instructions and configuration templates for installing, running, and managing local Model Context Protocol (MCP) servers (GitHub, SQLite, PostgreSQL, Filesystem).
---

# MCP Agent Integration Skill

This skill guides the agent in configuring and utilizing Model Context Protocol (MCP) servers locally to expand capabilities.

## Available Servers & Installation

### 1. GitHub MCP Server (`@modelcontextprotocol/server-github`)
Allows the agent to interact with GitHub repositories, issues, pull requests, and code search.
- **Run Command (npm/npx):**
  ```bash
  npx -y @modelcontextprotocol/server-github
  ```
- **Required Environment Variables:**
  - `GITHUB_PERSONAL_ACCESS_TOKEN`: Classic token or Fine-grained PAT with repo and issue scopes.

### 2. SQLite MCP Server (`mcp-server-sqlite`)
Exposes SQLite database reading, querying, and schema analysis to the agent.
- **Run Command:**
  ```bash
  npx -y mcp-server-sqlite /path/to/database.db
  ```

### 3. Filesystem MCP Server (`@modelcontextprotocol/server-filesystem`)
Gives secure, read/write tool-use capabilities to designated directories.
- **Run Command:**
  ```bash
  npx -y @modelcontextprotocol/server-filesystem <allowed-directory-1> <allowed-directory-2>
  ```

---

## Configuration Setup (JSON)

Add the server definitions directly to your host's configurations (like `mcp_config.json` or client config). Use absolute paths for directories and ensure credentials are set securely in user environment variables.
