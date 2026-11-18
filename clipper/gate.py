"""Safety gate: decides whether a rendered clip posts automatically, waits for a
human OK on Discord, or is rejected. One Reach strike bans you from every Reach
campaign, so hard rules are strict and anything doubtful goes to review.

  decision = "auto"     every hard check passes, no warnings, score >= auto_score
             "review"   hard checks pass but score in [review_score, auto_score) or a warning
             "rejected" a hard check fails, or score < review_score
"""
import re, time
from . import db

NEGATIVE = re.compile(r"\b(cringe|fell off|trash|racist|homophobic|cancel(?:led)?|drama|beef|exposed|"
                      r"hate (?:him|her|this)|worst streamer|dogwater|ratio)\b", re.I)


def _ascii_ratio(text):
    letters = [c for c in text if c.isalpha()]
    return 1.0 if not letters else sum(c.isascii() for c in letters) / len(letters)


def check(item, ch, cfg):
    g = cfg.get("gate", {})
    auto_score = g.get("auto_score", 70)
    review_score = g.get("review_score", 45)
    min_len, max_len = g.get("min_seconds", 12), g.get("max_seconds", 60)
    hard, soft = [], []

    name = ch["name"].lower()
    hook_text = item.get("hook", "")
    caption = f"{item.get('title', '')}\n{item.get('description', '')}".lower()

    # --- hard checks -------------------------------------------------------
    if name not in hook_text.lower() and name.split()[0] not in hook_text.lower():
        hard.append(f"streamer name '{ch['name']}' missing from on-screen hook")
    for tag in ch.get("required_tags", ch["hashtags"][:1]):
        if tag.lower() not in caption:
            hard.append(f"required hashtag {tag} missing from caption")
    if _ascii_ratio(item.get("title", "") + item.get("hook", "")) < 0.9:
        hard.append("title/hook not in English")
    if _ascii_ratio(item.get("transcript", "")) < 0.8:
        hard.append("speech does not look English")
    dur = item.get("duration") or 0
    if not (min_len <= dur <= max_len):
        hard.append(f"length {dur:.0f}s outside {min_len}-{max_len}s")
    if time.time() - item["created"] > g.get("max_age_minutes", 90) * 60:
        hard.append("older than the posting window")
    spike = (item.get("event") or {}).get("spike_at")
    if spike:
        for other in db.posted_spikes(item["channel"], since=time.time() - 6 * 3600):
            if abs(other - spike) < g.get("dedupe_seconds", 60) and other != spike:
                hard.append("duplicate of a clip already posted for this moment")
                break

    # --- soft warnings -----------------------------------------------------
    words = len(item.get("transcript", "").split())
    if words < 5:
        soft.append(f"only {words} words spoken - may need context")
    chat_lines = " ".join((item.get("event") or {}).get("top_messages", []))
    if NEGATIVE.search(item.get("transcript", "")) or NEGATIVE.search(chat_lines):
        soft.append("negative/drama wording in speech or chat")
    if item.get("needs_context"):
        soft.append("AI reviewer says it needs context")

    score = item.get("score", 0)
    if hard:
        decision = "rejected"
    elif score < review_score:
        decision = "rejected"
        hard.append(f"score {score} below {review_score}")
    elif score >= auto_score and not soft:
        decision = "auto"
    else:
        decision = "review"
    return {"decision": decision, "hard": hard, "soft": soft, "checked_at": time.time()}
