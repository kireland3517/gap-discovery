"""
SQLite database initialization for Pain-Point Intelligence System.

Core Tables:
- topics: Research topics (e.g., "Website Decision Paralysis")
- keywords: Seed and discovered keywords per topic
- posts: Scraped posts from Reddit/YouTube
- themes: Synthesized pain patterns from Claude (legacy)
- theme_posts: Mapping between themes and source posts (legacy)

Pain Intelligence Tables:
- pain_evidence: Raw verbatim quotes with four-question classification
- pain_clusters: Grouped pain patterns (only when 3+ evidence)
- pain_cluster_evidence: Junction table linking clusters to evidence
- failed_solutions: Tools/approaches that have failed

Scraper Tables:
- search_signals: Google autocomplete and PAA data
- tool_reviews: G2/Capterra reviews
- job_signals: Job descriptions with manual task detection
"""

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

DATABASE_PATH = Path(__file__).parent / "research.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled.

    Uses timeout=30 to wait for locks during concurrent access.
    """
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Enable WAL mode for better concurrent access
    # WAL allows readers and writers to proceed concurrently
    cursor.execute("PRAGMA journal_mode=WAL")

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

    # ============================================
    # PAIN INTELLIGENCE TABLES
    # ============================================

    # Pain Evidence table - raw verbatim quotes with four-question classification
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pain_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            post_id INTEGER,

            -- Core evidence (VERBATIM, never summarized)
            verbatim_quote TEXT NOT NULL,

            -- Four Questions Classification
            manual_task TEXT,           -- Q1: What manual task causes frustration?
            cost_impact TEXT,           -- Q2: What does it cost (time/money/errors)?
            failed_solutions TEXT,      -- Q3: What have they tried that failed?
            ideal_state TEXT,           -- Q4: What would "better" look like?

            -- Hybrid AI/Human workflow flags
            task_ai_suggested BOOLEAN DEFAULT 0,
            task_user_confirmed BOOLEAN DEFAULT 0,
            cost_ai_suggested BOOLEAN DEFAULT 0,
            cost_user_confirmed BOOLEAN DEFAULT 0,
            tried_ai_suggested BOOLEAN DEFAULT 0,
            tried_user_confirmed BOOLEAN DEFAULT 0,
            better_ai_suggested BOOLEAN DEFAULT 0,
            better_user_confirmed BOOLEAN DEFAULT 0,

            -- Human-Centered Lens Tags (JSON array)
            human_lens_tags TEXT DEFAULT '[]',

            -- Metadata
            source TEXT NOT NULL,
            source_url TEXT,
            industry TEXT,
            emotion TEXT CHECK(emotion IN ('frustrated', 'overwhelmed', 'anxious', 'resigned', NULL)),
            intensity TEXT CHECK(intensity IN ('low', 'medium', 'high', NULL)),
            ai_confidence REAL DEFAULT 0.0,
            flagged_for_removal BOOLEAN DEFAULT 0,

            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TIMESTAMP,

            FOREIGN KEY (topic_id) REFERENCES topics(id),
            FOREIGN KEY (post_id) REFERENCES posts(id)
        )
    """)

    # Pain Clusters table - grouped patterns (only created when 3+ evidence)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pain_clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,

            -- Cluster-specific fields
            repeated_manual_tasks TEXT,     -- JSON array of task descriptions
            trigger_moment TEXT,            -- growth, busy season, new hire, etc.
            current_workaround TEXT,
            consequence_of_failure TEXT,

            -- Aggregated metadata
            evidence_count INTEGER DEFAULT 0,
            primary_question TEXT,          -- Which of 4 questions this primarily answers
            dominant_emotion TEXT,
            dominant_lens TEXT,
            industries TEXT,                -- JSON array of industries affected

            -- Status
            intensity TEXT CHECK(intensity IN ('low', 'medium', 'high', 'critical')),
            status TEXT DEFAULT 'auto' CHECK(status IN ('auto', 'confirmed', 'merged', 'archived')),

            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)

    # Junction table: Pain Cluster to Evidence (many-to-many)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pain_cluster_evidence (
            cluster_id INTEGER NOT NULL,
            evidence_id INTEGER NOT NULL,
            relevance_score REAL DEFAULT 1.0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (cluster_id, evidence_id),
            FOREIGN KEY (cluster_id) REFERENCES pain_clusters(id) ON DELETE CASCADE,
            FOREIGN KEY (evidence_id) REFERENCES pain_evidence(id) ON DELETE CASCADE
        )
    """)

    # Failed Solutions table - tools/approaches that have failed
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS failed_solutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            tool_tried TEXT NOT NULL,
            tool_category TEXT,             -- automation, spreadsheet, manual_process, software
            why_failed TEXT,
            what_broke_first TEXT,
            human_behavior_involved TEXT,

            -- Links
            evidence_id INTEGER,
            cluster_id INTEGER,

            -- Frequency tracking
            reported_count INTEGER DEFAULT 1,
            evidence_ids TEXT,              -- JSON array of pain_evidence IDs mentioning this

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (topic_id) REFERENCES topics(id),
            FOREIGN KEY (evidence_id) REFERENCES pain_evidence(id),
            FOREIGN KEY (cluster_id) REFERENCES pain_clusters(id)
        )
    """)

    # ============================================
    # SCRAPER DATA TABLES
    # ============================================

    # Search Signals table - Google autocomplete, PAA
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            signal_type TEXT NOT NULL CHECK(signal_type IN ('autocomplete', 'paa', 'related_search')),
            query_text TEXT NOT NULL,
            seed_query TEXT,
            position INTEGER,
            answer_preview TEXT,            -- For PAA: the snippet answer
            source_url TEXT,
            content_hash TEXT UNIQUE,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)

    # Tool Reviews table - G2, Capterra, community forums
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            platform TEXT NOT NULL,         -- g2, capterra, zapier_community, etc.
            star_rating INTEGER,
            reviewer_role TEXT,
            industry TEXT,
            pros_text TEXT,
            cons_text TEXT,                 -- Primary focus for pain extraction
            full_review TEXT,
            url TEXT UNIQUE,
            content_hash TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)

    # Job Signals table - job descriptions with manual task detection
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            job_title TEXT NOT NULL,
            company TEXT,
            platform TEXT NOT NULL,         -- linkedin, indeed
            location TEXT,
            description TEXT,
            manual_tasks_detected TEXT,     -- JSON array of detected manual tasks
            tools_mentioned TEXT,           -- JSON array of tools mentioned
            pain_language TEXT,             -- JSON array of pain phrases found
            url TEXT UNIQUE,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)

    # ============================================
    # INDEXES
    # ============================================

    # Original indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_topic ON posts(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_themes_topic ON themes(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_keywords_topic ON keywords(topic_id)")

    # Pain Evidence indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_evidence_topic ON pain_evidence(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_evidence_source ON pain_evidence(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_evidence_industry ON pain_evidence(industry)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_evidence_emotion ON pain_evidence(emotion)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_evidence_flagged ON pain_evidence(flagged_for_removal)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_evidence_confirmed ON pain_evidence(task_user_confirmed)")

    # Pain Clusters indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_clusters_topic ON pain_clusters(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pain_clusters_status ON pain_clusters(status)")

    # Junction table indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pce_cluster ON pain_cluster_evidence(cluster_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pce_evidence ON pain_cluster_evidence(evidence_id)")

    # Failed Solutions indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_failed_solutions_topic ON failed_solutions(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_failed_solutions_tool ON failed_solutions(tool_tried)")

    # Scraper table indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_signals_topic ON search_signals(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_reviews_topic ON tool_reviews(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_reviews_tool ON tool_reviews(tool_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_signals_topic ON job_signals(topic_id)")

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
    if "complaint_score" not in columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN complaint_score REAL DEFAULT NULL")

    # Migration: add confidence_score column to themes if missing
    cursor.execute("PRAGMA table_info(themes)")
    theme_columns = [col[1] for col in cursor.fetchall()]
    if "confidence_score" not in theme_columns:
        cursor.execute("ALTER TABLE themes ADD COLUMN confidence_score REAL DEFAULT NULL")

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
             title: str, content: str, author: str = None,
             complaint_score: float = None) -> int | None:
    """Add a scraped post. Returns post ID or None if duplicate (URL or content)."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Generate content hash for deduplication
        c_hash = content_hash(title, content)

        # Check for content duplicate first
        cursor.execute(
            "SELECT id FROM posts WHERE content_hash = ? AND topic_id = ?",
            (c_hash, topic_id)
        )
        if cursor.fetchone():
            return None  # Content duplicate

        cursor.execute("""
            INSERT INTO posts (topic_id, keyword_id, source, url, title, content, author, content_hash, complaint_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (topic_id, keyword_id, source, url, title, content, author, c_hash, complaint_score))
        post_id = cursor.lastrowid
        conn.commit()
        return post_id
    except sqlite3.IntegrityError:
        # Post with this URL already exists
        return None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    """Delete a theme and its post associations.

    Both DELETEs are atomic - either both succeed or neither does.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM theme_posts WHERE theme_id = ?", (theme_id,))
        cursor.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_processed_posts(topic_id: int):
    """Reset all posts for a topic to unprocessed state."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE posts SET processed = 0 WHERE topic_id = ?", (topic_id,))
    conn.commit()
    conn.close()


# ============================================
# PAIN EVIDENCE FUNCTIONS
# ============================================

def add_pain_evidence(
    topic_id: int,
    verbatim_quote: str,
    source: str,
    post_id: Optional[int] = None,
    source_url: Optional[str] = None,
    manual_task: Optional[str] = None,
    cost_impact: Optional[str] = None,
    failed_solutions: Optional[str] = None,
    ideal_state: Optional[str] = None,
    human_lens_tags: Optional[list] = None,
    industry: Optional[str] = None,
    emotion: Optional[str] = None,
    intensity: Optional[str] = None,
    ai_confidence: float = 0.0,
    flagged_for_removal: bool = False
) -> int:
    """Add a pain evidence entry. Returns the evidence ID."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Set AI suggested flags based on which fields are populated
        task_ai_suggested = 1 if manual_task else 0
        cost_ai_suggested = 1 if cost_impact else 0
        tried_ai_suggested = 1 if failed_solutions else 0
        better_ai_suggested = 1 if ideal_state else 0

        cursor.execute("""
            INSERT INTO pain_evidence (
                topic_id, post_id, verbatim_quote, source, source_url,
                manual_task, cost_impact, failed_solutions, ideal_state,
                task_ai_suggested, cost_ai_suggested, tried_ai_suggested, better_ai_suggested,
                human_lens_tags, industry, emotion, intensity,
                ai_confidence, flagged_for_removal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            topic_id, post_id, verbatim_quote, source, source_url,
            manual_task, cost_impact, failed_solutions, ideal_state,
            task_ai_suggested, cost_ai_suggested, tried_ai_suggested, better_ai_suggested,
            json.dumps(human_lens_tags or []), industry, emotion, intensity,
            ai_confidence, 1 if flagged_for_removal else 0
        ))

        evidence_id = cursor.lastrowid
        conn.commit()
        return evidence_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pain_evidence_for_topic(
    topic_id: int,
    confirmed_only: bool = False,
    include_flagged: bool = False,
    source_filter: Optional[str] = None,
    industry_filter: Optional[str] = None,
    emotion_filter: Optional[str] = None,
    question_filter: Optional[str] = None,
    limit: Optional[int] = None
) -> list:
    """Get pain evidence for a topic with optional filters."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM pain_evidence WHERE topic_id = ?"
    params = [topic_id]

    if confirmed_only:
        query += " AND task_user_confirmed = 1"

    if not include_flagged:
        query += " AND flagged_for_removal = 0"

    if source_filter:
        query += " AND source = ?"
        params.append(source_filter)

    if industry_filter:
        query += " AND industry = ?"
        params.append(industry_filter)

    if emotion_filter:
        query += " AND emotion = ?"
        params.append(emotion_filter)

    if question_filter:
        if question_filter == "manual_task":
            query += " AND manual_task IS NOT NULL AND manual_task != ''"
        elif question_filter == "cost_impact":
            query += " AND cost_impact IS NOT NULL AND cost_impact != ''"
        elif question_filter == "failed_solutions":
            query += " AND failed_solutions IS NOT NULL AND failed_solutions != ''"
        elif question_filter == "ideal_state":
            query += " AND ideal_state IS NOT NULL AND ideal_state != ''"
        elif question_filter == "flagged":
            query += " AND flagged_for_removal = 1"

    query += " ORDER BY created_at DESC"

    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query, params)
    evidence = [dict(row) for row in cursor.fetchall()]

    # Parse JSON fields
    for e in evidence:
        try:
            e['human_lens_tags'] = json.loads(e.get('human_lens_tags', '[]'))
        except (json.JSONDecodeError, TypeError):
            e['human_lens_tags'] = []

    conn.close()
    return evidence


def get_unconfirmed_evidence(topic_id: int, limit: int = 50) -> list:
    """Get evidence that needs human confirmation."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM pain_evidence
        WHERE topic_id = ?
          AND task_user_confirmed = 0
          AND flagged_for_removal = 0
        ORDER BY ai_confidence DESC, created_at DESC
        LIMIT ?
    """, (topic_id, limit))

    evidence = [dict(row) for row in cursor.fetchall()]
    for e in evidence:
        try:
            e['human_lens_tags'] = json.loads(e.get('human_lens_tags', '[]'))
        except (json.JSONDecodeError, TypeError):
            e['human_lens_tags'] = []

    conn.close()
    return evidence


def confirm_evidence(
    evidence_id: int,
    manual_task: Optional[str] = None,
    cost_impact: Optional[str] = None,
    failed_solutions: Optional[str] = None,
    ideal_state: Optional[str] = None,
    human_lens_tags: Optional[list] = None,
    industry: Optional[str] = None
):
    """Confirm and optionally update pain evidence classification."""
    conn = get_connection()
    cursor = conn.cursor()

    updates = ["task_user_confirmed = 1", "confirmed_at = CURRENT_TIMESTAMP"]
    params = []

    if manual_task is not None:
        updates.append("manual_task = ?")
        params.append(manual_task)
    if cost_impact is not None:
        updates.append("cost_impact = ?")
        params.append(cost_impact)
    if failed_solutions is not None:
        updates.append("failed_solutions = ?")
        params.append(failed_solutions)
    if ideal_state is not None:
        updates.append("ideal_state = ?")
        params.append(ideal_state)
    if human_lens_tags is not None:
        updates.append("human_lens_tags = ?")
        params.append(json.dumps(human_lens_tags))
    if industry is not None:
        updates.append("industry = ?")
        params.append(industry)

    params.append(evidence_id)

    cursor.execute(f"""
        UPDATE pain_evidence SET {', '.join(updates)} WHERE id = ?
    """, params)

    conn.commit()
    conn.close()


def flag_evidence_for_removal(evidence_id: int):
    """Flag evidence for removal (doesn't answer any of the four questions)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE pain_evidence SET flagged_for_removal = 1 WHERE id = ?
    """, (evidence_id,))
    conn.commit()
    conn.close()


def delete_flagged_evidence(topic_id: int) -> int:
    """Delete all flagged evidence for a topic. Returns count deleted."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM pain_evidence WHERE topic_id = ? AND flagged_for_removal = 1
    """, (topic_id,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


# ============================================
# PAIN CLUSTER FUNCTIONS
# ============================================

def add_pain_cluster(
    topic_id: int,
    name: str,
    description: Optional[str] = None,
    repeated_manual_tasks: Optional[list] = None,
    trigger_moment: Optional[str] = None,
    current_workaround: Optional[str] = None,
    consequence_of_failure: Optional[str] = None,
    primary_question: Optional[str] = None,
    dominant_emotion: Optional[str] = None,
    dominant_lens: Optional[str] = None,
    industries: Optional[list] = None,
    intensity: Optional[str] = None
) -> int:
    """Add a pain cluster. Returns the cluster ID."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO pain_clusters (
                topic_id, name, description,
                repeated_manual_tasks, trigger_moment, current_workaround, consequence_of_failure,
                primary_question, dominant_emotion, dominant_lens, industries, intensity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            topic_id, name, description,
            json.dumps(repeated_manual_tasks or []), trigger_moment, current_workaround, consequence_of_failure,
            primary_question, dominant_emotion, dominant_lens, json.dumps(industries or []), intensity
        ))

        cluster_id = cursor.lastrowid
        conn.commit()
        return cluster_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def link_evidence_to_cluster(cluster_id: int, evidence_id: int, relevance_score: float = 1.0):
    """Link a pain evidence entry to a cluster.

    Uses explicit transaction handling to ensure INSERT and UPDATE are atomic.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO pain_cluster_evidence (cluster_id, evidence_id, relevance_score)
            VALUES (?, ?, ?)
        """, (cluster_id, evidence_id, relevance_score))

        # Update evidence count on cluster (atomic with INSERT)
        cursor.execute("""
            UPDATE pain_clusters
            SET evidence_count = (SELECT COUNT(*) FROM pain_cluster_evidence WHERE cluster_id = ?),
                last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (cluster_id, cluster_id))

        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()  # Link already exists - rollback partial transaction
    except Exception:
        conn.rollback()  # Rollback on any error
        raise
    finally:
        conn.close()


def get_pain_clusters_for_topic(topic_id: int, min_evidence: int = 3, include_archived: bool = False) -> list:
    """Get pain clusters for a topic (default: only those with 3+ evidence)."""
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT * FROM pain_clusters
        WHERE topic_id = ? AND evidence_count >= ?
    """
    params = [topic_id, min_evidence]

    if not include_archived:
        query += " AND status != 'archived'"

    query += " ORDER BY evidence_count DESC"

    cursor.execute(query, params)
    clusters = [dict(row) for row in cursor.fetchall()]

    # Parse JSON fields
    for c in clusters:
        try:
            c['repeated_manual_tasks'] = json.loads(c.get('repeated_manual_tasks', '[]'))
            c['industries'] = json.loads(c.get('industries', '[]'))
        except (json.JSONDecodeError, TypeError):
            c['repeated_manual_tasks'] = []
            c['industries'] = []

    conn.close()
    return clusters


def get_cluster_evidence(cluster_id: int) -> list:
    """Get all evidence entries linked to a cluster."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pe.*, pce.relevance_score
        FROM pain_evidence pe
        JOIN pain_cluster_evidence pce ON pe.id = pce.evidence_id
        WHERE pce.cluster_id = ?
        ORDER BY pce.relevance_score DESC
    """, (cluster_id,))

    evidence = [dict(row) for row in cursor.fetchall()]
    for e in evidence:
        try:
            e['human_lens_tags'] = json.loads(e.get('human_lens_tags', '[]'))
        except (json.JSONDecodeError, TypeError):
            e['human_lens_tags'] = []

    conn.close()
    return evidence


def update_cluster_status(cluster_id: int, status: str):
    """Update cluster status (auto/confirmed/merged/archived)."""
    if status not in ("auto", "confirmed", "merged", "archived"):
        return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE pain_clusters SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?
    """, (status, cluster_id))
    conn.commit()
    conn.close()


# ============================================
# FAILED SOLUTIONS FUNCTIONS
# ============================================

def add_failed_solution(
    topic_id: int,
    tool_tried: str,
    tool_category: Optional[str] = None,
    why_failed: Optional[str] = None,
    what_broke_first: Optional[str] = None,
    human_behavior_involved: Optional[str] = None,
    evidence_id: Optional[int] = None,
    cluster_id: Optional[int] = None
) -> int:
    """Add a failed solution entry. Returns the solution ID.

    Uses atomic upsert pattern - SELECT and UPDATE/INSERT in same transaction.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Check if this tool already exists for this topic
        cursor.execute("""
            SELECT id, reported_count, evidence_ids FROM failed_solutions
            WHERE topic_id = ? AND tool_tried = ?
        """, (topic_id, tool_tried))
        existing = cursor.fetchone()

        if existing:
            # Update existing entry
            solution_id = existing['id']
            new_count = existing['reported_count'] + 1
            existing_ids = json.loads(existing['evidence_ids'] or '[]')
            if evidence_id and evidence_id not in existing_ids:
                existing_ids.append(evidence_id)

            cursor.execute("""
                UPDATE failed_solutions
                SET reported_count = ?, evidence_ids = ?, why_failed = COALESCE(?, why_failed)
                WHERE id = ?
            """, (new_count, json.dumps(existing_ids), why_failed, solution_id))
        else:
            # Insert new entry
            cursor.execute("""
                INSERT INTO failed_solutions (
                    topic_id, tool_tried, tool_category, why_failed, what_broke_first,
                    human_behavior_involved, evidence_id, cluster_id, evidence_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                topic_id, tool_tried, tool_category, why_failed, what_broke_first,
                human_behavior_involved, evidence_id, cluster_id,
                json.dumps([evidence_id] if evidence_id else [])
            ))
            solution_id = cursor.lastrowid

        conn.commit()
        return solution_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_failed_solutions_for_topic(topic_id: int, min_reports: int = 1) -> list:
    """Get failed solutions for a topic, ordered by frequency."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM failed_solutions
        WHERE topic_id = ? AND reported_count >= ?
        ORDER BY reported_count DESC
    """, (topic_id, min_reports))

    solutions = [dict(row) for row in cursor.fetchall()]
    for s in solutions:
        try:
            s['evidence_ids'] = json.loads(s.get('evidence_ids', '[]'))
        except (json.JSONDecodeError, TypeError):
            s['evidence_ids'] = []

    conn.close()
    return solutions


# ============================================
# SCRAPER DATA FUNCTIONS
# ============================================

def add_search_signal(
    topic_id: int,
    signal_type: str,
    query_text: str,
    seed_query: Optional[str] = None,
    position: Optional[int] = None,
    answer_preview: Optional[str] = None,
    source_url: Optional[str] = None
) -> Optional[int]:
    """Add a search signal (autocomplete, PAA). Returns ID or None if duplicate."""
    conn = get_connection()
    cursor = conn.cursor()

    # Generate content hash for deduplication
    c_hash = hashlib.md5(f"{signal_type}:{query_text}".encode()).hexdigest()

    try:
        cursor.execute("""
            INSERT INTO search_signals (
                topic_id, signal_type, query_text, seed_query, position,
                answer_preview, source_url, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (topic_id, signal_type, query_text, seed_query, position, answer_preview, source_url, c_hash))
        signal_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        signal_id = None

    conn.close()
    return signal_id


def add_tool_review(
    topic_id: int,
    tool_name: str,
    platform: str,
    url: str,
    star_rating: Optional[int] = None,
    reviewer_role: Optional[str] = None,
    industry: Optional[str] = None,
    pros_text: Optional[str] = None,
    cons_text: Optional[str] = None,
    full_review: Optional[str] = None
) -> Optional[int]:
    """Add a tool review. Returns ID or None if duplicate."""
    conn = get_connection()
    cursor = conn.cursor()

    # Generate content hash
    c_hash = hashlib.md5(f"{tool_name}:{cons_text or full_review or ''}".encode()).hexdigest()

    try:
        cursor.execute("""
            INSERT INTO tool_reviews (
                topic_id, tool_name, platform, star_rating, reviewer_role, industry,
                pros_text, cons_text, full_review, url, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (topic_id, tool_name, platform, star_rating, reviewer_role, industry,
              pros_text, cons_text, full_review, url, c_hash))
        review_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        review_id = None

    conn.close()
    return review_id


def add_job_signal(
    topic_id: int,
    job_title: str,
    platform: str,
    url: str,
    company: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    manual_tasks_detected: Optional[list] = None,
    tools_mentioned: Optional[list] = None,
    pain_language: Optional[list] = None
) -> Optional[int]:
    """Add a job signal. Returns ID or None if duplicate."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO job_signals (
                topic_id, job_title, company, platform, location, description,
                manual_tasks_detected, tools_mentioned, pain_language, url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            topic_id, job_title, company, platform, location, description,
            json.dumps(manual_tasks_detected or []),
            json.dumps(tools_mentioned or []),
            json.dumps(pain_language or []),
            url
        ))
        signal_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        signal_id = None

    conn.close()
    return signal_id


def get_search_signals_for_topic(topic_id: int, signal_type: Optional[str] = None) -> list:
    """Get search signals for a topic."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM search_signals WHERE topic_id = ?"
    params = [topic_id]

    if signal_type:
        query += " AND signal_type = ?"
        params.append(signal_type)

    query += " ORDER BY scraped_at DESC"

    cursor.execute(query, params)
    signals = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return signals


def get_tool_reviews_for_topic(topic_id: int, tool_name: Optional[str] = None, max_stars: int = 5) -> list:
    """Get tool reviews for a topic."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM tool_reviews WHERE topic_id = ? AND (star_rating IS NULL OR star_rating <= ?)"
    params = [topic_id, max_stars]

    if tool_name:
        query += " AND tool_name = ?"
        params.append(tool_name)

    query += " ORDER BY star_rating ASC, scraped_at DESC"

    cursor.execute(query, params)
    reviews = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return reviews


def get_job_signals_for_topic(topic_id: int) -> list:
    """Get job signals for a topic."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM job_signals WHERE topic_id = ? ORDER BY scraped_at DESC
    """, (topic_id,))

    signals = [dict(row) for row in cursor.fetchall()]
    for s in signals:
        try:
            s['manual_tasks_detected'] = json.loads(s.get('manual_tasks_detected', '[]'))
            s['tools_mentioned'] = json.loads(s.get('tools_mentioned', '[]'))
            s['pain_language'] = json.loads(s.get('pain_language', '[]'))
        except (json.JSONDecodeError, TypeError):
            s['manual_tasks_detected'] = []
            s['tools_mentioned'] = []
            s['pain_language'] = []

    conn.close()
    return signals


# ============================================
# STATISTICS FUNCTIONS
# ============================================

def get_pain_intelligence_stats(topic_id: int) -> dict:
    """Get statistics for the pain intelligence system."""
    conn = get_connection()
    cursor = conn.cursor()

    # Evidence counts
    cursor.execute("""
        SELECT
            COUNT(*) as total_evidence,
            SUM(CASE WHEN task_user_confirmed = 1 THEN 1 ELSE 0 END) as confirmed_evidence,
            SUM(CASE WHEN flagged_for_removal = 1 THEN 1 ELSE 0 END) as flagged_evidence,
            SUM(CASE WHEN manual_task IS NOT NULL AND manual_task != '' THEN 1 ELSE 0 END) as has_task,
            SUM(CASE WHEN cost_impact IS NOT NULL AND cost_impact != '' THEN 1 ELSE 0 END) as has_cost,
            SUM(CASE WHEN failed_solutions IS NOT NULL AND failed_solutions != '' THEN 1 ELSE 0 END) as has_tried,
            SUM(CASE WHEN ideal_state IS NOT NULL AND ideal_state != '' THEN 1 ELSE 0 END) as has_better
        FROM pain_evidence WHERE topic_id = ?
    """, (topic_id,))
    evidence_stats = dict(cursor.fetchone())

    # Cluster counts
    cursor.execute("""
        SELECT
            COUNT(*) as total_clusters,
            SUM(CASE WHEN evidence_count >= 3 THEN 1 ELSE 0 END) as valid_clusters
        FROM pain_clusters WHERE topic_id = ?
    """, (topic_id,))
    cluster_stats = dict(cursor.fetchone())

    # Failed solutions count
    cursor.execute("""
        SELECT COUNT(DISTINCT tool_tried) as unique_failed_tools,
               SUM(reported_count) as total_failure_reports
        FROM failed_solutions WHERE topic_id = ?
    """, (topic_id,))
    solution_stats = dict(cursor.fetchone())

    # Scraper data counts
    cursor.execute("SELECT COUNT(*) as count FROM search_signals WHERE topic_id = ?", (topic_id,))
    search_count = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM tool_reviews WHERE topic_id = ?", (topic_id,))
    review_count = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM job_signals WHERE topic_id = ?", (topic_id,))
    job_count = cursor.fetchone()['count']

    conn.close()

    return {
        'evidence': evidence_stats,
        'clusters': cluster_stats,
        'failed_solutions': solution_stats,
        'scraped_data': {
            'search_signals': search_count,
            'tool_reviews': review_count,
            'job_signals': job_count
        }
    }


if __name__ == "__main__":
    init_database()
