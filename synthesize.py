"""
Theme synthesis using Claude API.

Sends batches of posts to Claude for pattern analysis.
Extracts recurring themes, emotional tones, and discovered keywords.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import yaml
from anthropic import Anthropic

import database

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds, will be multiplied for exponential backoff


SYNTHESIS_PROMPT = """
You are a qualitative researcher analyzing raw user language from online communities.
Your job is to surface patterns of PAIN, not solutions.

## CRITICAL BEHAVIORAL LOCKS

1. **Suppress novelty** - Only report patterns that appear 3+ times in the data
2. **Prioritize repetition** - Exact phrases matter more than paraphrases
3. **Refuse to brainstorm** - If you catch yourself suggesting solutions, stop immediately
4. **Infer behavior** - Focus on what people actually DID, not what they said they want
5. **Preserve their language** - Use their words, not your interpretation

## FORBIDDEN ACTIONS

- DO NOT propose solutions, products, or improvements
- DO NOT interpret or editorialize beyond the evidence
- DO NOT merge distinct pain points into vague categories
- DO NOT include pains that only appear once or twice
- DO NOT speculate about what they "might" want

## Your Task

Analyze these posts and identify recurring THEMES of pain or frustration.

For each theme, determine:
1. **Name**: Short descriptive name (2-4 words)
2. **Description**: The core complaint in THEIR words (not your interpretation)
3. **Intensity**: High, Medium, or Low based on emotional language
4. **Emotional Tone**: Frustration, Shame, Overwhelm, Anxiety, or Resignation
5. **Representative Quotes**: 3-5 exact quotes capturing the theme
6. **Post IDs**: Which posts belong to this theme

## Output Format

Return a JSON object with this exact structure:

```json
{
  "themes": [
    {
      "name": "Theme Name Here",
      "description": "Core complaint in their words",
      "intensity": "high",
      "emotional_tone": "Frustration",
      "quotes": ["exact quote 1", "exact quote 2", "exact quote 3"],
      "post_ids": [1, 5, 12, 34]
    }
  ],
  "discovered_keywords": ["potential keyword 1", "potential keyword 2"],
  "meta": {
    "total_posts_analyzed": 50,
    "dominant_emotion": "Frustration"
  }
}
```

## Quality Checks

Before responding, verify:
- Every theme appears in at least 3 posts
- Quotes are EXACT text, not paraphrased
- No solutions or recommendations slipped in
- Distinct pains are NOT merged into vague categories

## Posts to Analyze

{posts}
"""


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_unprocessed_posts(topic_id: int, limit: int = 100) -> list:
    """Get posts that haven't been processed yet."""
    conn = database.get_connection()
    cursor = conn.cursor()

    # Get posts with processed = 0 (or NULL for legacy data)
    cursor.execute("""
        SELECT p.id, p.title, p.content, p.source, p.url
        FROM posts p
        WHERE p.topic_id = ?
        AND (p.processed = 0 OR p.processed IS NULL)
        ORDER BY p.scraped_at DESC
        LIMIT ?
    """, (topic_id, limit))

    posts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return posts


def mark_posts_processed(post_ids: list):
    """Mark posts as processed after synthesis."""
    if not post_ids:
        return
    conn = database.get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" * len(post_ids))
    cursor.execute(f"UPDATE posts SET processed = 1 WHERE id IN ({placeholders})", post_ids)
    conn.commit()
    conn.close()


def determine_intensity(content: str, config: dict) -> str:
    """Determine intensity based on config keywords."""
    content_lower = content.lower()
    intensity_keywords = config["synthesis"]["intensity_keywords"]

    high_count = sum(1 for kw in intensity_keywords["high"] if kw in content_lower)
    medium_count = sum(1 for kw in intensity_keywords["medium"] if kw in content_lower)
    low_count = sum(1 for kw in intensity_keywords["low"] if kw in content_lower)

    if high_count > 0:
        return "high"
    elif medium_count > 0:
        return "medium"
    else:
        return "low"


def format_posts_for_prompt(posts: list) -> str:
    """Format posts for inclusion in the prompt."""
    formatted = []
    for post in posts:
        formatted.append(f"[Post ID: {post['id']}]\n"
                        f"Source: {post['source']}\n"
                        f"Title: {post['title']}\n"
                        f"Content: {post['content']}\n")
    return "\n---\n".join(formatted)


def parse_claude_response(response_text: str) -> dict | None:
    """Extract JSON from Claude's response."""
    # Try to find JSON in the response
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try parsing the whole response as JSON
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        print("Failed to parse Claude response as JSON")
        print(f"Response preview: {response_text[:500]}...")
        return None


def save_themes(themes: list, topic_id: int, config: dict) -> int:
    """Save extracted themes to database. Returns number saved."""
    conn = database.get_connection()
    cursor = conn.cursor()
    saved_count = 0

    for theme in themes:
        try:
            post_ids = theme.get("post_ids", [])

            # Determine intensity if not provided
            intensity = theme.get("intensity", "medium")
            if isinstance(intensity, str):
                intensity = intensity.lower()
            if intensity not in ("low", "medium", "high"):
                intensity = "medium"

            # Get theme name - handle different formats
            name = theme.get("name") or theme.get("theme_name") or "Unnamed Theme"

            # Insert theme
            cursor.execute("""
                INSERT INTO themes (topic_id, name, description, intensity, emotional_tone, post_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                topic_id,
                name,
                theme.get("description", ""),
                intensity,
                theme.get("emotional_tone", ""),
                len(post_ids) if post_ids else 0
            ))
            theme_id = cursor.lastrowid
            saved_count += 1

            # Link posts to theme (if post_ids are valid)
            for i, post_id in enumerate(post_ids):
                try:
                    # Ensure post_id is an integer
                    post_id = int(post_id)
                    relevance = max(0.1, 1.0 - (i * 0.1))
                    cursor.execute("""
                        INSERT OR IGNORE INTO theme_posts (theme_id, post_id, relevance_score)
                        VALUES (?, ?, ?)
                    """, (theme_id, post_id, relevance))
                except (ValueError, TypeError):
                    continue
                except Exception as e:
                    continue

            print(f"  Saved theme: '{name}' ({len(post_ids) if post_ids else 0} posts)")

        except Exception as e:
            print(f"  Error saving theme: {e}")
            continue

    conn.commit()
    conn.close()
    return saved_count


def save_discovered_keywords(keywords: list, topic_id: int):
    """Save discovered keywords. Only inserts new ones, doesn't increment existing."""
    conn = database.get_connection()
    cursor = conn.cursor()

    for keyword in keywords:
        keyword = keyword.strip().lower()
        if len(keyword) < 5:  # Skip very short keywords
            continue

        try:
            # Only insert if new - don't increment count on duplicates
            cursor.execute("""
                INSERT OR IGNORE INTO discovered_keywords (topic_id, keyword)
                VALUES (?, ?)
            """, (topic_id, keyword))
        except Exception as e:
            print(f"  Warning: Could not save keyword '{keyword}': {e}")

    conn.commit()
    conn.close()


def batch_synthesize(posts: list, config: dict) -> dict | None:
    """Send a batch of posts to Claude for analysis with retry logic."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return None
    client = Anthropic(api_key=api_key)

    formatted_posts = format_posts_for_prompt(posts)
    prompt = SYNTHESIS_PROMPT.replace("{posts}", formatted_posts)

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=config["anthropic"]["model"],
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.content[0].text
            result = parse_claude_response(response_text)

            if result is None:
                print(f"  Parse failed, response preview: {response_text[:300]}...")

            return result

        except Exception as e:
            delay = RETRY_DELAY * (2 ** attempt)
            print(f"  Claude API error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                print(f"  Retrying in {delay}s...")
                time.sleep(delay)
            else:
                print("  Max retries reached, giving up.")
                return None

    return None


def run_synthesis(topic_name: str = None, process_all: bool = False) -> dict:
    """
    Main synthesis entry point.

    Processes posts in batches and extracts themes.
    Args:
        topic_name: Topic to process (or first topic if None)
        process_all: If True, process all batches; if False, process one batch
    Returns dict with synthesis statistics.
    """
    config = load_config()
    database.init_database()

    # Get topic ID
    conn = database.get_connection()
    cursor = conn.cursor()

    if topic_name:
        cursor.execute("SELECT id, name FROM topics WHERE name = ?", (topic_name,))
    else:
        cursor.execute("SELECT id, name FROM topics LIMIT 1")

    row = cursor.fetchone()
    conn.close()

    if not row:
        print(f"Topic '{topic_name}' not found in database.")
        return {"error": "Topic not found"}

    topic_id = row["id"]
    topic_name = row["name"]

    print(f"\nSynthesizing themes for: {topic_name}")

    stats = {
        "posts_processed": 0,
        "themes_created": 0,
        "keywords_discovered": 0,
        "batches_run": 0
    }

    batch_size = config["synthesis"]["batch_size"]

    while True:
        # Get unprocessed posts
        posts = get_unprocessed_posts(topic_id, limit=batch_size)

        if not posts:
            print("No more unprocessed posts.")
            break

        post_ids = [p["id"] for p in posts]
        print(f"\nProcessing batch of {len(posts)} posts...")
        stats["posts_processed"] += len(posts)

        # Send to Claude
        result = batch_synthesize(posts, config)

        # Mark posts as processed regardless of result to avoid reprocessing
        mark_posts_processed(post_ids)

        if result:
            # Debug: show what Claude returned
            print(f"  Claude returned: {list(result.keys())}")

            # Save themes
            themes = result.get("themes", [])
            if themes:
                print(f"  Found {len(themes)} themes in response")
                saved = save_themes(themes, topic_id, config)
                stats["themes_created"] += saved
            else:
                print("  No themes found in Claude response")

            # Save discovered keywords
            keywords = result.get("discovered_keywords", [])
            if keywords:
                save_discovered_keywords(keywords, topic_id)
                stats["keywords_discovered"] += len(keywords)

            stats["batches_run"] += 1
        else:
            print("  Failed to get valid response from Claude")

        # If not processing all, break after first batch
        if not process_all:
            break

    print("\nSynthesis complete!")
    print(f"  Posts processed: {stats['posts_processed']}")
    print(f"  Themes created: {stats['themes_created']}")
    print(f"  Keywords discovered: {stats['keywords_discovered']}")
    print(f"  Batches run: {stats['batches_run']}")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthesize themes from scraped posts")
    parser.add_argument("--topic", type=str, help="Topic name to synthesize")
    parser.add_argument(
        "--all", action="store_true",
        help="Process all unprocessed posts (not just one batch)"
    )
    args = parser.parse_args()

    run_synthesis(args.topic, process_all=args.all)
