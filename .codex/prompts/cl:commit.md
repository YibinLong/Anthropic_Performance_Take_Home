---
description: "Create git commits with user approval and no Claude attribution"
---

<!-- Migrated from .claude/commands/cl/commit.md. Use /prompts:cl:commit (or type /cl:commit and select it in slash popup). -->

## Codex Compatibility Notes

- `codebase-locator` -> `/prompts:cl:agent:codebase-locator`
- `codebase-analyzer` -> `/prompts:cl:agent:codebase-analyzer`
- `codebase-pattern-finder` -> `/prompts:cl:agent:codebase-pattern-finder`
- `web-search-researcher` -> `/prompts:cl:agent:web-search-researcher`
- When delegation is needed, use `spawn_agent` with a clear role-specific prompt (prefer `explorer` for codebase analysis).



# Commit Changes

You are tasked with creating git commits for the changes made during this session.

## Process:

1. **Think about what changed:**
   - Review the conversation history and understand what was accomplished
   - Run `git status` to see current changes
   - Run `git diff` to understand the modifications
   - Consider whether changes should be one commit or multiple logical commits

2. **Plan your commit(s):**
   - Identify which files belong together
   - Draft clear, descriptive commit messages
   - Use imperative mood in commit messages
   - Focus on why the changes were made, not just what

3. **Present your plan to the user:**
   - List the files you plan to add for each commit
   - Show the commit message(s) you'll use
   - Ask: "I plan to create [N] commit(s) with these changes. Shall I proceed?"

4. **Execute upon confirmation:**
   - Use `git add` with specific files (never use `-A` or `.`)
   - Create commits with your planned messages
   - Show the result with `git log --oneline -n [number]`

## Important:
- **NEVER add co-author information or Claude attribution**
- Commits should be authored solely by the user
- Do not include any "Generated with Claude" messages
- Do not add "Co-Authored-By" lines
- Write commit messages as if the user wrote them

## Remember:
- You have the full context of what was done in this session
- Group related changes together
- Keep commits focused and atomic when possible
- The user trusts your judgment - they asked you to commit
