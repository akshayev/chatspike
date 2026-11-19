# 2026-11-19: M4 terminal app

- `./tui.sh` runs a Textual dashboard as a separate process. The clipper keeps running when it is closed.
- Tabs: Live (channels, capture health, RAM/VRAM/disk, playbook), Review (a = approve, r = reject, p = play), Posted (YouTube/Instagram/Content Rewards status and views), Agent (Claude chat).
- The agent uses the Claude Agent SDK with in-process MCP tools only: get_status, list_clips, clip_detail, approve_clip, reject_clip, set_title, pause_channel, resume_channel, campaign_stats, ai_usage, read_vault, tail_log. Bash/Write/Edit/Web tools are disallowed. Every state change shows a Yes/No dialog. read_vault is confined to vault/ (no access to .env).
- Coupling: the clipper writes logs/status.json every 10 s; pauses go through data/control.json and the scheduler applies them each minute.
- Requires ANTHROPIC_API_KEY for the Agent tab (API billing). The other tabs work without it.
- SDK API was checked on 2026-11-19 (pip claude-agent-sdk; @tool + create_sdk_mcp_server; allowed_tools mcp__<server>__<tool>; ClaudeSDKClient).
