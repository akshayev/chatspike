# 2026-11-18: System design locked

Full doc: https://claude.ai/artifact/UgHic4yzm4ctWdMnPfkX5G

- Hybrid AI: rules, then local Ollama (qwen2.5:3b), then Gemini free tier, then Claude only for judgement and repairs.
- Memory: Context7 MCP, this vault, SQLite, CLAUDE.md.
- At most 2 live recordings, by priority LACY > Clix > Tomo > Bobby. RAM guard at 1.5 GB and 1.0 GB.
- Gate: auto at 70+, review from 45 to 69 (or any warning), reject below 45 or on a hard rule.
- Discord bot for approvals. YouTube now, Instagram next. Terminal app on the Agent SDK in M4.
