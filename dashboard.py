"""
Pain-Point Intelligence Dashboard.

Three-View Architecture:
- View 1: Raw Pain Evidence with confirmation UI
- View 2: Pain Clusters (3+ evidence)
- View 3: Failed Solutions Analysis

Legacy Features (still supported):
- Theme cards view
- Charts: top themes, timeline, intensity distribution
"""

import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import plotly.express as px
import streamlit as st
import yaml

import database
import synthesize

# Human-centered lens options
HUMAN_LENS_OPTIONS = [
    "trust_issue",
    "cognitive_load",
    "change_resistance",
    "error_sensitivity",
    "emotional_stakes"
]

LENS_LABELS = {
    "trust_issue": "Trust Issue",
    "cognitive_load": "Cognitive Load",
    "change_resistance": "Change Resistance",
    "error_sensitivity": "Error Sensitivity",
    "emotional_stakes": "Emotional Stakes"
}

INDUSTRY_OPTIONS = [
    "freelance", "agency", "ecommerce", "saas", "consulting",
    "healthcare", "real_estate", "enterprise", "other"
]

EMOTION_OPTIONS = ["frustrated", "overwhelmed", "anxious", "resigned"]

# Progress tracking database (separate from main DB to avoid blocking)
PROGRESS_DB = Path(__file__).parent / ".job_progress.db"


def _init_progress_db():
    """Initialize the progress tracking database."""
    conn = sqlite3.connect(PROGRESS_DB, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_progress (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            job_type TEXT,
            status TEXT,
            step TEXT,
            percentage REAL DEFAULT 0,
            timestamp TEXT,
            error TEXT
        )
    """)
    conn.commit()
    conn.close()


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def write_progress(job_type: str, status: str, step: str, percentage: float = 0, error: str = None):
    """Write progress to database for cross-thread communication (thread-safe)."""
    _init_progress_db()
    data = {
        "job_type": job_type,
        "status": status,
        "step": step,
        "percentage": percentage,
        "timestamp": datetime.now().isoformat(),
        "error": error
    }
    try:
        conn = sqlite3.connect(PROGRESS_DB, timeout=30)
        conn.execute("DELETE FROM job_progress")
        conn.execute("""
            INSERT INTO job_progress (id, job_type, status, step, percentage, timestamp, error)
            VALUES (1, ?, ?, ?, ?, ?, ?)
        """, (data["job_type"], data["status"], data["step"],
              data["percentage"], data["timestamp"], data["error"]))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"Progress write error: {e}")


def read_progress() -> dict | None:
    """Read progress from database. Returns None if no progress."""
    if not PROGRESS_DB.exists():
        return None
    try:
        conn = sqlite3.connect(PROGRESS_DB, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM job_progress WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None
    except sqlite3.Error:
        return None


def clear_progress():
    """Clear progress from database."""
    if PROGRESS_DB.exists():
        try:
            conn = sqlite3.connect(PROGRESS_DB, timeout=30)
            conn.execute("DELETE FROM job_progress")
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass


def run_scraper_background(topic_name: str, platforms: list):
    """Run scraper in background thread with progress updates."""
    try:
        write_progress("scrape", "running", f"Starting scrape for {topic_name}", 0)

        # Run scraper as subprocess
        platforms_arg = ",".join(platforms)
        result = subprocess.run(
            [sys.executable, "scrape.py", "--topic", topic_name, "--platforms", platforms_arg],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent),
            check=False
        )

        if result.returncode == 0:
            write_progress("scrape", "completed", "Scraping complete!", 100)
        else:
            write_progress("scrape", "failed", "Scrape failed", 0, error=result.stderr[:500])

    except Exception as e:
        write_progress("scrape", "failed", "Scrape error", 0, error=str(e))


def run_synthesis_background(topic_name: str, mode: str = "pain"):
    """Run synthesis in background thread with progress updates."""
    try:
        write_progress("synthesize", "running", f"Analyzing posts for {topic_name}", 10)

        if mode == "pain":
            # Run pain intelligence synthesis
            stats = synthesize.run_pain_intelligence_synthesis(topic_name, process_all=True)

            # Reset processed flag
            topic_id = database.get_or_create_topic(topic_name)
            database.reset_processed_posts(topic_id)

            evidence_saved = stats.get("evidence_saved", 0)
            clusters_created = stats.get("clusters_created", 0)
            write_progress(
                "synthesize", "completed",
                f"Saved {evidence_saved} evidence, {clusters_created} clusters!",
                100
            )
        else:
            # Legacy synthesis
            stats = synthesize.run_synthesis(topic_name, process_all=True)

            # Reset processed flag
            topic_id = database.get_or_create_topic(topic_name)
            database.reset_processed_posts(topic_id)

            themes_created = stats.get("themes_created", 0)
            write_progress("synthesize", "completed", f"Created {themes_created} themes!", 100)

    except Exception as e:
        write_progress("synthesize", "failed", "Synthesis error", 0, error=str(e))


def start_background_job(job_type: str, target_func, args: tuple):
    """Start a background job and track it in session state."""
    clear_progress()
    thread = threading.Thread(target=target_func, args=args, daemon=True)
    thread.start()
    st.session_state.background_job = {
        "type": job_type,
        "thread": thread,
        "started_at": datetime.now().isoformat()
    }


def render_progress_indicator():
    """Render progress indicator if a job is running."""
    progress = read_progress()
    if not progress:
        return False

    status = progress.get("status", "")

    if status == "running":
        job_type = progress.get("job_type", "job").capitalize()
        step = progress.get("step", "Processing...")

        st.info(f"**{job_type} in progress:** {step}")
        st.progress(progress.get("percentage", 0) / 100)
        return True

    elif status == "completed":
        step = progress.get("step", "Complete!")
        st.success(step)
        # Auto-clear after displaying
        if st.button("Dismiss", key="dismiss_success"):
            clear_progress()
            st.rerun()
        return False

    elif status == "failed":
        error = progress.get("error", "Unknown error")
        st.error(f"Job failed: {error}")
        if st.button("Dismiss", key="dismiss_error"):
            clear_progress()
            st.rerun()
        return False

    return False


def get_topic_names(config: dict) -> list:
    """Get list of topic names from config."""
    return [topic["name"] for topic in config.get("topics", [])]


def get_topic_keywords(config: dict, topic_name: str) -> list:
    """Get keywords for a specific topic from config."""
    for topic in config.get("topics", []):
        if topic["name"] == topic_name:
            return topic.get("keywords", [])
    return []


def get_topic_stats(topic_id: int) -> dict:
    """Get statistics for a topic."""
    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM posts WHERE topic_id = ?", (topic_id,))
    post_count = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) as count FROM themes WHERE topic_id = ?", (topic_id,))
    theme_count = cursor.fetchone()["count"]

    cursor.execute(
        "SELECT COUNT(*) as count FROM keywords WHERE topic_id = ? AND is_seed = 1",
        (topic_id,)
    )
    keyword_count = cursor.fetchone()["count"]

    conn.close()

    return {
        "posts": post_count,
        "themes": theme_count,
        "keywords": keyword_count
    }


def get_themes_with_quotes(topic_id: int, source_filter: str = None,
                           intensity_filter: str = None,
                           date_filter: str = None,
                           confidence_range: tuple = (0.0, 1.0),
                           min_post_count: int = 0,
                           keyword_search: str = None) -> list:
    """Get themes with their quotes for a topic with advanced filtering."""
    conn = database.get_connection()
    cursor = conn.cursor()

    query = """
        SELECT t.*,
               GROUP_CONCAT(p.content, '|||') as quotes,
               GROUP_CONCAT(p.source, '|||') as sources
        FROM themes t
        LEFT JOIN theme_posts tp ON t.id = tp.theme_id
        LEFT JOIN posts p ON tp.post_id = p.id
        WHERE t.topic_id = ?
    """
    params = [topic_id]

    if intensity_filter and intensity_filter != "All":
        query += " AND t.intensity = ?"
        params.append(intensity_filter.lower())

    # Date filter on theme first_seen
    if date_filter == "Last 7 Days":
        query += " AND t.first_seen >= datetime('now', '-7 days')"
    elif date_filter == "Last 30 Days":
        query += " AND t.first_seen >= datetime('now', '-30 days')"

    # Confidence score filter
    if confidence_range != (0.0, 1.0):
        query += " AND (t.confidence_score >= ? AND t.confidence_score <= ?)"
        params.extend([confidence_range[0], confidence_range[1]])

    # Minimum post count filter
    if min_post_count > 0:
        query += " AND t.post_count >= ?"
        params.append(min_post_count)

    # Keyword search in name and description
    if keyword_search and keyword_search.strip():
        search_term = f"%{keyword_search.strip()}%"
        query += " AND (t.name LIKE ? OR t.description LIKE ?)"
        params.extend([search_term, search_term])

    query += " GROUP BY t.id ORDER BY t.post_count DESC"

    cursor.execute(query, params)
    themes = []

    for row in cursor.fetchall():
        theme = dict(row)
        # Parse concatenated quotes
        if theme["quotes"]:
            theme["quote_list"] = theme["quotes"].split("|||")[:5]
        else:
            theme["quote_list"] = []
        themes.append(theme)

    conn.close()

    # Apply source filter if needed
    if source_filter and source_filter != "All":
        filtered = []
        for theme in themes:
            sources = theme.get("sources", "") or ""
            if source_filter.lower() in sources.lower():
                filtered.append(theme)
        themes = filtered

    return themes


def themes_to_csv(themes: list, topic_name: str) -> str:
    """Convert themes list to CSV string for export."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Theme Name",
        "Description",
        "Intensity",
        "Emotional Tone",
        "Post Count",
        "Confidence Score",
        "Status",
        "First Seen",
        "Sample Quotes"
    ])

    # Data rows
    for theme in themes:
        quotes = theme.get("quote_list", [])
        sample_quotes = " | ".join(q[:100] for q in quotes[:3]) if quotes else ""

        writer.writerow([
            theme.get("name", ""),
            theme.get("description", "")[:500],
            theme.get("intensity", ""),
            theme.get("emotional_tone", ""),
            theme.get("post_count", 0),
            round(theme.get("confidence_score", 0) or 0, 2),
            theme.get("status", "new"),
            theme.get("first_seen", ""),
            sample_quotes
        ])

    return output.getvalue()


def get_sources(topic_id: int) -> list:
    """Get unique sources for a topic."""
    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT
            CASE
                WHEN source LIKE 'reddit%' THEN 'Reddit'
                WHEN source = 'youtube' THEN 'YouTube'
                WHEN source = 'hackernews' THEN 'Hacker News'
                WHEN source = 'quora' THEN 'Quora'
                ELSE source
            END as source_name
        FROM posts
        WHERE topic_id = ?
    """, (topic_id,))

    sources = [row["source_name"] for row in cursor.fetchall()]
    conn.close()
    return sources


def get_discovered_keywords(topic_id: int, limit: int = 10) -> list:
    """Get discovered keywords not yet promoted."""
    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM discovered_keywords
        WHERE topic_id = ? AND promoted = 0
        ORDER BY occurrence_count DESC
        LIMIT ?
    """, (topic_id, limit))

    keywords = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return keywords


def get_seed_keywords(topic_id: int) -> list:
    """Get seed keywords for a topic."""
    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT keyword FROM keywords
        WHERE topic_id = ? AND is_seed = 1
        ORDER BY keyword
    """, (topic_id,))

    keywords = [row["keyword"] for row in cursor.fetchall()]
    conn.close()
    return keywords


def promote_keyword(keyword_id: int, topic_id: int, keyword_text: str):
    """Promote a discovered keyword to seed status."""
    conn = database.get_connection()
    cursor = conn.cursor()

    # Mark as promoted
    cursor.execute("""
        UPDATE discovered_keywords
        SET promoted = 1
        WHERE id = ?
    """, (keyword_id,))

    # Add to keywords table as seed keyword
    cursor.execute("""
        INSERT OR IGNORE INTO keywords (topic_id, keyword, is_seed, promoted_at)
        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
    """, (topic_id, keyword_text))

    conn.commit()
    conn.close()


def delete_keyword(keyword_id: int):
    """Delete a discovered keyword."""
    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM discovered_keywords WHERE id = ?", (keyword_id,))

    conn.commit()
    conn.close()


def render_theme_card(theme: dict, col):
    """Render a single theme card with status controls."""
    with col:
        # Color based on intensity and status
        intensity_colors = {
            "high": "#ff6b6b",
            "medium": "#ffd93d",
            "low": "#6bcb77"
        }
        status_colors = {
            "new": "#17a2b8",
            "validated": "#28a745",
            "archived": "#6c757d"
        }
        intensity = theme.get("intensity", "medium")
        status = theme.get("status", "new") or "new"
        color = intensity_colors.get(intensity, "#6bcb77")
        status_color = status_colors.get(status, "#17a2b8")

        st.markdown(f"""
        <div style="
            border-left: 4px solid {color};
            padding: 12px;
            margin-bottom: 12px;
            background-color: #f8f9fa;
            border-radius: 4px;
        ">
            <h4 style="margin: 0 0 8px 0;">{theme['name']}</h4>
            <p style="color: #666; font-size: 14px; margin: 0 0 8px 0;">
                {theme.get('description', '')[:150]}...
            </p>
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <span style="background: {status_color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">
                    {status.upper()}
                </span>
                <span style="background: {color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">
                    {intensity.upper()}
                </span>
                <span style="background: #e9ecef; padding: 2px 8px; border-radius: 12px; font-size: 12px;">
                    {theme.get('emotional_tone', 'Unknown')}
                </span>
                <span style="background: #e9ecef; padding: 2px 8px; border-radius: 12px; font-size: 12px;">
                    {theme.get('post_count', 0)} posts
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Theme actions row
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            new_status = st.selectbox(
                "Status",
                ["new", "validated", "archived"],
                index=["new", "validated", "archived"].index(status),
                key=f"status_{theme['id']}",
                label_visibility="collapsed"
            )
            if new_status != status:
                database.update_theme_status(theme["id"], new_status)
                st.rerun()
        with btn_col2:
            if st.button("Delete", key=f"del_{theme['id']}", type="secondary"):
                database.delete_theme(theme["id"])
                st.rerun()

        # Expandable quotes
        with st.expander("View Quotes"):
            for quote in theme.get("quote_list", [])[:3]:
                st.markdown(f"> *\"{quote[:200]}...\"*")


def render_charts(themes: list, topic_id: int):
    """Render the three charts."""
    col1, col2, col3 = st.columns(3)

    # Chart 1: Top themes by frequency
    with col1:
        st.subheader("Top Themes")
        if themes:
            theme_names = [t["name"][:20] for t in themes[:10]]
            post_counts = [t["post_count"] for t in themes[:10]]

            fig = px.bar(
                x=post_counts,
                y=theme_names,
                orientation='h',
                labels={"x": "Posts", "y": "Theme"}
            )
            fig.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=20, b=0),
                yaxis=dict(autorange="reversed")
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No themes yet. Run synthesis first.")

    # Chart 2: Timeline (themes over time)
    with col2:
        st.subheader("Discovery Timeline")
        conn = database.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DATE(first_seen) as date, COUNT(*) as count
            FROM themes
            WHERE topic_id = ?
            GROUP BY DATE(first_seen)
            ORDER BY date
        """, (topic_id,))

        timeline_data = cursor.fetchall()
        conn.close()

        if timeline_data:
            dates = [row["date"] for row in timeline_data]
            counts = [row["count"] for row in timeline_data]

            fig = px.line(
                x=dates,
                y=counts,
                labels={"x": "Date", "y": "Themes Discovered"}
            )
            fig.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=20, b=0)
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No timeline data yet.")

    # Chart 3: Intensity distribution
    with col3:
        st.subheader("Intensity Distribution")
        if themes:
            intensity_counts = {"high": 0, "medium": 0, "low": 0}
            for t in themes:
                intensity = t.get("intensity", "medium")
                if intensity in intensity_counts:
                    intensity_counts[intensity] += 1

            fig = px.pie(
                values=list(intensity_counts.values()),
                names=["High", "Medium", "Low"],
                color_discrete_sequence=["#ff6b6b", "#ffd93d", "#6bcb77"]
            )
            fig.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=20, b=0)
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No intensity data yet.")


# ============================================
# PAIN INTELLIGENCE VIEW FUNCTIONS
# ============================================

def get_pain_intelligence_stats(topic_id: int) -> dict:
    """Get pain intelligence statistics for a topic."""
    return database.get_pain_intelligence_stats(topic_id)


def render_evidence_card(evidence: dict, show_confirmation: bool = True):
    """Render a single pain evidence entry with optional confirmation UI."""
    emotion_colors = {
        "frustrated": "#ff6b6b",
        "overwhelmed": "#ffd93d",
        "anxious": "#9b59b6",
        "resigned": "#95a5a6"
    }

    emotion = evidence.get("emotion") or "unknown"
    color = emotion_colors.get(emotion, "#6c757d")
    confirmed = evidence.get("task_user_confirmed", 0) == 1
    flagged = evidence.get("flagged_for_removal", 0) == 1

    # Status indicator
    if flagged:
        status_badge = '<span style="background: #dc3545; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">FLAGGED</span>'
    elif confirmed:
        status_badge = '<span style="background: #28a745; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">CONFIRMED</span>'
    else:
        status_badge = '<span style="background: #17a2b8; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">PENDING</span>'

    # Build tags display
    lens_tags = evidence.get("human_lens_tags", [])
    if isinstance(lens_tags, str):
        try:
            lens_tags = json.loads(lens_tags)
        except:
            lens_tags = []

    tags_html = ""
    for tag in lens_tags[:3]:
        label = LENS_LABELS.get(tag, tag)
        tags_html += f'<span style="background: #e9ecef; padding: 2px 6px; border-radius: 8px; font-size: 10px; margin-right: 4px;">{label}</span>'

    # Confidence bar
    confidence = evidence.get("ai_confidence", 0) or 0

    st.markdown(f"""
    <div style="
        border-left: 4px solid {color};
        padding: 12px;
        margin-bottom: 12px;
        background-color: {'#fff3cd' if flagged else '#f8f9fa'};
        border-radius: 4px;
    ">
        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
            {status_badge}
            <span style="font-size: 11px; color: #666;">{evidence.get('source', 'unknown')}</span>
        </div>
        <blockquote style="margin: 8px 0; font-style: italic; color: #333; border-left: 2px solid #ddd; padding-left: 10px;">
            "{evidence.get('verbatim_quote', '')[:300]}{'...' if len(evidence.get('verbatim_quote', '')) > 300 else ''}"
        </blockquote>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;">
            <span style="background: {color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">
                {emotion}
            </span>
            {f'<span style="background: #007bff; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{evidence.get("industry", "")}</span>' if evidence.get("industry") else ''}
            {tags_html}
        </div>
        <div style="margin-top: 8px; font-size: 11px; color: #666;">
            Confidence: {confidence:.0%}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Confirmation UI
    if show_confirmation and not confirmed and not flagged:
        with st.expander("Review & Confirm", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                new_task = st.text_input(
                    "Q1: Manual Task",
                    value=evidence.get("manual_task", "") or "",
                    key=f"task_{evidence['id']}",
                    placeholder="What manual task causes frustration?"
                )
                new_cost = st.text_input(
                    "Q2: Cost Impact",
                    value=evidence.get("cost_impact", "") or "",
                    key=f"cost_{evidence['id']}",
                    placeholder="Time/money/errors cost?"
                )

            with col2:
                new_tried = st.text_input(
                    "Q3: Failed Solutions",
                    value=evidence.get("failed_solutions", "") or "",
                    key=f"tried_{evidence['id']}",
                    placeholder="What have they tried?"
                )
                new_ideal = st.text_input(
                    "Q4: Ideal State",
                    value=evidence.get("ideal_state", "") or "",
                    key=f"ideal_{evidence['id']}",
                    placeholder="What would better look like?"
                )

            new_lens = st.multiselect(
                "Human Lens Tags",
                HUMAN_LENS_OPTIONS,
                default=lens_tags,
                key=f"lens_{evidence['id']}",
                format_func=lambda x: LENS_LABELS.get(x, x)
            )

            new_industry = st.selectbox(
                "Industry",
                [""] + INDUSTRY_OPTIONS,
                index=INDUSTRY_OPTIONS.index(evidence.get("industry", "")) + 1 if evidence.get("industry") in INDUSTRY_OPTIONS else 0,
                key=f"industry_{evidence['id']}"
            )

            btn_col1, btn_col2, btn_col3 = st.columns(3)
            with btn_col1:
                if st.button("Confirm", key=f"confirm_{evidence['id']}", type="primary"):
                    database.confirm_evidence(
                        evidence['id'],
                        manual_task=new_task if new_task else None,
                        cost_impact=new_cost if new_cost else None,
                        failed_solutions=new_tried if new_tried else None,
                        ideal_state=new_ideal if new_ideal else None,
                        human_lens_tags=new_lens,
                        industry=new_industry if new_industry else None
                    )
                    st.rerun()
            with btn_col2:
                if st.button("Flag for Removal", key=f"flag_{evidence['id']}"):
                    database.flag_evidence_for_removal(evidence['id'])
                    st.rerun()
            with btn_col3:
                st.button("Skip", key=f"skip_{evidence['id']}")


def render_pain_evidence_view(topic_id: int):
    """Render View 1: Raw Pain Evidence with filters and confirmation UI."""
    st.subheader("Raw Pain Evidence")

    # Filters
    filter_col1, filter_col2, filter_col3, filter_col4, filter_col5 = st.columns(5)

    with filter_col1:
        status_options = ["All", "Pending", "Confirmed", "Flagged"]
        status_filter = st.selectbox("Status", status_options, key="ev_status")

    with filter_col2:
        source_options = ["All", "Reddit", "YouTube", "Hacker News", "Quora", "Review", "Search", "Job Posting"]
        source_filter = st.selectbox("Source", source_options, key="ev_source")

    with filter_col3:
        industry_options = ["All"] + INDUSTRY_OPTIONS
        industry_filter = st.selectbox("Industry", industry_options, key="ev_industry")

    with filter_col4:
        emotion_options = ["All"] + EMOTION_OPTIONS
        emotion_filter = st.selectbox("Emotion", emotion_options, key="ev_emotion")

    with filter_col5:
        question_options = ["All", "Q1: Manual Task", "Q2: Cost Impact", "Q3: Failed Solutions", "Q4: Ideal State", "Flagged"]
        question_filter = st.selectbox("Four Questions", question_options, key="ev_question")

    # Map filters
    confirmed_only = status_filter == "Confirmed"
    include_flagged = status_filter in ["All", "Flagged"]

    question_map = {
        "Q1: Manual Task": "manual_task",
        "Q2: Cost Impact": "cost_impact",
        "Q3: Failed Solutions": "failed_solutions",
        "Q4: Ideal State": "ideal_state",
        "Flagged": "flagged"
    }
    question_value = question_map.get(question_filter) if question_filter != "All" else None

    # Get evidence
    evidence_list = database.get_pain_evidence_for_topic(
        topic_id,
        confirmed_only=confirmed_only,
        include_flagged=include_flagged,
        source_filter=source_filter.lower() if source_filter != "All" else None,
        industry_filter=industry_filter if industry_filter != "All" else None,
        emotion_filter=emotion_filter if emotion_filter != "All" else None,
        question_filter=question_value,
        limit=100
    )

    # Header with count and export
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.write(f"**{len(evidence_list)} entries**")
    with header_col2:
        if evidence_list:
            csv_data = evidence_to_csv(evidence_list)
            st.download_button(
                label="Export CSV",
                data=csv_data,
                file_name=f"pain_evidence_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

    # Show pending confirmation count
    pending = [e for e in evidence_list if not e.get("task_user_confirmed") and not e.get("flagged_for_removal")]
    if pending:
        st.info(f"{len(pending)} entries pending confirmation")

    # Render evidence cards
    if evidence_list:
        for evidence in evidence_list:
            render_evidence_card(evidence, show_confirmation=True)
    else:
        st.info("No pain evidence yet. Run synthesis first.")


def render_pain_clusters_view(topic_id: int):
    """Render View 2: Pain Clusters."""
    st.subheader("Pain Clusters")
    st.caption("Clusters are formed when 3+ evidence entries share the same core pain")

    # Get clusters
    clusters = database.get_pain_clusters_for_topic(topic_id, min_evidence=3)

    if not clusters:
        st.info("No clusters formed yet. Need 3+ similar evidence entries to create a cluster.")
        return

    st.write(f"**{len(clusters)} clusters**")

    # Render cluster cards in 2-column grid
    cols = st.columns(2)
    for i, cluster in enumerate(clusters):
        with cols[i % 2]:
            intensity_colors = {
                "low": "#6bcb77",
                "medium": "#ffd93d",
                "high": "#ff6b6b",
                "critical": "#dc3545"
            }
            intensity = cluster.get("intensity") or "medium"
            color = intensity_colors.get(intensity, "#6c757d")

            # Industries
            industries = cluster.get("industries", [])
            if isinstance(industries, str):
                try:
                    industries = json.loads(industries)
                except:
                    industries = []
            industries_html = " ".join([f'<span style="background: #e9ecef; padding: 2px 6px; border-radius: 8px; font-size: 10px;">{ind}</span>' for ind in industries[:3]])

            st.markdown(f"""
            <div style="
                border: 1px solid #ddd;
                border-left: 4px solid {color};
                padding: 16px;
                margin-bottom: 16px;
                border-radius: 4px;
                background-color: #fff;
            ">
                <h4 style="margin: 0 0 8px 0;">{cluster.get('name', 'Unnamed')}</h4>
                <p style="color: #666; font-size: 13px; margin: 0 0 12px 0;">
                    {cluster.get('description', '')[:200]}
                </p>
                <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">
                    <span style="background: {color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">
                        {intensity.upper()}
                    </span>
                    <span style="background: #17a2b8; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">
                        {cluster.get('evidence_count', 0)} evidence
                    </span>
                    <span style="background: #6c757d; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">
                        {cluster.get('primary_question', 'unknown')}
                    </span>
                </div>
                <div style="margin-top: 8px;">
                    {industries_html}
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Expandable details
            with st.expander("View Details"):
                if cluster.get("trigger_moment"):
                    st.write(f"**Trigger:** {cluster.get('trigger_moment')}")
                if cluster.get("current_workaround"):
                    st.write(f"**Workaround:** {cluster.get('current_workaround')}")
                if cluster.get("consequence_of_failure"):
                    st.write(f"**Consequence:** {cluster.get('consequence_of_failure')}")

                # Show linked evidence
                st.write("**Linked Evidence:**")
                cluster_evidence = database.get_cluster_evidence(cluster["id"])
                for ev in cluster_evidence[:5]:
                    st.markdown(f"> *\"{ev.get('verbatim_quote', '')[:150]}...\"*")

            # Status controls
            status_col1, status_col2 = st.columns(2)
            with status_col1:
                current_status = cluster.get("status", "auto")
                new_status = st.selectbox(
                    "Status",
                    ["auto", "confirmed", "merged", "archived"],
                    index=["auto", "confirmed", "merged", "archived"].index(current_status),
                    key=f"cluster_status_{cluster['id']}",
                    label_visibility="collapsed"
                )
                if new_status != current_status:
                    database.update_cluster_status(cluster["id"], new_status)
                    st.rerun()


def render_failed_solutions_view(topic_id: int):
    """Render View 3: Failed Solutions Analysis."""
    st.subheader("Failed Solutions")
    st.caption("Tools and approaches that have been tried and failed")

    # Get failed solutions
    solutions = database.get_failed_solutions_for_topic(topic_id, min_reports=1)

    if not solutions:
        st.info("No failed solutions tracked yet. These are extracted during synthesis when users mention tools that didn't work.")
        return

    st.write(f"**{len(solutions)} failed solutions tracked**")

    # Summary chart
    if len(solutions) >= 3:
        tool_names = [s.get("tool_tried", "Unknown")[:15] for s in solutions[:10]]
        frequencies = [s.get("reported_count", 1) for s in solutions[:10]]

        fig = px.bar(
            x=frequencies,
            y=tool_names,
            orientation='h',
            labels={"x": "Times Mentioned", "y": "Tool/Approach"},
            title="Most Frequently Failed Tools"
        )
        fig.update_layout(
            height=300,
            margin=dict(l=0, r=0, t=40, b=0),
            yaxis=dict(autorange="reversed")
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Detailed table
    for solution in solutions:
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"### {solution.get('tool_tried', 'Unknown')}")
            if solution.get("tool_category"):
                st.caption(f"Category: {solution.get('tool_category')}")

            if solution.get("why_failed"):
                st.write(f"**Why it failed:** {solution.get('why_failed')}")

            if solution.get("what_broke_first"):
                st.write(f"**What broke first:** {solution.get('what_broke_first')}")

            if solution.get("human_behavior_involved"):
                st.write(f"**Human behavior:** {solution.get('human_behavior_involved')}")

        with col2:
            st.metric("Reports", solution.get("reported_count", 1))

            # Show linked evidence count
            evidence_ids = solution.get("evidence_ids", [])
            if isinstance(evidence_ids, str):
                try:
                    evidence_ids = json.loads(evidence_ids)
                except:
                    evidence_ids = []
            st.caption(f"{len(evidence_ids)} evidence entries")

        st.divider()


def evidence_to_csv(evidence_list: list) -> str:
    """Convert pain evidence to CSV format with verbatim quotes."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    headers = [
        "ID", "Verbatim Quote", "Source", "Industry", "Emotion", "Intensity",
        "Q1: Manual Task", "Q2: Cost Impact", "Q3: Failed Solutions", "Q4: Ideal State",
        "Human Lens Tags", "AI Confidence", "Confirmed", "Flagged", "Created At"
    ]
    writer.writerow(headers)

    for ev in evidence_list:
        lens_tags = ev.get("human_lens_tags", [])
        if isinstance(lens_tags, list):
            lens_str = ", ".join(lens_tags)
        else:
            lens_str = str(lens_tags)

        row = [
            ev.get("id"),
            ev.get("verbatim_quote", ""),
            ev.get("source", ""),
            ev.get("industry", ""),
            ev.get("emotion", ""),
            ev.get("intensity", ""),
            ev.get("manual_task", ""),
            ev.get("cost_impact", ""),
            ev.get("failed_solutions", ""),
            ev.get("ideal_state", ""),
            lens_str,
            round(ev.get("ai_confidence", 0) or 0, 2),
            "Yes" if ev.get("task_user_confirmed") else "No",
            "Yes" if ev.get("flagged_for_removal") else "No",
            ev.get("created_at", "")
        ]
        writer.writerow(row)

    return output.getvalue()


def main():
    """Main dashboard entry point."""
    st.set_page_config(
        page_title="Pain-Point Intelligence",
        page_icon="🎯",
        layout="wide"
    )

    # Initialize session state
    if "background_job" not in st.session_state:
        st.session_state.background_job = None

    # Initialize database
    database.init_database()

    # Load config
    config = load_config()
    topic_names = get_topic_names(config)

    # Header
    st.title("Pain-Point Intelligence Dashboard")

    # Progress indicator (shows if job running/completed/failed)
    job_running = render_progress_indicator()

    # Auto-refresh while job is running
    if job_running:
        time.sleep(2)
        st.rerun()

    # Top bar: Topic selector, Platform selector, and buttons
    col1, col2, col3, col4 = st.columns([2, 2, 1, 1])

    with col1:
        if topic_names:
            selected_topic = st.selectbox(
                "Select Topic",
                topic_names,
                key="topic_selector"
            )
        else:
            st.warning("No topics defined in config.yaml")
            selected_topic = None

    with col2:
        # Platform selector
        available_platforms = ["Reddit", "YouTube", "Hacker News", "Quora"]
        selected_platforms = st.multiselect(
            "Platforms to Scrape",
            available_platforms,
            default=["Reddit"],
            key="platform_selector"
        )
        # Convert display names to internal names
        platform_map = {
            "Reddit": "reddit",
            "YouTube": "youtube",
            "Hacker News": "hackernews",
            "Quora": "quora"
        }
        platforms_to_scrape = [platform_map[p] for p in selected_platforms]

    with col3:
        # Disable buttons while job is running
        scrape_disabled = job_running
        if selected_topic and st.button("Scrape", type="primary", disabled=scrape_disabled):
            if not platforms_to_scrape:
                st.error("Select at least one platform!")
            else:
                # Start background scraping job
                start_background_job(
                    "scrape",
                    run_scraper_background,
                    (selected_topic, platforms_to_scrape)
                )
                st.rerun()

    with col4:
        synth_disabled = job_running
        if selected_topic and st.button("Synthesize", disabled=synth_disabled):
            # Start background synthesis job with pain intelligence mode
            start_background_job(
                "synthesize",
                run_synthesis_background,
                (selected_topic, "pain")
            )
            st.rerun()

    if not selected_topic:
        st.stop()

    # Get topic ID and populate seed keywords from config
    topic_id = database.get_or_create_topic(selected_topic)
    topic_keywords = get_topic_keywords(config, selected_topic)
    database.populate_seed_keywords(topic_id, topic_keywords)

    # Pain Intelligence Stats row
    legacy_stats = get_topic_stats(topic_id)
    pain_stats = get_pain_intelligence_stats(topic_id)

    stat_col1, stat_col2, stat_col3, stat_col4, stat_col5 = st.columns(5)
    stat_col1.metric("Posts", legacy_stats["posts"])
    stat_col2.metric("Evidence", pain_stats["evidence"]["total_evidence"] or 0)
    stat_col3.metric("Confirmed", pain_stats["evidence"]["confirmed_evidence"] or 0)
    stat_col4.metric("Clusters", pain_stats["clusters"]["valid_clusters"] or 0)
    stat_col5.metric("Failed Tools", pain_stats["failed_solutions"]["unique_failed_tools"] or 0)

    st.divider()

    # Main content area with tabbed views
    tab1, tab2, tab3, tab4 = st.tabs([
        "Pain Evidence",
        "Pain Clusters",
        "Failed Solutions",
        "Legacy Themes"
    ])

    with tab1:
        render_pain_evidence_view(topic_id)

    with tab2:
        render_pain_clusters_view(topic_id)

    with tab3:
        render_failed_solutions_view(topic_id)

    with tab4:
        # Legacy theme view
        st.subheader("Legacy Themes View")
        st.caption("This is the original theme extraction view. Use Pain Evidence for the new system.")

        # Filters for legacy view
        filter_col1, filter_col2, filter_col3 = st.columns(3)

        with filter_col1:
            sources = ["All"] + get_sources(topic_id)
            source_filter = st.selectbox("Source", sources, key="legacy_source")

        with filter_col2:
            intensity_filter = st.selectbox("Intensity", ["All", "High", "Medium", "Low"], key="legacy_intensity")

        with filter_col3:
            date_options = ["All Time", "Last 7 Days", "Last 30 Days"]
            date_filter = st.selectbox("Time Period", date_options, key="legacy_date")

        # Advanced filters
        with st.expander("Advanced Filters", expanded=False):
            adv_col1, adv_col2, adv_col3 = st.columns(3)

            with adv_col1:
                confidence_range = st.slider(
                    "Confidence Score",
                    min_value=0.0,
                    max_value=1.0,
                    value=(0.0, 1.0),
                    step=0.1,
                    key="legacy_confidence"
                )

            with adv_col2:
                min_post_count = st.number_input(
                    "Min Posts per Theme",
                    min_value=0,
                    max_value=50,
                    value=0,
                    step=1,
                    key="legacy_min_posts"
                )

            with adv_col3:
                keyword_search = st.text_input(
                    "Search Themes",
                    placeholder="Search in name/description...",
                    key="legacy_search"
                )

        # Get themes
        themes = get_themes_with_quotes(
            topic_id,
            source_filter,
            intensity_filter,
            date_filter,
            confidence_range=confidence_range,
            min_post_count=min_post_count,
            keyword_search=keyword_search
        )

        # Header with count and export
        header_col1, header_col2 = st.columns([3, 1])
        with header_col1:
            st.write(f"**{len(themes)} themes**")
        with header_col2:
            if themes:
                csv_data = themes_to_csv(themes, selected_topic)
                st.download_button(
                    label="Export CSV",
                    data=csv_data,
                    file_name=f"themes_{selected_topic.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="legacy_export"
                )

        if themes:
            # Render in 3-column grid
            cols = st.columns(3)
            for i, theme in enumerate(themes):
                render_theme_card(theme, cols[i % 3])
        else:
            st.info("No themes found. Try scraping and synthesizing with legacy mode.")

        st.divider()

        # Charts
        render_charts(themes, topic_id)

    # Sidebar (shown on all tabs)
    with st.sidebar:
        st.subheader("Keywords")

        # Seed keywords
        with st.expander("Seed Keywords", expanded=False):
            seed_keywords = get_seed_keywords(topic_id)
            if seed_keywords:
                for kw in seed_keywords:
                    st.write(f"• {kw}")
            else:
                st.caption("No seed keywords yet")

        st.divider()

        # Discovered keywords
        st.subheader("Suggested Keywords")
        discovered = get_discovered_keywords(topic_id)

        if discovered:
            for kw in discovered:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"**{kw['keyword']}**")
                with col2:
                    if st.button("+", key=f"promote_{kw['id']}", help="Add to keywords"):
                        promote_keyword(kw["id"], topic_id, kw["keyword"])
                        st.success("Promoted!")
                        st.rerun()
                with col3:
                    if st.button("X", key=f"delete_{kw['id']}", help="Remove"):
                        delete_keyword(kw["id"])
                        st.rerun()
        else:
            st.info("No suggestions yet.")


if __name__ == "__main__":
    main()
