---
name: onboard-cli-agent-workflow
description: Procedures and commands for the agent to programmatically call Onboard-CLI commands to analyze codebase structure, check import limits, and inspect refactoring blast radius.
---

# Onboard-CLI Agent Workflow Skill

This skill outlines how the agent can use Onboard-CLI programmatically in its own execution trajectory to safely analyze code structures and prevent code regressions.

## Programmatic Codebase Checks

### 1. Verify Architecture & Import Rules (Drift)
Before making modifications to project modules, the agent should run a drift check to verify that existing code conforms to specified boundaries:
```bash
onboard drift --rules architecture.yaml
```
If this command reports errors or violations, the agent must ensure its modifications do not introduce additional import leaks.

### 2. Identify Routing & Handlers
When working on API codebases, the agent can map routes directly:
```bash
onboard routes --framework fastapi --protocol rest
```
*(Supports frameworks like Gin, Express, FastAPI, and Spring Boot)*.

### 3. Check Blast Radius (Impact)
The agent can query how changes to a specific file will propagate using the impact analysis:
```bash
onboard impact --target "core/strategy.py"
```
This lists all dependent files that will be affected by the modifications, helping the agent structure tests and verification steps.
