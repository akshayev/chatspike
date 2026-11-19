"""AI router: send each job to the cheapest tier that can do it, log every call.

  tier "local"  Ollama on the laptop GPU (free)     - default for hooks/scores/clustering
  tier "free"   Gemini free tier (GEMINI_API_KEY)   - fallback when RAM is low or local fails
  tier "claude" Claude Code CLI (`claude -p`, your Claude login; no API key needed)
                                                    - only jobs that ask for it: borderline verdicts,
                                                      the trend playbook. ai.claude_backend "api" +
                                                      ANTHROPIC_API_KEY uses the API instead.

ask_json(prompt, tiers=[...]) tries the tiers in order and returns (dict, tier) or (None, None).
API shapes checked 2026-11-19: Ollama POST /api/generate {model,prompt,format:"json",stream:false,
options,keep_alive} -> response/prompt_eval_count/eval_count; Gemini v1beta
models/{id}:generateContent; Anthropic /v1/messages.
"""
import json, os, re, shutil, subprocess, time, urllib.request
from .common import log, load_config
from . import db, sysinfo

L = log("ai")


def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _parse(text):
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _log(tier, model, purpose, t0, tin, tout, ok):
    try:
        with db._lock:
            c = db.conn()
            c.execute("INSERT INTO ai_calls(t, tier, model, purpose, tokens_in, tokens_out, ms, ok) VALUES(?,?,?,?,?,?,?,?)",
                      (time.time(), tier, model, purpose, tin, tout, int((time.time() - t0) * 1000), int(ok)))
            c.commit()
    except Exception:
        pass


def _local(prompt, cfg, purpose):
    a = cfg.get("ai", {})
    if sysinfo.mem_available_gb() < a.get("local_min_ram_gb", 1.0):
        raise RuntimeError("RAM too low for local model")
    model = a.get("local_model", "qwen2.5:3b")
    t0 = time.time()
    r = _post(a.get("ollama_url", "http://127.0.0.1:11434") + "/api/generate",
              {"model": model, "prompt": prompt, "format": "json", "stream": False,
               "options": {"temperature": a.get("temperature", 0.6)}, "keep_alive": a.get("keep_alive", "2m")},
              {}, timeout=a.get("local_timeout", 90))
    _log("local", model, purpose, t0, r.get("prompt_eval_count", 0), r.get("eval_count", 0), True)
    return _parse(r["response"])


def _free(prompt, cfg, purpose):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY")
    model = cfg.get("ai", {}).get("gemini_model", "gemini-3.5-flash-lite")
    t0 = time.time()
    r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
              {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6}},
              {"x-goog-api-key": key}, timeout=60)
    u = r.get("usageMetadata", {})
    _log("free", model, purpose, t0, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), True)
    return _parse(r["candidates"][0]["content"]["parts"][0]["text"])


def claude_bin():
    """The claude CLI, also when ~/.local/bin is not on PATH (e.g. started from a desktop launcher)."""
    p = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    return p if os.path.exists(p) else None


def cli_env():
    """Env for the claude CLI without ANTHROPIC_API_KEY, so it uses the user's Claude login (plan), not the key."""
    return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


def _claude_cli(prompt, a):
    """Claude Code CLI with the user's Claude login: no tools, one turn, not saved as a session."""
    exe = claude_bin()
    if not exe:
        raise RuntimeError("no ANTHROPIC_API_KEY and no claude CLI")
    model = a.get("claude_cli_model", "haiku")
    r = subprocess.run([exe, "-p", prompt + "\n\nReply with JSON only.", "--output-format", "json", "--model", model,
                        "--tools", "", "--strict-mcp-config", "--max-turns", "1", "--no-session-persistence",
                        # replace Claude Code's big default system prompt (~47k tokens) with a tiny one
                        "--system-prompt", "You are a careful JSON-only assistant. Reply with one JSON object."],
                       capture_output=True, text=True, timeout=a.get("claude_cli_timeout", 120), cwd="/tmp",
                       env=cli_env())
    try:
        j = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude CLI failed: {(r.stderr or r.stdout)[-200:]}")
    if j.get("is_error"):
        raise RuntimeError(f"claude CLI: {str(j.get('result') or j.get('subtype'))[:200]}")
    u = j.get("usage", {})
    tin = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    return j.get("result", ""), "cli:" + model, tin, u.get("output_tokens", 0)


def _claude(prompt, cfg, purpose):
    a = cfg.get("ai", {})
    budget = a.get("claude_daily_calls", 40)
    with db._lock:
        used = db.conn().execute("SELECT COUNT(*) FROM ai_calls WHERE tier='claude' AND ok=1 AND t>?",
                                 (time.time() - 86400,)).fetchone()[0]
    if used >= budget:
        raise RuntimeError(f"Claude daily budget reached ({used}/{budget})")
    t0 = time.time()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key and a.get("claude_backend", "cli") == "api":
        model = a.get("claude_model", "claude-haiku-5-5")
        r = _post("https://api.anthropic.com/v1/messages",
                  {"model": model, "max_tokens": a.get("claude_max_tokens", 700),
                   "messages": [{"role": "user", "content": prompt}]},
                  {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=60)
        u = r.get("usage", {})
        text, tin, tout = r["content"][0]["text"], u.get("input_tokens", 0), u.get("output_tokens", 0)
    else:
        text, model, tin, tout = _claude_cli(prompt, a)
    out = _parse(text)
    _log("claude", model, purpose, t0, tin, tout, True)
    return out


TIERS = {"local": _local, "free": _free, "claude": _claude}


def ask_json(prompt, purpose, tiers=("local", "free"), cfg=None):
    cfg = cfg or load_config()
    for t in tiers:
        t0 = time.time()
        try:
            return TIERS[t](prompt, cfg, purpose), t
        except Exception as e:
            _log(t, "-", purpose, t0, 0, 0, False)
            L.info("ai %s/%s unavailable: %s", purpose, t, str(e)[:160])
    return None, None


def usage(hours=24):
    with db._lock:
        rows = db.conn().execute("SELECT tier, COUNT(*), SUM(ok), SUM(tokens_in), SUM(tokens_out) FROM ai_calls "
                                 "WHERE t>? GROUP BY tier", (time.time() - hours * 3600,)).fetchall()
    return {r[0]: {"calls": r[1], "ok": r[2], "tokens_in": r[3] or 0, "tokens_out": r[4] or 0} for r in rows}
