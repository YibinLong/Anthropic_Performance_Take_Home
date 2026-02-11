---
description: "List migrated Claude-compatible cl:* prompts"
---

# Claude-Compatible Prompt Commands

Available command prompts (invoke with `/prompts:<name>`):
- `/prompts:cl:agent:codebase-analyzer`
- `/prompts:cl:agent:codebase-locator`
- `/prompts:cl:agent:codebase-pattern-finder`
- `/prompts:cl:agent:web-search-researcher`
- `/prompts:cl:commit`
- `/prompts:cl:create_plan`
- `/prompts:cl:describe_pr`
- `/prompts:cl:implement_plan`
- `/prompts:cl:iterate_plan`
- `/prompts:cl:research_codebase`

Shortcut in interactive TUI: type `/cl:<name>` and pick the matching prompt from the slash popup.

Agent-role prompts are namespaced as `cl:agent:*` and can be used directly as reusable role templates.
