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

INSTAGRAM_PROMPT = """Write a viral Instagram caption from this video transcript.

Rules:
- First line = strong hook (make them stop scrolling)
- Short punchy sentences
- Add 5 relevant hashtags at the end
- Engaging and bold tone
- Max 150 words

Transcript:
{clip_text}

Caption:"""

LINKEDIN_PROMPT = """Turn this video transcript into a LinkedIn post.

Style:
- Start with a relatable hook or bold statement
- Share the insight / lesson
- End with a thought-provoking takeaway or question
- Professional but conversational tone
- Max 200 words

Transcript:
{clip_text}

Post:"""

TWITTER_PROMPT = """Convert this video transcript into a Twitter/X thread of 3-5 tweets.

Style:
- Tweet 1: Hook (make people click "Show more")
- Remaining tweets: value-driven points
- Last tweet: call to action or key takeaway
- Keep each tweet under 280 characters
- Simple language, punchy

Format each tweet as:
1/ ...
2/ ...
3/ ...

Transcript:
{clip_text}

Thread:"""

YOUTUBE_PROMPT = """Generate a YouTube Shorts title and description from this transcript.

Rules:
- Title: catchy, under 60 characters, retention-optimized
- Description: 2-3 sentences summarizing the clip + relevant keywords
- Include a call to action

Format:
Title: ...
Description: ...

Transcript:
{clip_text}

Output:"""


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
