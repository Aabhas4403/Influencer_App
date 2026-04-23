🎬 5. FFMPEG COMMANDS (THIS IS GOLD)
Convert horizontal → vertical + crop
ffmpeg -i input.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" output.mp4
Add subtitles (basic)
ffmpeg -i input.mp4 -vf subtitles=subs.srt output.mp4
Cut clip
ffmpeg -i input.mp4 -ss 00:01:20 -to 00:01:50 -c copy clip.mp4
Combine all
ffmpeg -i input.mp4 \
-ss 00:01:20 -to 00:01:50 \
-vf "crop=ih*9/16:ih,scale=1080:1920,subtitles=subs.srt" \
clip_final.mp4

👉 This is your core pipeline