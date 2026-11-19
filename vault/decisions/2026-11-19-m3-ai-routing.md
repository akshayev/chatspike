# 2026-11-19: M3 AI routing

- Hooks, titles and the 4-question score (hook, retention, value, share) come from the local model (qwen2.5:3b via Ollama), with Gemini free tier (`gemini-3.5-flash-lite`) as fallback. No Claude tokens per clip.
- Final score = 50% chat signals + 50% AI 4-question average.
- Claude is used only for: (1) a second opinion on borderline clips (score 45-69 or a gate warning), shown next to the Discord buttons (the user still decides); (2) the trend playbook every 3 h. Daily cap: `ai.claude_daily_calls` (40).
- Trend sources without keys: YouTube autocomplete, Reddit r/GTA6 hot. Optional: pytrends (Google Trends), Twitch Helix (needs TWITCH_CLIENT_ID/SECRET).
- API shapes were checked against current docs on 2026-11-19 (Ollama /api/generate; Gemini v1beta generateContent; free-tier model ids from AI Studio listings).
