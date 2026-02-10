# Claude Compatibility

This repository keeps legacy Claude command/agent specs under `./.claude` and exposes Codex-compatible prompt aliases under `./.codex/prompts`.

## `/cl:*` Alias Behavior

When a user message starts with `/cl:`:

1. Parse command token up to first whitespace.
2. Resolve alias `/cl:<name>` to `/prompts:cl:<name>`.
3. If `./.codex/prompts/cl:<name>.md` exists, treat it as the canonical command definition.
4. If no migrated prompt exists, fallback to `./.claude/commands/cl/<name>.md`.
5. If command is unknown, list available commands from `./.codex/prompts/cl:*.md`.

## Agent Role Aliases

For `/cl:agent:<name>`:

1. Prefer `./.codex/prompts/cl:agent:<name>.md`.
2. Fallback to `./.claude/agents/cl/<name>.md`.

## Maintenance

- Regenerate migrated prompts with:
  - `tools/sync_claude_to_codex_prompts.sh`
- Regenerate and install into active Codex prompt directory:
  - `tools/sync_claude_to_codex_prompts.sh --install`
