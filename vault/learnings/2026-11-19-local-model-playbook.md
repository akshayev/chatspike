# 2026-11-19: The local 3B model can't be trusted to write the playbook alone

The first two qwen2.5:3b playbooks included invented names ("Mandy"), off-topic angles (trailer, pre-order, PS5 update, voice actors) and unsafe ones ("Sex in GTA6", "Lucia kiss", "sex scenes if appropriate").

Fix: the playbook is grounded. Hot terms come from counting real YouTube autocomplete suggestions and Google Trends rising queries. The model can only re-rank them, and its own terms survive only if they appear in the data. Unsafe and off-topic words are blocked. Hooks must be `{N}` templates, never invented events.

Takeaway: use the local model to judge and rephrase given material, never to supply facts. A Claude-written playbook (ANTHROPIC_API_KEY) is expected to be much better, but it still goes through the same filters.
