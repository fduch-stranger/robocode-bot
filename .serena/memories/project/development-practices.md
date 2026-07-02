# Development Practices

General rules:
- Before behavior, tooling, or architecture changes, list Serena memories and read the project memories that match the task.
- Prefer Serena and JetBrains/IDE MCP tools for symbol lookup, references, renames, moves, safe deletes, and inspections when they can improve accuracy or reduce broad text scans.
- Do not revert unrelated user changes in the working tree.
- Avoid committing generated artifacts: `.venv/`, `.env`, `dist/`, `battle-results/`, `legacy-bots/`, caches, `.DS_Store`.
- Do not add absolute local paths, usernames, or machine-specific internals to public docs/defaults.
- For docs, keep root README as navigation; put workflow details in `docs/tooling.md`, shared behavior in `docs/bot-shared-systems.md`, exact shared data/math in `docs/bot-core-data-structures.md`, and bot-specific behavior in each bot README.

Verification by change type:
- Shared Python math/helper changes: run relevant unit tests, preferably `PYTHONPATH=bots .venv/bin/python -m pytest`.
- Bot behavior changes: run at least a short CLI battle; use A/B runs for performance-sensitive changes.
- Telemetry changes: run a telemetry battle and `tools/telemetry_audit.py`.
- Script changes: run `bash -n` on edited shell scripts and a smoke command when practical.
- Documentation changes: run `git diff --check`; check Markdown fences and local links when links changed.

Performance work should be evidence-driven: use battle results, telemetry, and A/B summaries. Adaptive Prime is intended to be optimized primarily for 1v1 before melee.