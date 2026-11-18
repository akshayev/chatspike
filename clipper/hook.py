"""Hook text, YouTube title/description and a virality score for each clip.
Scores the 4 questions: does the opening hook? will people keep watching?
is it worth watching? would someone send it to a friend?
Uses Claude if ANTHROPIC_API_KEY is set, otherwise chat-signal heuristics."""
import json, math, os, random, urllib.request
from .common import log

L = log("hook")

TEMPLATES = {
    "laugh": [
        ("{N} HAD CHAT CRYING IN GTA 6", "{N} Had Chat CRYING In GTA 6 😭"),
        ("{N} CAN'T STOP LAUGHING IN GTA 6", "{N} Couldn't Stop Laughing At This In GTA 6 💀"),
        ("GTA 6 BROKE {N}", "GTA 6 Completely Broke {N} 😂"),
    ],
    "shock": [
        ("{N} DID NOT EXPECT THIS IN GTA 6", "{N} Did NOT Expect This In GTA 6 😳"),
        ("WAIT FOR {N}'S REACTION", "Wait For {N}'s Reaction… GTA 6 😱"),
        ("THIS ACTUALLY HAPPENED TO {N} IN GTA 6", "This Actually Happened To {N} In GTA 6"),
    ],
    "hype": [
        ("{N} JUST DID THE CRAZIEST THING IN GTA 6", "{N} Just Did The CRAZIEST Thing In GTA 6 🔥"),
        ("{N} IS INSANE AT GTA 6", "{N} Is Actually INSANE At GTA 6 🔥"),
        ("CHAT WENT CRAZY FOR {N}", "Chat Went CRAZY For {N} In GTA 6"),
    ],
}


def heuristic_score(ev, words):
    ratio_s = min(35.0, max(0.0, (ev["ratio"] - 2.0) * 6 + 12))
    vol_s = min(25.0, ev["peak_msgs"] / max(1, ev["min_msgs"]) * 8)
    react_s = min(20.0, ev["react_frac"] * 35)
    uniq_s = min(10.0, ev["unique_chatters"] / 8)
    speech_s = 10.0 if len(words) >= 15 else (5.0 if len(words) >= 5 else 0.0)
    return round(ratio_s + vol_s + react_s + uniq_s + speech_s, 1)


def template_meta(ch, ev):
    hook, title = random.choice(TEMPLATES.get(ev["mood"], TEMPLATES["hype"]))
    return hook.format(N=ch["name"].upper()), title.format(N=ch["name"])


def llm_meta(ch, ev, transcript, cfg):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    prompt = f"""You write YouTube Shorts hooks for a GTA 6 streamer-clips channel.
Streamer: {ch['name']}
What the streamer said in the clip: "{transcript[:1500]}"
What chat spammed right after: {ev['top_messages'][:10]}
Chat mood: {ev['mood']}, chat spike {ev['ratio']}x normal.

Return ONLY JSON:
{{"hook": "on-screen text, max 7 words, MUST include '{ch['name']}', no emoji, curiosity-driven, no spoilers of the punchline",
 "title": "YouTube title, max 70 chars, includes '{ch['name']}' and 'GTA 6', 1 emoji max",
 "hook_score": 0-10, "retention_score": 0-10, "value_score": 0-10, "share_score": 0-10,
 "verdict": "one short sentence"}}
Be honest: score low if the transcript shows nothing happens or needs context."""
    body = json.dumps({"model": cfg["llm"]["model"], "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            txt = json.load(r)["content"][0]["text"]
        j = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        if ch["name"].lower() not in j["hook"].lower():
            j["hook"] = f"{ch['name']}: {j['hook']}"
        return j
    except Exception as e:
        L.warning("LLM hook failed (%s), using template", e)
        return None


def make_meta(ch, ev, words, cfg):
    transcript = " ".join(w["w"] for w in words)
    h_score = heuristic_score(ev, words)
    llm = llm_meta(ch, ev, transcript, cfg)
    if llm:
        q = [llm.get(k, 5) for k in ("hook_score", "retention_score", "value_score", "share_score")]
        score = round(0.5 * h_score + 0.5 * (sum(q) / 40 * 100), 1)
        hook, title, verdict = llm["hook"], llm["title"], llm.get("verdict", "")
    else:
        score = h_score
        hook, title = template_meta(ch, ev)
        verdict = "heuristic"
    tags = " ".join(ch["hashtags"])
    title = title[:100 - len(" #GTA6 #shorts") - 1].rstrip()
    desc = f"{title}\n\n{ch['cta']}\n\n{tags}\n"
    title += " #GTA6 #shorts"
    if ch["platform"] == "twitch":
        desc = desc.replace(ch["cta"], f"{ch['cta']}: https://twitch.tv/{ch['source']}")
    return {"hook": hook, "title": title, "description": desc, "score": score,
            "heuristic_score": h_score, "verdict": verdict, "transcript": transcript}
