"""Clip Detection Engine — 3-layer smart clip selection.

Layer 1 (Context):   LLM summarizes the full video for context-aware decisions
Layer 2 (Structure): LLM segments transcript into meaningful sections (not dumb time-chunks)
Layer 3 (Selection): Hybrid scoring (rule-based + LLM) to pick top viral moments

Extras:
  - Hook rewriting: LLM rewrites the first line of each clip into a viral hook
  - Clip validation: filters out weak/filler clips
  - Fuzzy timestamp alignment: maps LLM segments back to exact timestamps
"""

import json
import logging
import re
from difflib import SequenceMatcher
from typing import List, Dict, Optional

import requests

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# ── Hook keywords (English + Hindi/Hinglish) ──
HOOK_KEYWORDS = [
    # English
    "secret", "truth", "mistake", "stop", "never", "always",
    "don't", "dont", "warning", "shocking", "nobody", "everyone",
    "hack", "trick", "wrong", "biggest", "worst", "best",
    "hidden", "real reason", "actually", "here's the thing",
    "listen", "pay attention", "most people", "99%", "90%",
    # Hindi / Hinglish
    "suno", "dekho", "galti", "sach", "raaz", "shocking",
    "sabse bada", "mat karo", "zaruri", "asli", "important",
    "koi nahi batata", "dhyan do", "samjho", "pata nahi",
    "believe", "amazing", "game changer", "seriously",
    "bhai", "yaar", "dost", "guys",
]

POWER_PHRASES = [
    r"the truth is", r"here'?s what", r"most people don'?t",
    r"nobody tells you", r"the (biggest|worst|best) mistake",
    r"stop doing", r"if you'?re not", r"the real reason",
    r"what I learned", r"changed my life",
    # Hindi / Hinglish
    r"sabse badi galti", r"koi nahi batata", r"asli wajah",
    r"dhyan se suno", r"ye mat karo", r"main ne seekha", r"zindagi badal",
]

# Words that signal filler / weak starts
FILLER_STARTS = ["so", "and", "but", "um", "uh", "like", "basically", "ok so",
                 "as i said", "as i mentioned", "toh", "aur", "haan"]


# ─────────────────────────── Ollama helper ───────────────────────────

def _call_ollama(prompt: str, timeout: int = 120) -> str:
    """Call Ollama and return the response text. Returns empty string on failure."""
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.ConnectionError:
        logger.debug("Ollama unavailable for clip detection")
        return ""
    except requests.RequestException as e:
        logger.warning(f"Ollama call failed: {e}")
        return ""


def _call_ollama_json(prompt: str, timeout: int = 120) -> Optional[list | dict]:
    """Call Ollama expecting JSON output. Returns parsed JSON or None."""
    raw = _call_ollama(prompt, timeout)
    if not raw:
        return None
    # Try to extract JSON from the response (LLM sometimes wraps it in markdown)
    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not json_match:
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    # Try raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.debug(f"Could not parse Ollama JSON: {raw[:200]}")
        return None


# ─────────────── Layer 1: Video Context Summary ──────────────────

def summarize_video(full_text: str) -> Dict:
    """Get a high-level summary of the video for context-aware clip selection."""
    prompt = f"""Summarize this video transcript concisely.

Return JSON:
{{"topic": "main topic in one line", "subtopics": ["subtopic1", "subtopic2", ...]}}

Transcript:
{full_text[:4000]}"""

    result = _call_ollama_json(prompt)
    if result and isinstance(result, dict):
        logger.info(f"Video summary: {result.get('topic', 'unknown')}")
        return result
    return {"topic": "unknown", "subtopics": []}


# ─────────────── Layer 2: Smart Segmentation ──────────────────

def _llm_segment(full_text: str, summary: Dict) -> Optional[List[Dict]]:
    """Use LLM to divide transcript into meaningful segments (not time-based)."""
    topic = summary.get("topic", "")
    prompt = f"""You are a content expert. This video is about: {topic}

Divide this transcript into 5-10 meaningful topic-based segments.
Each segment should be a self-contained idea that could work as a standalone short clip.

Return JSON array:
[
  {{"title": "short title", "summary": "1-line summary", "text": "exact text from transcript"}}
]

Rules:
- Each segment should be 15-60 seconds worth of speech (~40-150 words)
- Pick segments that have strong hooks, opinions, or surprising facts
- DO NOT include introductions, filler, or transitions
- Return ONLY the JSON array, nothing else

Transcript:
{full_text[:6000]}"""

    return _call_ollama_json(prompt, timeout=180)


def _similarity(a: str, b: str) -> float:
    """Fuzzy text similarity ratio."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_best_window(segment_text: str, transcript_chunks: List[Dict],
                      window_sizes: tuple = (3, 4, 5, 2, 6)) -> Optional[Dict]:
    """Fuzzy-match an LLM segment back to transcript chunks to recover timestamps.

    Tries multiple window sizes and returns the best match.
    """
    best_score = 0.0
    best_window = None

    for ws in window_sizes:
        for i in range(len(transcript_chunks) - ws + 1):
            window = transcript_chunks[i:i + ws]
            combined = " ".join(c["text"] for c in window)
            score = _similarity(segment_text, combined)
            if score > best_score:
                best_score = score
                best_window = window

    if best_window and best_score > 0.25:
        return {
            "start": best_window[0]["start"],
            "end": best_window[-1]["end"],
            "text": " ".join(c["text"] for c in best_window),
            "match_score": best_score,
        }
    return None


def smart_segment(full_text: str, chunks: List[Dict],
                  summary: Dict) -> Optional[List[Dict]]:
    """LLM-based segmentation with fuzzy timestamp recovery.

    Returns segments with accurate timestamps, or None if LLM unavailable.
    """
    llm_segments = _llm_segment(full_text, summary)
    if not llm_segments:
        return None

    result = []
    for seg in llm_segments:
        text = seg.get("text", "")
        if not text:
            continue
        match = _find_best_window(text, chunks)
        if match:
            result.append({
                "start": match["start"],
                "end": match["end"],
                "text": match["text"],
                "title": seg.get("title", ""),
                "summary": seg.get("summary", ""),
                "match_score": match["match_score"],
            })

    logger.info(f"LLM segmentation: {len(llm_segments)} segments → {len(result)} matched to timestamps")
    return result if result else None


# ─────────────── Fallback: Time-based Segmentation ──────────────────

def merge_chunks_into_segments(
    chunks: List[Dict],
    min_duration: float = 20.0,
    max_duration: float = 60.0,
) -> List[Dict]:
    """Merge small transcript chunks into 20–60 second segments (fallback)."""
    if not chunks:
        return []

    segments: List[Dict] = []
    current = {
        "start": chunks[0]["start"],
        "end": chunks[0]["end"],
        "text": chunks[0]["text"],
    }

    for chunk in chunks[1:]:
        duration = chunk["end"] - current["start"]
        if duration <= max_duration:
            current["end"] = chunk["end"]
            current["text"] += " " + chunk["text"]
        else:
            if current["end"] - current["start"] >= min_duration:
                segments.append(current)
            current = {
                "start": chunk["start"],
                "end": chunk["end"],
                "text": chunk["text"],
            }

    if current["end"] - current["start"] >= min_duration:
        segments.append(current)

    return segments


# ─────────────── Layer 3: Hybrid Scoring ──────────────────

def rule_score(text: str) -> float:
    """Fast rule-based scoring for viral potential."""
    score = 0.0
    text_lower = text.lower()
    word_count = len(text.split())

    # Hook keywords — +2 each, max 10
    keyword_hits = sum(1 for kw in HOOK_KEYWORDS if kw in text_lower)
    score += min(keyword_hits * 2, 10)

    # Power phrases — +3 each
    for pattern in POWER_PHRASES:
        if re.search(pattern, text_lower):
            score += 3

    # Length sweet spot
    if 20 <= word_count <= 60:
        score += 3
    elif 15 <= word_count <= 80:
        score += 1

    # Emotional punctuation
    score += min(text.count("!"), 3)
    score += min(text.count("?") * 1.5, 3)

    # Questions = engagement
    if "?" in text:
        score += 1

    # Short punchy sentences
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if sentences:
        avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
        if avg_len < 10:
            score += 2

    # Lists / numbered items (e.g. "3 mistakes", "5 tips")
    if re.search(r'\d+\s+(mistakes?|tips?|reasons?|ways?|things?|steps?|secrets?|hacks?)', text_lower):
        score += 3

    # Strong first sentence (first 3 seconds hook)
    first_sentence = sentences[0] if sentences else ""
    first_lower = first_sentence.lower()
    if any(kw in first_lower for kw in HOOK_KEYWORDS[:15]):
        score += 3  # Boost for hook in first sentence

    return score


def llm_score(text: str) -> Optional[Dict]:
    """LLM-based scoring for engagement quality. Returns {"score": float, "title": str}."""
    prompt = f"""You are a viral content expert who creates short-form video clips.

Score this transcript segment from 1 to 10 based on:
- Hook strength (does it grab attention immediately?)
- Engagement (would viewers watch till the end?)
- Standalone clarity (makes sense without context?)
- Emotional impact (opinions, surprises, stories?)

Return ONLY JSON: {{"score": number, "title": "catchy short title"}}

Text:
{text[:1500]}"""

    result = _call_ollama_json(prompt, timeout=60)
    if result and isinstance(result, dict) and "score" in result:
        return {
            "score": float(result["score"]),
            "title": result.get("title", ""),
        }
    return None


def hybrid_score(segments: List[Dict]) -> List[Dict]:
    """Combine rule-based + LLM scoring for each segment."""
    scored = []
    for seg in segments:
        r_score = rule_score(seg["text"])

        # Try LLM scoring
        llm_result = llm_score(seg["text"])
        if llm_result:
            # Weighted: rule (40%) + LLM (60%) — LLM is smarter but rule is reliable
            final_score = (r_score * 0.4) + (llm_result["score"] * 0.6 * 3)  # scale LLM 1-10 → ~3-30
            title = llm_result["title"] or seg.get("title", "")
        else:
            final_score = r_score
            title = seg.get("title", "")

        # Generate title if still empty
        if not title:
            words = seg["text"].split()
            title = " ".join(words[:8]) + ("…" if len(words) > 8 else "")

        scored.append({**seg, "score": final_score, "title": title})

    return scored


# ─────────────── Clip Validation ──────────────────

def is_valid_clip(text: str) -> bool:
    """Filter out weak/filler clips that wouldn't make good content."""
    words = text.split()

    # Too short to be meaningful
    if len(words) < 20:
        return False

    # Starts with filler words → weak opening
    first_words = " ".join(words[:3]).lower().strip()
    for filler in FILLER_STARTS:
        if first_words.startswith(filler):
            return False

    # Mostly filler / repetitive
    unique_words = set(w.lower() for w in words)
    if len(unique_words) < len(words) * 0.3:
        return False

    return True


# ─────────────── Hook Rewriting ──────────────────

def rewrite_hook(text: str) -> str:
    """Use LLM to rewrite the first sentence into a stronger viral hook.

    Returns the full text with the first sentence replaced, or original if LLM fails.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text, maxsplit=1)
    if not sentences:
        return text

    first_sentence = sentences[0]
    rest = sentences[1] if len(sentences) > 1 else ""

    prompt = f"""Rewrite this into a strong viral hook for a short video.

Rules:
- Make it bold and curiosity-driven
- Keep it short (under 15 words)
- Keep the same language (if Hindi, write in Hindi; if English, write in English)
- Do NOT add quotes or explanations — return ONLY the rewritten sentence

Original:
{first_sentence}"""

    rewritten = _call_ollama(prompt, timeout=30)
    if rewritten and len(rewritten) < 200:
        # Clean up: remove quotes, extra whitespace
        rewritten = rewritten.strip('"\'').strip()
        return f"{rewritten} {rest}".strip() if rest else rewritten

    return text


# ─────────────── Main Entry Point ──────────────────

def detect_clips(
    chunks: List[Dict],
    top_n: int = 5,
    min_duration: float = 20.0,
    max_duration: float = 60.0,
    full_text: str = "",
) -> List[Dict]:
    """Main entry: smart clip detection with LLM + rule-based hybrid approach.

    Pipeline:
      1. Summarize video (LLM) → context
      2. Segment into meaningful sections (LLM) → structure
      3. Score each segment (rules + LLM) → selection
      4. Filter weak clips
      5. Rewrite hooks (LLM) → optimization
      6. Return top N

    Falls back to pure rule-based if Ollama is unavailable.

    Returns: [{"start", "end", "text", "score", "title"}, ...]
    """
    if not chunks:
        return []

    if not full_text:
        full_text = " ".join(c["text"] for c in chunks)

    # ── Layer 1: Context (LLM summary) ──
    summary = summarize_video(full_text)

    # ── Layer 2: Structure (LLM segmentation with timestamp recovery) ──
    segments = smart_segment(full_text, chunks, summary)
    if not segments:
        # Fallback: time-based segmentation
        logger.info("LLM segmentation unavailable — using time-based fallback")
        segments = merge_chunks_into_segments(chunks, min_duration, max_duration)

    if not segments:
        return []

    # ── Filter out invalid/filler clips ──
    valid_segments = [s for s in segments if is_valid_clip(s["text"])]
    if not valid_segments:
        valid_segments = segments  # Don't lose all clips to filtering

    # ── Enforce duration limits ──
    for seg in valid_segments:
        duration = seg["end"] - seg["start"]
        if duration > max_duration:
            seg["end"] = seg["start"] + max_duration
        # Add small buffer (1s) for natural feel
        seg["start"] = max(0, seg["start"] - 1.0)
        seg["end"] = seg["end"] + 1.0

    # ── Layer 3: Hybrid scoring ──
    scored = hybrid_score(valid_segments)

    # ── Sort and pick top N ──
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_n]

    # ── Hook rewriting (LLM optimization) ──
    for clip in top:
        original_text = clip["text"]
        rewritten = rewrite_hook(original_text)
        if rewritten != original_text:
            clip["hook_rewritten"] = True
            clip["original_text"] = original_text
            clip["text"] = rewritten
            logger.debug(f"Hook rewritten for: {clip.get('title', '')}")

    logger.info(f"Detected {len(top)} clips (from {len(segments)} segments, {len(valid_segments)} valid)")
    return top
