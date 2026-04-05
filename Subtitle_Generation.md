🧾 6. SUBTITLE GENERATION
Use Whisper → get transcript with timestamps
Convert to .srt
Example:
def generate_srt(chunks):
    srt = ""
    for i, chunk in enumerate(chunks):
        srt += f"{i+1}\n"
        srt += f"{chunk['start']} --> {chunk['end']}\n"
        srt += f"{chunk['text']}\n\n"
    return srt
    