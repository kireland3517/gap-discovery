"""
SQLite database initialization for Research Pattern Discovery System.

Tables:
- topics: Research topics (e.g., "Website Decision Paralysis")
- keywords: Seed and discovered keywords per topic
- posts: Scraped posts from Reddit/YouTube
- themes: Synthesized pain patterns from Claude
- theme_posts: Mapping between themes and source posts
"""

import hashlib
import re
import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / "research.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Topics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Keywords table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            keyword TEXT NOT NULL,
            is_seed BOOLEAN DEFAULT 1,
            discovery_count INTEGER DEFAULT 0,
            promoted_at TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES topics(id),
            UNIQUE(topic_id, keyword)
        )
    """)

    # Posts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            keyword_id INTEGER,
            source TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            author TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES topics(id),
            FOREIGN KEY (keyword_id) REFERENCES keywords(id)
        )
    """)

    # Themes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            intensity TEXT CHECK(intensity IN ('low', 'medium', 'high')),
            emotional_tone TEXT,
            post_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'new' CHECK(status IN ('new', 'validated', 'archived')),
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)

    # Theme-Posts mapping table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS theme_posts (
            theme_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            relevance_score REAL DEFAULT 1.0,
            PRIMARY KEY (theme_id, post_id),
            FOREIGN KEY (theme_id) REFERENCES themes(id),
            FOREIGN KEY (post_id) REFERENCES posts(id)
        )
    """)

    # Discovered keywords table (not yet promoted to seeds)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            keyword TEXT NOT NULL,
            occurrence_count INTEGER DEFAULT 1,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            promoted BOOLEAN DEFAULT 0,
            FOREIGN KEY (topic_id) REFERENCES topics(id),
            UNIQUE(topic_id, keyword)
        )
    """)

    # Create indexes for common queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_topic ON posts(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_themes_topic ON themes(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_keywords_topic ON keywords(topic_id)")

    # Migration: add status column to themes if missing
    cursor.execute("PRAGMA table_info(themes)")
    columns = [col[1] for col in cursor.fetchall()]
    if "status" not in columns:
        cursor.execute("ALTER TABLE themes ADD COLUMN status TEXT DEFAULT 'new'")

    # Migration: add content_hash column to posts if missing
    cursor.execute("PRAGMA table_info(posts)")
    columns = [col[1] for col in cursor.fetchall()]
    if "content_hash" not in columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN content_hash TEXT")
    if "processed" not in columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN processed INTEGER DEFAULT 0")

    conn.commit()
    conn.close()
    print(f"Database initialized at {DATABASE_PATH}")


def get_or_create_topic(name: str) -> int:
    """Get topic ID by name, or create if doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM topics WHERE name = ?", (name,))
    row = cursor.fetchone()

    if row:
        topic_id = row["id"]
    else:
        cursor.execute("INSERT INTO topics (name) VALUES (?)", (name,))
        topic_id = cursor.lastrowid
        conn.commit()

    conn.close()
    return topic_id


def add_keyword(topic_id: int, keyword: str, is_seed: bool = True) -> int:
    """Add a keyword for a topic."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO keywords (topic_id, keyword, is_seed)
            VALUES (?, ?, ?)
        """, (topic_id, keyword, is_seed))
        keyword_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        # Keyword already exists
        cursor.execute("""
            SELECT id FROM keywords WHERE topic_id = ? AND keyword = ?
        """, (topic_id, keyword))
        keyword_id = cursor.fetchone()["id"]

    conn.close()
    return keyword_id


def normalize_content(text: str) -> str:
    """Normalize text for deduplication: strip whitespace, lowercase, remove boilerplate."""
    if not text:
        return ""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    # Remove common boilerplate phrases
    boilerplate = [
        r'edit:.*$', r'update:.*$', r'tldr:.*$',
        r'thanks in advance', r'thanks for reading',
        r'any help appreciated', r'sorry for.*format'
    ]
    text_lower = text.lower()
    for pattern in boilerplate:
        text_lower = re.sub(pattern, '', text_lower, flags=re.IGNORECASE)
    return text_lower.strip()


def content_hash(title: str, content: str) -> str:
    """Generate hash of normalized content for deduplication."""
    normalized = normalize_content(f"{title} {content}")
    return hashlib.md5(normalized.encode()).hexdigest()


def add_post(topic_id: int, keyword_id: int, source: str, url: str,
             title: str, content: str, author: str = None) -> int | None:
    """Add a scraped post. Returns post ID or None if duplicate (URL or content)."""
    conn = get_connection()
    cursor = conn.cursor()

    # Generate content hash for deduplication
    c_hash = content_hash(title, content)

    # Check for content duplicate first
    cursor.execute(
        "SELECT id FROM posts WHERE content_hash = ? AND topic_id = ?",
        (c_hash, topic_id)
    )
    if cursor.fetchone():
        conn.close()
        return None  # Content duplicate

    try:
        cursor.execute("""
            INSERT INTO posts (topic_id, keyword_id, source, url, title, content, author, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (topic_id, keyword_id, source, url, title, content, author, c_hash))
        post_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        # Post with this URL already exists
        post_id = None

    conn.close()
    return post_id


def get_posts_for_topic(topic_id: int, limit: int = None) -> list:
    """Get all posts for a topic."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM posts WHERE topic_id = ? ORDER BY scraped_at DESC"
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query, (topic_id,))
    posts = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return posts


def populate_seed_keywords(topic_id: int, keywords: list) -> int:
    """Populate all seed keywords for a topic from config. Returns count added."""
    conn = get_connection()
    cursor = conn.cursor()
    added = 0

    for keyword in keywords:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO keywords (topic_id, keyword, is_seed)
                VALUES (?, ?, 1)
            """, (topic_id, keyword))
            if cursor.rowcount > 0:
                added += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    return added


def get_themes_for_topic(topic_id: int) -> list:
    """Get all themes for a topic."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM themes
        WHERE topic_id = ?
        ORDER BY post_count DESC
    """, (topic_id,))
    themes = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return themes


def get_theme_quotes(theme_id: int, limit: int = 5) -> list:
    """Get representative quotes for a theme."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.content, p.source, p.url, tp.relevance_score
        FROM theme_posts tp
        JOIN posts p ON tp.post_id = p.id
        WHERE tp.theme_id = ?
        ORDER BY tp.relevance_score DESC
        LIMIT ?
    """, (theme_id, limit))
    quotes = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return quotes


def update_theme_status(theme_id: int, status: str):
    """Update theme status (new/validated/archived)."""
    if status not in ("new", "validated", "archived"):
        return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE themes SET status = ?, last_updated = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, theme_id))
    conn.commit()
    conn.close()


def update_theme(theme_id: int, name: str, description: str):
    """Update theme name and description."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE themes SET name = ?, description = ?, last_updated = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (name, description, theme_id))
    conn.commit()
    conn.close()


def delete_theme(theme_id: int):
    """Delete a theme and its post associations."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM theme_posts WHERE theme_id = ?", (theme_id,))
    cursor.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
    conn.commit()
    conn.close()


def reset_processed_posts(topic_id: int):
    """Reset all posts for a topic to unprocessed state."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE posts SET processed = 0 WHERE topic_id = ?", (topic_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_database()
