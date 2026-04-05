🗄️ 2. DATABASE SCHEMA (keep it minimal)
Users
id (uuid)
email
plan (free/pro)
credits
created_at
Projects (1 video = 1 project)
id (uuid)
user_id
video_url
transcript
duration
status (processing/done)
created_at
Clips
id (uuid)
project_id
start_time
end_time
score
title
video_url
caption_instagram
caption_linkedin
caption_twitter