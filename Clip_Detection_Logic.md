🧠 4. CLIP DETECTION LOGIC (core differentiator)

Start SIMPLE — don’t overcomplicate.

Python Example:
import re

def score_chunk(text):
    score = 0
    
    # Hook words
    hooks = ["secret", "truth", "mistake", "don’t", "stop", "never"]
    for word in hooks:
        if word in text.lower():
            score += 2
    
    # Shorter is better
    if len(text.split()) < 40:
        score += 1
    
    # Emotional punctuation
    if "!" in text:
        score += 1
    
    return score


def get_top_clips(transcript_chunks):
    scored = []
    
    for chunk in transcript_chunks:
        score = score_chunk(chunk["text"])
        scored.append({**chunk, "score": score})
    
    return sorted(scored, key=lambda x: x["score"], reverse=True)[:5]

👉 Later you can upgrade to ML, but this works for MVP.