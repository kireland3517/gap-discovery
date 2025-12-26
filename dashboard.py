"""
Streamlit dashboard for Research Pattern Discovery System.

Features:
- Topic selector dropdown
- Scrape button (synchronous, freezes UI)
- Filter bar (source, date range, intensity)
- Theme cards with expandable quotes
- Charts: top themes, timeline, intensity distribution
- Sidebar: discovered keywords with promote button
"""

import subprocess
import sys
from pathlib import Path

import plotly.express as px
import streamlit as st
import yaml

import database
import synthesize


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
                           date_filter: str = None) -> list:
    """Get themes with their quotes for a topic."""
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


def main():
    """Main dashboard entry point."""
    st.set_page_config(
        page_title="Research Pattern Discovery",
        page_icon="🔍",
        layout="wide"
    )

    # Initialize database
    database.init_database()

    # Load config
    config = load_config()
    topic_names = get_topic_names(config)

    # Header
    st.title("Research Pattern Discovery")

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
        if selected_topic and st.button("Scrape", type="primary"):
            if not platforms_to_scrape:
                st.error("Select at least one platform!")
            else:
                with st.spinner(f"Scraping {', '.join(selected_platforms)}..."):
                    # Run scraper as subprocess to avoid asyncio conflicts
                    platforms_arg = ",".join(platforms_to_scrape)
                    result = subprocess.run(
                        [sys.executable, "scrape.py", "--topic", selected_topic,
                         "--platforms", platforms_arg],
                        capture_output=True,
                        text=True,
                        cwd=str(Path(__file__).parent),
                        check=False
                    )
                    if result.returncode == 0:
                        st.success("Scraping complete!")
                    else:
                        st.error(f"Scrape failed: {result.stderr[:200]}")
                    st.rerun()

    with col4:
        if selected_topic and st.button("Synthesize"):
            with st.spinner("Analyzing with Claude..."):
                synth_topic_id = database.get_or_create_topic(selected_topic)
                stats = synthesize.run_synthesis(selected_topic, process_all=True)
                # Reset processed flag so posts can be re-analyzed
                database.reset_processed_posts(synth_topic_id)
                st.success(f"Created {stats.get('themes_created', 0)} themes!")
                st.rerun()

    if not selected_topic:
        st.stop()

    # Get topic ID and populate seed keywords from config
    topic_id = database.get_or_create_topic(selected_topic)
    topic_keywords = get_topic_keywords(config, selected_topic)
    database.populate_seed_keywords(topic_id, topic_keywords)

    # Stats row
    stats = get_topic_stats(topic_id)
    stat_col1, stat_col2, stat_col3 = st.columns(3)
    stat_col1.metric("Posts Collected", stats["posts"])
    stat_col2.metric("Themes Found", stats["themes"])
    stat_col3.metric("Seed Keywords", stats["keywords"])

    st.divider()

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        sources = ["All"] + get_sources(topic_id)
        source_filter = st.selectbox("Source", sources)

    with filter_col2:
        intensity_filter = st.selectbox("Intensity", ["All", "High", "Medium", "Low"])

    with filter_col3:
        date_options = ["All Time", "Last 7 Days", "Last 30 Days"]
        date_filter = st.selectbox("Time Period", date_options)

    st.divider()

    # Main content area with sidebar
    main_col, sidebar_col = st.columns([4, 1])

    with main_col:
        # Theme cards
        st.subheader("Themes")
        themes = get_themes_with_quotes(topic_id, source_filter, intensity_filter, date_filter)

        if themes:
            # Render in 3-column grid
            cols = st.columns(3)
            for i, theme in enumerate(themes):
                render_theme_card(theme, cols[i % 3])
        else:
            st.info("No themes found. Try scraping and synthesizing first.")

        st.divider()

        # Charts
        render_charts(themes, topic_id)

    with sidebar_col:
        # Seed keywords (collapsible)
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
            st.info("No suggestions yet. Run synthesis to discover keywords.")


if __name__ == "__main__":
    main()
