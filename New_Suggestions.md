🧠 How to Select “Best Clips That Make Sense”

Think of it as a 3-layer system:

🧩 1. Understand the FULL VIDEO (Context Layer)
4
Goal:

Understand:

What is this video about?
What topics are discussed?
🔧 Implementation
Take full transcript
Send to LLM (Ollama)

Prompt:

Summarize this video in:
1. Main topic
2. Key subtopics (bullet points)

Transcript:
{full_transcript}

👉 Output:

Topic: “Startup growth mistakes”
Subtopics:
Hiring mistakes
Marketing errors
Funding myths

👉 Why this matters:
Now your clips are context-aware, not random

🧩 2. Segment Video into Meaningful Sections (Structure Layer)
Goal:

Break video into logical segments, not time chunks

🔧 Method 1 (Simple & effective)

Split transcript into:

30–60 sec chunks

Then group similar chunks by meaning

🔧 Method 2 (Better — still simple)

Use LLM:

Divide this transcript into meaningful segments.

For each segment provide:
- Title
- Start idea
- End idea
- Summary

Transcript:
{transcript}

👉 Output:

Segment 1: “Why most startups fail early”
Segment 2: “Biggest hiring mistake”
Segment 3: “Growth hacks that don’t work”

👉 Now you have:
Topic-based segmentation (THIS IS GOLD)

🧩 3. Score Each Segment for “Clip Worthiness” (Selection Layer)
4

Now filter segments using multi-factor scoring

🧠 Scoring Criteria (practical)
1. Hook Strength (MOST IMPORTANT)

Does it start strong?

Examples:

“Most people get this WRONG…”
“This is the biggest mistake…”
2. Standalone Value

Can this clip make sense alone?

👉 If user watches only this → still valuable?

3. Emotional / Opinionated
Strong opinions
Surprising facts
Contrarian takes
4. Length
Ideal: 15–45 sec
5. Clarity
No dependency on previous context
🔧 LLM-based Scoring (very effective)

Use Ollama:

You are a viral content expert.

Score this transcript (1–10) based on:
- Hook strength
- Engagement
- Standalone clarity

Also suggest a title.

Transcript:
{segment_text}

👉 Output:

Score: 8.5
Title: “Why Most Startups Fail in Year 1”
🧠 FINAL PIPELINE (THIS IS YOUR SECRET SAUCE)
1. Transcribe video
2. Get full video summary (context)
3. Segment into meaningful sections
4. Score each segment
5. Pick top 3–5 clips
6. Cut + generate content
⚡ Practical Python Flow
Step 1: Chunk transcript
chunks = split_into_chunks(transcript, duration=40)
Step 2: Group / label segments
segments = call_llm_for_segmentation(chunks)
Step 3: Score segments
for seg in segments:
    seg["score"] = score_with_llm(seg["text"])
Step 4: Pick best
top_clips = sorted(segments, key=lambda x: x["score"], reverse=True)[:5]
🔥 Pro Tricks (high impact)
1. Boost first 3 seconds

If first line is weak → discard

2. Remove filler segments

Avoid:

“So basically…”
“As I said earlier…”
3. Prefer:
Lists (“3 mistakes…”)
Strong claims
Personal stories
4. Add “Hook Rewriting” (BIG WIN)

Even if clip is good → rewrite first line:

Rewrite this into a strong hook:
{first_sentence}

👉 This alone increases performance

⚠️ Biggest Mistake to Avoid

Don’t:

Only use timestamps
Only use keywords

👉 That gives garbage clips

🧠 Reality Check

You don’t need:

Perfect NLP
Complex ML

👉 LLM + simple logic = enough to beat competitors



Perfect — let’s turn this into **actual working Python logic you can plug into your app**.

I’ll give you:

1. ✅ Full pipeline functions
2. ✅ Ollama integration
3. ✅ Clip scoring + ranking
4. ✅ Clean, usable structure

---

# 🚀 1. FULL PIPELINE (COPY THIS STRUCTURE)

```python
# pipeline.py

from services.transcription import transcribe_video
from services.segmentation import segment_transcript
from services.scoring import score_segments
from services.selector import select_top_clips


def process_video(video_path):
    transcript = transcribe_video(video_path)

    segments = segment_transcript(transcript)

    scored_segments = score_segments(segments)

    top_clips = select_top_clips(scored_segments)

    return top_clips
```

---

# 🧠 2. TRANSCRIPT SEGMENTATION (SMART VERSION)

👉 Uses LLM to create **meaningful segments (not dumb chunks)**

```python
# services/segmentation.py

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"


def segment_transcript(transcript):
    prompt = f"""
Divide this transcript into meaningful segments.

For each segment return:
- title
- summary
- start_text (first line)
- full_text

Transcript:
{transcript}
"""

    response = requests.post(OLLAMA_URL, json={
        "model": "llama3",
        "prompt": prompt,
        "stream": False
    })

    result = response.json()["response"]

    # ⚠️ You will need to parse this into structured JSON
    # (you can enforce JSON in prompt later)

    return parse_segments(result)
```

---

# ⚡ PRO TIP (IMPORTANT)

Improve output reliability:

```text
Return output in JSON format like:
[
  {
    "title": "...",
    "summary": "...",
    "text": "..."
  }
]
```

👉 This avoids messy parsing

---

# 🎯 3. SCORING ENGINE (HYBRID = BEST)

👉 Combine:

* Rule-based (fast)
* LLM-based (smart)

---

## Step 1: Rule-based scoring

```python
# services/scoring.py

def rule_score(text):
    score = 0

    hooks = ["secret", "mistake", "truth", "never", "stop", "don’t"]

    for word in hooks:
        if word in text.lower():
            score += 2

    if len(text.split()) < 80:
        score += 1

    if "?" in text or "!" in text:
        score += 1

    return score
```

---

## Step 2: LLM scoring

```python
import requests

def llm_score(text):
    prompt = f"""
You are a viral content expert.

Score this from 1–10 based on:
- Hook strength
- Engagement
- Standalone clarity

Also return a short title.

Text:
{text}

Return JSON:
{{"score": number, "title": "..."}}
"""

    response = requests.post("http://localhost:11434/api/generate", json={
        "model": "llama3",
        "prompt": prompt,
        "stream": False
    })

    return response.json()["response"]
```

---

## Step 3: Combine scores

```python
def score_segments(segments):
    scored = []

    for seg in segments:
        r_score = rule_score(seg["text"])

        llm_result = llm_score(seg["text"])
        llm_data = parse_json(llm_result)

        final_score = r_score + llm_data["score"]

        scored.append({
            **seg,
            "score": final_score,
            "title": llm_data["title"]
        })

    return scored
```

---

# 🏆 4. SELECT BEST CLIPS

```python
# services/selector.py

def select_top_clips(segments, n=5):
    sorted_segments = sorted(
        segments,
        key=lambda x: x["score"],
        reverse=True
    )

    return sorted_segments[:n]
```

---

# 🔥 5. HOOK OPTIMIZATION (GAME CHANGER)

👉 Even average clip becomes viral with better hook

```python
def rewrite_hook(text):
    prompt = f"""
Rewrite the first sentence into a strong viral hook.

Rules:
- Make it bold
- Make it curiosity-driven
- Keep it short

Text:
{text}
"""

    response = requests.post("http://localhost:11434/api/generate", json={
        "model": "llama3",
        "prompt": prompt,
        "stream": False
    })

    return response.json()["response"]
```

---

# 🧪 6. OPTIONAL (VERY POWERFUL)

## Filter bad clips

```python
def is_valid_clip(text):
    if len(text.split()) < 20:
        return False

    if text.lower().startswith(("so", "and", "but")):
        return False

    return True
```

---

# ⚡ FINAL FLOW (HOW IT RUNS)

```python
video → transcript  
→ segmentation (LLM)  
→ scoring (rules + LLM)  
→ ranking  
→ top clips  
→ hook rewrite  
→ final output
```

---

# 🔥 WHAT MAKES THIS STRONG

You are:

* NOT cutting randomly ❌
* NOT relying only on AI ❌

👉 You’re combining:

* Structure + context + scoring

This is **exactly how real products win**

---

# ⚠️ Practical Tips

* Cache LLM responses (saves time)
* Limit segments (10–20 max)
* Start with 3 clips only

---








🚀 GOAL

You want:

Transcript (with timestamps)
   ↓
Segment (text)
   ↓
Find exact start & end time
   ↓
Cut video using FFmpeg
🧠 1. WHAT YOU NEED FROM TRANSCRIPTION

Make sure your transcription gives word-level OR chunk-level timestamps

Using faster-whisper, you’ll get:

segments = [
    {
        "start": 0.0,
        "end": 4.2,
        "text": "Most startups fail because..."
    },
    {
        "start": 4.2,
        "end": 9.8,
        "text": "they don't understand their customer..."
    }
]

👉 This is your source of truth

🧩 2. MATCH LLM SEGMENTS BACK TO TIMESTAMPS

Problem:
LLM gives you:

Clean segment text
But NO timestamps ❌

👉 Solution:
Fuzzy match LLM segment → transcript chunks

✅ Implementation
from difflib import SequenceMatcher

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def find_timestamp(segment_text, transcript_segments):
    best_match = None
    best_score = 0

    for seg in transcript_segments:
        score = similarity(segment_text.lower(), seg["text"].lower())

        if score > best_score:
            best_score = score
            best_match = seg

    return best_match
🔥 Improve (multi-line match)

Instead of matching 1 chunk → match GROUP

def find_best_window(segment_text, transcript_segments, window_size=3):
    best_score = 0
    best_window = None

    for i in range(len(transcript_segments) - window_size):
        combined_text = " ".join(
            [transcript_segments[j]["text"] for j in range(i, i+window_size)]
        )

        score = similarity(segment_text.lower(), combined_text.lower())

        if score > best_score:
            best_score = score
            best_window = transcript_segments[i:i+window_size]

    if best_window:
        return {
            "start": best_window[0]["start"],
            "end": best_window[-1]["end"]
        }

    return None

👉 This works MUCH better

🎯 3. BUILD FINAL CLIP OBJECT
def map_segments_to_timestamps(llm_segments, transcript_segments):
    clips = []

    for seg in llm_segments:
        match = find_best_window(seg["text"], transcript_segments)

        if match:
            clips.append({
                "title": seg["title"],
                "text": seg["text"],
                "start": match["start"],
                "end": match["end"]
            })

    return clips
✂️ 4. CUT VIDEO WITH FFMPEG
import subprocess

def cut_clip(input_file, start, end, output_file):
    cmd = [
        "ffmpeg",
        "-i", input_file,
        "-ss", str(start),
        "-to", str(end),
        "-c", "copy",
        output_file
    ]

    subprocess.run(cmd)
🔥 5. MAKE IT VERTICAL + SUBTITLES (FINAL STEP)
def process_clip(input_file, start, end, output_file):
    cmd = f"""
    ffmpeg -i {input_file} -ss {start} -to {end} \
    -vf "crop=ih*9/16:ih,scale=1080:1920" \
    -c:a copy {output_file}
    """
    subprocess.run(cmd, shell=True)
🧠 6. ADD BUFFER (VERY IMPORTANT)

Clips feel abrupt otherwise

def add_buffer(start, end, buffer=1.5):
    start = max(0, start - buffer)
    end = end + buffer
    return start, end
⚡ FINAL PIPELINE (WITH TIMESTAMPS)
1. Transcribe video → transcript_segments (with timestamps)

2. LLM segmentation → meaningful segments

3. Match segments → timestamps (fuzzy window match)

4. Add buffer

5. Cut video (FFmpeg)

6. Generate captions
🧪 EXAMPLE OUTPUT
[
  {
    "title": "Why startups fail",
    "start": 12.5,
    "end": 38.2,
    "text": "Most startups fail because..."
  }
]
⚠️ COMMON ISSUES (and fixes)
❌ Mismatch text

👉 Fix:

Use window matching (not single line)
❌ Wrong clip boundaries

👉 Fix:

Add buffer
Increase window size
❌ Too long clips

👉 Fix:

if end - start > 60:
    end = start + 60
🔥 PRO UPGRADE (later)

Instead of fuzzy matching:

Store embeddings
Use semantic search

But:
👉 Not needed for MVP

💡 FINAL INSIGHT

This part (timestamp alignment) is:

Where most tools fail
Where your product becomes “magic”









You asked for next step → I’ll give you 3 high-impact upgrades that make your clips feel like Reels/TikTok quality, not raw cuts:

🚀 1. BURN SUBTITLES (word-by-word, reel style)
4
🧠 Goal
Big bold subtitles
Highlight words
Center placement

👉 THIS alone increases engagement massively

🧩 Step 1: Generate word-level timestamps

Using faster-whisper

segments, info = model.transcribe("input.mp4", word_timestamps=True)
🧩 Step 2: Convert to styled SRT
def generate_srt(segments):
    srt = ""
    index = 1

    for seg in segments:
        for word in seg.words:
            start = word.start
            end = word.end
            text = word.word.upper()

            srt += f"{index}\n"
            srt += f"{format_time(start)} --> {format_time(end)}\n"
            srt += f"{text}\n\n"

            index += 1

    return srt
🧩 Step 3: Burn subtitles with style
ffmpeg -i input.mp4 -vf "subtitles=subs.srt:force_style='Fontsize=24,PrimaryColour=&Hffffff&,OutlineColour=&H000000&,BorderStyle=3'" output.mp4

👉 You can tweak:

Fontsize
Color
Outline
🚀 2. AUTO ZOOM (makes video feel dynamic)
4
🧠 Goal

Avoid static boring frame

🧩 Simple Zoom Trick (no AI needed)
ffmpeg -i input.mp4 -vf "zoompan=z='min(zoom+0.0015,1.2)':d=125" output.mp4

👉 Creates slow zoom-in effect

🧩 Better: Alternate zoom per clip

In Python:

zoom_type = random.choice(["in", "out"])

if zoom_type == "in":
    vf = "zoompan=z='min(zoom+0.0015,1.2)'"
else:
    vf = "zoompan=z='if(lte(zoom,1.0),1.2,max(zoom-0.0015,1.0))'"
🚀 3. AUTO CENTER FACE (pro-level feel)
4
🧠 Goal

Always keep speaker in center when converting to vertical

🧩 Basic OpenCV Face Detection
import cv2

def detect_face(frame):
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)

    return faces
🧩 Crop around face
def crop_to_face(frame, face):
    x, y, w, h = face
    center_x = x + w // 2

    # Crop vertical frame (9:16)
    crop_width = int(frame.shape[0] * 9 / 16)

    start_x = max(0, center_x - crop_width // 2)
    end_x = start_x + crop_width

    return frame[:, start_x:end_x]

👉 Combine this into video pipeline
👉 This makes clips feel premium

⚡ FINAL ENHANCED PIPELINE
1. Transcribe (with word timestamps)
2. Segment + score clips
3. Map timestamps
4. Cut video
5. Face center crop (OpenCV)
6. Apply zoom (FFmpeg)
7. Generate subtitles (word-level)
8. Burn subtitles
9. Export final clip
💥 What you now have

With these 3 upgrades:

Subtitles → engagement ↑
Zoom → retention ↑
Face crop → quality ↑

👉 This is what separates:
❌ basic tool
vs
✅ product people PAY for

⚠️ Keep it practical

Don’t build all at once.

👉 Order:

Subtitles (must have)
Clip selection
Zoom
Face tracking (later)








import os
import subprocess
from faster_whisper import WhisperModel

# ---------- CONFIG ----------
VIDEO_PATH = "input.mp4"
OUTPUT_CLIP = "clip.mp4"
FINAL_OUTPUT = "final_reel.mp4"

# ---------- STEP 1: TRANSCRIBE ----------
model = WhisperModel("base", compute_type="int8")

segments, _ = model.transcribe(VIDEO_PATH, word_timestamps=True)

transcript_segments = []
full_text = ""

for seg in segments:
    transcript_segments.append({
        "start": seg.start,
        "end": seg.end,
        "text": seg.text
    })
    full_text += seg.text + " "

# ---------- STEP 2: SIMPLE SCORING ----------
def score_text(text):
    score = 0
    hooks = ["secret", "mistake", "truth", "never", "stop", "don’t"]

    for word in hooks:
        if word in text.lower():
            score += 2

    if len(text.split()) < 60:
        score += 1

    return score

best_seg = max(transcript_segments, key=lambda x: score_text(x["text"]))

start = max(0, best_seg["start"] - 1)
end = best_seg["end"] + 1

# limit clip length
if end - start > 45:
    end = start + 45

# ---------- STEP 3: CUT VIDEO ----------
subprocess.run([
    "ffmpeg", "-i", VIDEO_PATH,
    "-ss", str(start),
    "-to", str(end),
    "-c", "copy",
    OUTPUT_CLIP
])

# ---------- STEP 4: GENERATE SRT ----------
def format_time(t):
    hrs = int(t // 3600)
    mins = int((t % 3600) // 60)
    secs = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{hrs:02}:{mins:02}:{secs:02},{ms:03}"

srt_content = ""
index = 1

for seg in transcript_segments:
    if seg["start"] >= start and seg["end"] <= end:
        srt_content += f"{index}\n"
        srt_content += f"{format_time(seg['start']-start)} --> {format_time(seg['end']-start)}\n"
        srt_content += f"{seg['text'].strip()}\n\n"
        index += 1

with open("subs.srt", "w") as f:
    f.write(srt_content)

# ---------- STEP 5: FINAL VIDEO ----------
subprocess.run(f"""
ffmpeg -i {OUTPUT_CLIP} \
-vf "crop=ih*9/16:ih,scale=1080:1920,subtitles=subs.srt:force_style='Fontsize=28,PrimaryColour=&Hffffff&,OutlineColour=&H000000&,BorderStyle=3'" \
-c:a copy {FINAL_OUTPUT}
""", shell=True)

print("✅ Final reel generated:", FINAL_OUTPUT)