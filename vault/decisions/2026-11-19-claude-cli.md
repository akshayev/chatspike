# Decision: Claude through the Claude Code CLI, not the API key (2026-11-19)

**Why:** the user has a Claude plan and no API key. `claude -p` uses that login, so the dashboard agent and the
clipper's Claude tier work without extra billing setup.

**How**
- Dashboard agent: `claude -p --output-format json --tools "" --strict-mcp-config --mcp-config <chatspike>
  --allowedTools mcp__chatspike__* --permission-mode dontAsk --append-system-prompt ... [--resume <session_id>]`.
  No built-in tools, so it cannot run shell commands or read files (incl. `.env`).
- Changes are proposals only (`request_action` → `data/actions.json`); the user confirms (dashboard or
  `run.py --actions`) and `tui/tools.apply_action` applies them.
- Clipper tier: `claude -p --model haiku --tools "" --max-turns 1 --no-session-persistence`, cwd /tmp,
  ANTHROPIC_API_KEY removed from its env so the plan login is used. Still capped by `ai.claude_daily_calls`.
- Flags checked against code.claude.com/docs/en/cli-reference on 2026-11-19.

**Trade-offs:** each call starts a CLI process (a few seconds), and plan usage limits apply instead of per-token
billing. The API path stays available (`ai.claude_backend: "api"`).
