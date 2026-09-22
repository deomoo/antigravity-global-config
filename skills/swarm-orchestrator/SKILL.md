---
name: swarm-orchestrator
description: Guidelines and routines for parallel subagent swarm orchestration, role specialization, task partitioning, and inter-agent communication protocols in Antigravity.
---

# Antigravity Swarm Orchestrator & Parallel Subagents

This skill provides operational patterns, templates, and protocols for orchestrating multiple specialized AI subagents in parallel using Antigravity's `define_subagent` and `invoke_subagent` capabilities.

---

## 👥 1. The Standard AI Agent Office Roster

When assigning complex, multi-faceted engineering tasks, decompose the workload and delegate to these standardized roles:

| Agent Name | Type ID | Specialized Role | Best Fit Tasks |
| :--- | :--- | :--- | :--- |
| **Vanguard** | `vanguard` | Product Strategist | Architecture design, UX flows, ROI trade-offs, high-level feasibility review |
| **CodeCraft** | `codecraft` | Software Engineer | Clean code generation, refactoring, library integration, bug fixing |
| **Sentinel** | `sentinel` | QA Risk Reviewer | Static analysis, security auditing, edge-case analysis, test verification |
| **Synthesizer** | `synthesizer` | Token & System Optimizer | Token compression, prompt distillation, FTS5/RAG memory indexing, log cleanups |
| **Scout** | `scout` | Data Miner & Knowledge Architect | External web research, documentation scraping, paper analysis, quantitative data parsing |
| **Hermes** | `hermes` | Secretary & Automation Bridge | OS desktop automation, notification routing (LINE/Telegram), scheduled cron coordination |

---

## ⚡ 2. Parallel Delegation Protocol

### Step 1: Workload Decomposition
Break large tasks into independent, non-blocking units (e.g., CodeCraft generates the implementation while Sentinel concurrently drafts unit tests and edge-case suites).

### Step 2: Parallel Subagent Invocation
Invoke multiple subagents concurrently in a single tool call:

```json
{
  "Subagents": [
    {
      "TypeName": "codecraft",
      "Role": "Software Engineer",
      "Model": "pro",
      "Prompt": "Implement the volume profile POC/VAH calculation module in Python."
    },
    {
      "TypeName": "sentinel",
      "Role": "QA Risk Reviewer",
      "Model": "flash",
      "Prompt": "Review volume profile edge cases (zero volume bars, market gaps) and design pytest test cases."
    }
  ]
}
```

### Step 3: Context Isolation & Workspace Branching
- Default to `Workspace: "inherit"` for read/write on the same project tree.
- Use `Workspace: "branch"` or `Workspace: "share"` when running high-churn or exploratory spikes to avoid polluting the main context.

### Step 4: Consolidated Walkthrough
The parent agent acts as the conductor:
1. Receive asynchronous task completion signals via reactive wakeups (no polling needed).
2. Synthesize results from all subagents.
3. Produce a consolidated `walkthrough.md` report for the user.
