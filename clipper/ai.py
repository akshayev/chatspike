"""AI router: send each job to the cheapest tier that can do it, log every call.

  tier "local"  Ollama on the laptop GPU (free)     - default for hooks/scores/clustering
  tier "free"   Gemini free tier (GEMINI_API_KEY)   - fallback when RAM is low or local fails
  tier "claude" Anthropic API (ANTHROPIC_API_KEY)   - only jobs that ask for it: borderline
                                                      verdicts, the trend playbook

ask_json(prompt, tiers=[...]) tries the tiers in order and returns (dict, tier) or (None, None).
API shapes checked 2026-11-19: Ollama POST /api/generate {model,prompt,format:"json",stream:false,
options,keep_alive} -> response/prompt_eval_count/eval_count; Gemini v1beta
models/{id}:generateContent; Anthropic /v1/messages.
"""
import json, os, re, time, urllib.request
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


def _claude(prompt, cfg, purpose):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY")
    a = cfg.get("ai", {})
    budget = a.get("claude_daily_calls", 40)
    with db._lock:
        used = db.conn().execute("SELECT COUNT(*) FROM ai_calls WHERE tier='claude' AND ok=1 AND t>?",
                                 (time.time() - 86400,)).fetchone()[0]
    if used >= budget:
        raise RuntimeError(f"Claude daily budget reached ({used}/{budget})")
    model = a.get("claude_model", cfg.get("llm", {}).get("model", "claude-haiku-5-5"))
    t0 = time.time()
    r = _post("https://api.anthropic.com/v1/messages",
              {"model": model, "max_tokens": a.get("claude_max_tokens", 700),
               "messages": [{"role": "user", "content": prompt}]},
              {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=60)
    u = r.get("usage", {})
    _log("claude", model, purpose, t0, u.get("input_tokens", 0), u.get("output_tokens", 0), True)
    return _parse(r["content"][0]["text"])


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
