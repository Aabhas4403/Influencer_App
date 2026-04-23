"""Content Generator — uses Ollama (local LLM) to create platform-specific captions.

Generates:
  - Instagram caption (hook + hashtags)
  - LinkedIn post (insight + storytelling)
  - Twitter thread (3–5 tweets)
  - YouTube Shorts title + description
"""

import json
import logging
import requests
from typing import Dict

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# ── Prompt templates ──────────────────────────────────────────────

INSTAGRAM_PROMPT = """You are a top Instagram Reels copywriter who writes captions
that consistently go viral for creators in coaching, finance, fitness and lifestyle niches.

Write a Reel caption from the transcript below.

NON-NEGOTIABLE RULES:
- Line 1 = a SCROLL-STOPPING hook (curiosity gap, contrarian take, or bold promise). 8 words MAX.
- Line 2 = blank.
- 3-5 short value lines, each on its own line, plain language, no fluff.
- End with a single open-loop question to drive comments.
- Final line = exactly 5 niche-relevant hashtags (mix of broad + specific). No spammy tags.
- Match the language of the transcript (English / Hindi / Hinglish). Do NOT translate.
- Total length: under 130 words.
- Output ONLY the caption. No preamble, no explanation, no quotes.

Transcript:
{clip_text}"""

LINKEDIN_PROMPT = """You are a top LinkedIn ghostwriter who writes for founders and operators.

Turn the transcript into a LinkedIn post that maximises dwell-time + comments.

RULES:
- Line 1 = a pattern-interrupt hook (a number, a contrarian claim, or a confession). 10 words MAX.
- Use short paragraphs (1-2 sentences each), aggressive line breaks, NO emojis.
- Tell the lesson as a mini-story: situation → tension → insight → takeaway.
- End with a thought-provoking 1-line question.
- Match the original language. Do NOT translate.
- Under 180 words.
- Output ONLY the post. No preamble.

Transcript:
{clip_text}"""

TWITTER_PROMPT = """You are a top creator who writes high-engagement X/Twitter threads.

Convert the transcript into a 4-6 tweet thread.

RULES:
- Tweet 1 = the hook tweet. Curiosity gap or bold claim, MUST make people tap "Show more".
  Add 1 line break, then a one-line teaser of what's inside the thread.
- Tweets 2..N-1 = one specific, concrete insight per tweet. Use line breaks for rhythm.
  No filler ("As I said earlier..."). Each tweet must stand alone.
- Last tweet = a single CTA: "Follow @ for more on X" OR "If this hit, retweet the first tweet."
- Each tweet < 270 chars.
- Match the original language.
- Output format:
1/ ...
2/ ...
3/ ...
- Output ONLY the thread. No preamble.

Transcript:
{clip_text}"""

YOUTUBE_PROMPT = """You are a YouTube Shorts strategist optimising for retention + CTR.

From the transcript, generate ONE title and ONE description.

RULES:
- Title: 40-55 chars, includes a number or strong emotion or curiosity gap.
  No clickbait lies — must reflect the clip.
- Description: 2 short sentences summarising the value, plus 3-5 keywords on a new line
  (each prefixed with #).
- End with one CTA line ("Subscribe for daily clips like this.").
- Match the original language.
- Output format exactly:
Title: ...
Description: ...

Transcript:
{clip_text}"""


def _call_ollama(prompt: str) -> str:
    """Call Ollama API and return the generated text."""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except requests.ConnectionError:
        logger.warning("Ollama not running — returning placeholder caption")
        return ""
    except requests.RequestException as e:
        logger.error(f"Ollama call failed: {e}")
        return ""


def generate_instagram_caption(clip_text: str) -> str:
    return _call_ollama(INSTAGRAM_PROMPT.format(clip_text=clip_text))


def generate_linkedin_post(clip_text: str) -> str:
    return _call_ollama(LINKEDIN_PROMPT.format(clip_text=clip_text))


def generate_twitter_thread(clip_text: str) -> str:
    return _call_ollama(TWITTER_PROMPT.format(clip_text=clip_text))


def generate_youtube_content(clip_text: str) -> str:
    return _call_ollama(YOUTUBE_PROMPT.format(clip_text=clip_text))


def _fallback_captions(clip_text: str) -> Dict[str, str]:
    """Generate simple captions from transcript when Ollama is unavailable."""
    words = clip_text.split()
    short = " ".join(words[:25]) + ("..." if len(words) > 25 else "")
    hook = " ".join(words[:10]) + ("..." if len(words) > 10 else "")

    return {
        "instagram": f"🔥 {hook}\n\n{short}\n\n#viral #content #trending #clips #mustwatch",
        "linkedin": f"💡 Key insight from this clip:\n\n\"{short}\"\n\nWhat are your thoughts? Share below 👇",
        "twitter": f"🧵 Thread:\n\n1/ {hook}\n\n2/ {short}\n\n3/ Follow for more content like this!",
        "youtube": f"Title: {hook}\n\nDescription: {short}\n\nLike & subscribe for more!",
    }


def generate_all_captions(clip_text: str) -> Dict[str, str]:
    """Generate captions for all 4 platforms. Falls back to simple captions if Ollama is unavailable."""
    result = {
        "instagram": generate_instagram_caption(clip_text),
        "linkedin": generate_linkedin_post(clip_text),
        "twitter": generate_twitter_thread(clip_text),
        "youtube": generate_youtube_content(clip_text),
    }

    # If all empty (Ollama not running), use fallback
    if all(v == "" for v in result.values()):
        return _fallback_captions(clip_text)

    return result


def generate_all_captions_custom(clip_text: str, custom_prompt: str) -> Dict[str, str]:
    """Generate captions with a user-provided custom prompt applied to each platform."""
    custom_instruction = (
        f"\n\nAdditional user requirements:\n{custom_prompt}\n\n"
        "Apply these requirements while generating the caption."
    )

    result = {
        "instagram": _call_ollama(INSTAGRAM_PROMPT.format(clip_text=clip_text) + custom_instruction),
        "linkedin": _call_ollama(LINKEDIN_PROMPT.format(clip_text=clip_text) + custom_instruction),
        "twitter": _call_ollama(TWITTER_PROMPT.format(clip_text=clip_text) + custom_instruction),
        "youtube": _call_ollama(YOUTUBE_PROMPT.format(clip_text=clip_text) + custom_instruction),
    }

    if all(v == "" for v in result.values()):
        fallback = _fallback_captions(clip_text)
        # Append custom note to fallback
        for k in fallback:
            fallback[k] += f"\n\n[Custom: {custom_prompt[:100]}]"
        return fallback

    return result
