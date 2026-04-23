"""One-time migration script to add new columns and tables."""
import sqlite3
import sys

DB_PATH = "/Users/karnawat.a/Influencer_App/backend/clipflow.db"

MIGRATIONS = [
    "ALTER TABLE projects ADD COLUMN progress_pct INTEGER DEFAULT 0",
    "ALTER TABLE projects ADD COLUMN progress_stage VARCHAR(100) DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN progress_detail VARCHAR(255) DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN eta_seconds INTEGER",
    "ALTER TABLE projects ADD COLUMN video_hash VARCHAR(64)",
    "ALTER TABLE projects ADD COLUMN language VARCHAR(20)",
    "ALTER TABLE clips ADD COLUMN clip_index INTEGER DEFAULT 0",
    "ALTER TABLE clips ADD COLUMN active_version INTEGER DEFAULT 1",
    """CREATE TABLE IF NOT EXISTS clip_versions (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        clip_id VARCHAR(36) NOT NULL,
        version_num INTEGER DEFAULT 1,
        video_path TEXT,
        srt_path TEXT,
        caption_instagram TEXT,
        caption_linkedin TEXT,
        caption_twitter TEXT,
        caption_youtube TEXT,
        custom_prompt TEXT,
        created_at DATETIME,
        FOREIGN KEY(clip_id) REFERENCES clips(id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_projects_video_hash ON projects(video_hash)",
    "ALTER TABLE projects ADD COLUMN manual_selections TEXT",
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for sql in MIGRATIONS:
        try:
            cur.execute(sql)
            print(f"OK: {sql[:60]}...")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"SKIP (exists): {sql[:60]}...")
            else:
                print(f"ERROR: {e} -- {sql[:60]}...")
    conn.commit()
    conn.close()
    print("\nMigration complete!")

if __name__ == "__main__":
    main()
