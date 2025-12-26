"""
Playwright-based scraper for Reddit, YouTube, Hacker News, and Quora.

Collects posts and comments containing complaint-related content.
Uses headless browser to handle JavaScript-rendered pages.
"""

import argparse
import random
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import yaml
from playwright.sync_api import sync_playwright, Page, Browser

import database

# Available platforms
PLATFORMS = ["reddit", "youtube", "hackernews", "quora"]


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def random_delay(config: dict, multiplier: float = 1.0):
    """Wait a random amount of time between requests."""
    delay = random.uniform(
        config["scraping"]["delay_min"],
        config["scraping"]["delay_max"]
    ) * multiplier
    time.sleep(delay)


def get_random_user_agent(config: dict) -> str:
    """Get a random user agent from config."""
    return random.choice(config["scraping"]["user_agents"])


def extract_topic_terms(topic_keywords: list) -> set:
    """Extract unique meaningful words from all topic keywords."""
    terms = set()
    stopwords = {'a', 'an', 'the', 'is', 'it', 'to', 'for', 'my', 'i', 'me', 'vs', 'or', 'and'}
    for kw in topic_keywords:
        for word in kw.lower().split():
            if len(word) > 3 and word not in stopwords:
                terms.add(word)
    return terms


def is_relevant_content(content: str, keyword: str, topic_keywords: list) -> bool:
    """Check if content is relevant to the keyword/topic.

    Derives relevance from topic keywords rather than hardcoded terms.
    """
    content_lower = content.lower()

    # Extract meaningful terms from all topic keywords
    topic_terms = extract_topic_terms(topic_keywords)

    # Must contain at least part of the search keyword
    keyword_words = keyword.lower().split()
    keyword_matches = sum(1 for word in keyword_words if len(word) > 3 and word in content_lower)

    # Check how many topic-derived terms appear in content
    topic_matches = sum(1 for term in topic_terms if term in content_lower)

    # Require meaningful relevance:
    # - At least 2 words from the search keyword, OR
    # - At least 3 topic-derived terms
    return keyword_matches >= 2 or topic_matches >= 3


def scrape_reddit(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape Reddit search results for a keyword.

    Uses old.reddit.com for simpler HTML structure.
    Returns list of post dicts with title, content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    base_url = f"https://old.reddit.com/search?q={encoded_keyword}&sort=relevance&t=all"

    try:
        page.goto(base_url, timeout=config["scraping"]["timeout"] * 1000)
        random_delay(config)

        pages_scraped = 0
        max_pages = (max_posts // 25) + 1  # Reddit shows ~25 posts per page

        while len(posts) < max_posts and pages_scraped < max_pages:
            # Wait for search results to load
            try:
                page.wait_for_selector("div.search-result", timeout=10000)
            except:
                break

            # Extract posts from current page
            results = page.query_selector_all("div.search-result")

            for result in results:
                if len(posts) >= max_posts:
                    break

                try:
                    # Extract title
                    title_elem = result.query_selector("a.search-title")
                    title = title_elem.inner_text() if title_elem else ""

                    # Extract URL
                    url = title_elem.get_attribute("href") if title_elem else ""
                    if url and not url.startswith("http"):
                        url = "https://old.reddit.com" + url

                    # Extract subreddit
                    subreddit_elem = result.query_selector("a.search-subreddit-link")
                    subreddit = subreddit_elem.inner_text() if subreddit_elem else ""

                    # Extract post text/snippet
                    text_elem = result.query_selector("div.search-result-body")
                    content = text_elem.inner_text() if text_elem else ""

                    # Extract author
                    author_elem = result.query_selector("a.author")
                    author = author_elem.inner_text() if author_elem else ""

                    if title and content and len(content) > 20:
                        posts.append({
                            "title": title.strip(),
                            "content": content.strip()[:2000],
                            "url": url,
                            "author": author,
                            "source": f"reddit/{subreddit}" if subreddit else "reddit"
                        })

                except Exception as e:
                    continue

            # Try to go to next page
            next_button = page.query_selector("span.next-button a")
            if next_button and len(posts) < max_posts:
                next_button.click()
                random_delay(config)
                pages_scraped += 1
            else:
                break

    except Exception as e:
        print(f"    Error scraping Reddit for '{keyword}': {e}")

    return posts


def scrape_youtube(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape YouTube comments for videos matching a keyword.

    Searches for videos, clicks into each, and extracts comments.
    Returns list of comment dicts with content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    search_url = f"https://www.youtube.com/results?search_query={encoded_keyword}"

    try:
        page.goto(search_url, timeout=config["scraping"]["timeout"] * 1000)
        random_delay(config)

        # Wait for video results with longer timeout
        try:
            page.wait_for_selector("ytd-video-renderer", timeout=20000)
        except:
            print(f"    YouTube search timed out for '{keyword}'")
            return posts

        # Get video links (limit to first 3 videos per keyword for speed)
        video_elements = page.query_selector_all("ytd-video-renderer a#video-title")[:3]
        video_urls = []

        for elem in video_elements:
            href = elem.get_attribute("href")
            if href and "/watch?" in href:
                full_url = "https://www.youtube.com" + href
                video_urls.append(full_url)

        # Visit each video and extract comments
        for video_url in video_urls:
            if len(posts) >= max_posts:
                break

            try:
                page.goto(video_url, timeout=config["scraping"]["timeout"] * 1000)
                random_delay(config, multiplier=1.5)  # Extra delay for YouTube

                # Get video title with longer timeout
                try:
                    page.wait_for_selector("h1.ytd-watch-metadata, h1.ytd-video-primary-info-renderer", timeout=15000)
                    title_elem = page.query_selector("h1.ytd-watch-metadata") or page.query_selector("h1.ytd-video-primary-info-renderer")
                    video_title = title_elem.inner_text() if title_elem else "Unknown Video"
                except:
                    video_title = "Unknown Video"

                # Scroll down multiple times to load comments
                for _ in range(5):
                    page.evaluate("window.scrollBy(0, 600)")
                    time.sleep(0.8)

                # Wait for comments with longer timeout
                try:
                    page.wait_for_selector("ytd-comment-thread-renderer", timeout=20000)
                except:
                    print(f"    No comments loaded for: {video_title[:40]}...")
                    continue

                # Extra scroll to ensure comments are loaded
                time.sleep(1)

                # Extract comments
                comments = page.query_selector_all("ytd-comment-thread-renderer")[:10]

                for comment in comments:
                    if len(posts) >= max_posts:
                        break

                    try:
                        # Extract comment text
                        text_elem = comment.query_selector("#content-text")
                        content = text_elem.inner_text() if text_elem else ""

                        # Extract author
                        author_elem = comment.query_selector("#author-text")
                        author = author_elem.inner_text().strip() if author_elem else ""

                        if content and len(content) > 20:
                            posts.append({
                                "title": video_title.strip()[:200],
                                "content": content.strip()[:2000],
                                "url": video_url,
                                "author": author,
                                "source": "youtube"
                            })

                    except Exception as e:
                        continue

                random_delay(config)

            except Exception as e:
                print(f"    Error scraping video: {e}")
                continue

    except Exception as e:
        print(f"    Error scraping YouTube for '{keyword}': {e}")

    return posts


def scrape_hackernews(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape Hacker News search results using Algolia search.

    Returns list of post/comment dicts with title, content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    # Use Algolia-powered HN search
    search_url = f"https://hn.algolia.com/?q={encoded_keyword}"

    try:
        page.goto(search_url, timeout=config["scraping"]["timeout"] * 1000)
        random_delay(config)

        # Wait for results
        try:
            page.wait_for_selector(".Story, .Comment", timeout=15000)
        except:
            print(f"    No Hacker News results for '{keyword}'")
            return posts

        # Extract stories and comments
        items = page.query_selector_all(".Story, .Comment")[:max_posts]

        for item in items:
            if len(posts) >= max_posts:
                break

            try:
                # Check if it's a story or comment
                is_story = "Story" in (item.get_attribute("class") or "")

                if is_story:
                    # Extract story title
                    title_elem = item.query_selector(".Story_title a")
                    title = title_elem.inner_text() if title_elem else ""

                    # Get HN discussion URL
                    link_elem = item.query_selector(".Story_meta a[href*='item?id=']")
                    url = link_elem.get_attribute("href") if link_elem else ""
                    if url and not url.startswith("http"):
                        url = "https://news.ycombinator.com/" + url

                    # Author
                    author_elem = item.query_selector(".Story_meta a[href*='user?id=']")
                    author = author_elem.inner_text() if author_elem else ""

                    content = title  # For stories, title is the main content

                else:
                    # It's a comment
                    text_elem = item.query_selector(".Comment_text")
                    content = text_elem.inner_text() if text_elem else ""
                    title = content[:100] + "..." if len(content) > 100 else content

                    # Get parent story link
                    link_elem = item.query_selector("a[href*='item?id=']")
                    url = link_elem.get_attribute("href") if link_elem else ""
                    if url and not url.startswith("http"):
                        url = "https://news.ycombinator.com/" + url

                    # Author
                    author_elem = item.query_selector("a[href*='user?id=']")
                    author = author_elem.inner_text() if author_elem else ""

                if content and len(content) > 15:
                    posts.append({
                        "title": title.strip()[:200],
                        "content": content.strip()[:2000],
                        "url": url,
                        "author": author,
                        "source": "hackernews"
                    })

            except Exception as e:
                continue

    except Exception as e:
        print(f"    Error scraping Hacker News for '{keyword}': {e}")

    return posts


def scrape_quora(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape Quora search results for a keyword.

    Returns list of question/answer dicts with title, content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    search_url = f"https://www.quora.com/search?q={encoded_keyword}"

    try:
        page.goto(search_url, timeout=config["scraping"]["timeout"] * 1000)
        random_delay(config, multiplier=1.5)  # Quora is slow

        # Wait for results - Quora uses dynamic loading
        try:
            page.wait_for_selector("[class*='qu-borderBottom']", timeout=20000)
        except:
            print(f"    No Quora results for '{keyword}'")
            return posts

        # Scroll to load more content
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(1)

        # Extract questions/answers - Quora's structure is complex
        # Look for question links and their preview text
        items = page.query_selector_all("[class*='qu-borderBottom']")[:max_posts * 2]

        seen_urls = set()
        for item in items:
            if len(posts) >= max_posts:
                break

            try:
                # Find question link
                link_elem = item.query_selector("a[href*='/']")
                if not link_elem:
                    continue

                url = link_elem.get_attribute("href") or ""
                if not url or url in seen_urls:
                    continue
                if not url.startswith("http"):
                    url = "https://www.quora.com" + url

                # Skip non-question URLs
                if "/profile/" in url or "/topic/" in url:
                    continue

                seen_urls.add(url)

                # Get question text
                title = link_elem.inner_text().strip()

                # Try to get answer preview
                content_elem = item.query_selector("[class*='q-text']")
                content = content_elem.inner_text() if content_elem else title

                if not content or len(content) < 20:
                    content = title

                if title and len(title) > 10:
                    posts.append({
                        "title": title[:200],
                        "content": content.strip()[:2000],
                        "url": url,
                        "author": "",
                        "source": "quora"
                    })

            except Exception as e:
                continue

    except Exception as e:
        print(f"    Error scraping Quora for '{keyword}': {e}")

    return posts


def run_scraper(topic_name: str = None, platforms: list = None) -> dict:
    """
    Main scraper entry point.

    Scrapes specified platforms for a topic (or all topics if none specified).
    Saves posts to SQLite database.
    Returns dict with scrape statistics.

    Args:
        topic_name: Name of topic to scrape (None = all topics)
        platforms: List of platforms to scrape (None = all platforms)
    """
    config = load_config()
    database.init_database()

    # Default to all platforms if none specified
    if platforms is None:
        platforms = PLATFORMS

    # Validate platforms
    platforms = [p.lower() for p in platforms if p.lower() in PLATFORMS]
    if not platforms:
        platforms = PLATFORMS

    # Determine which topics to scrape
    topics_to_scrape = []
    for topic in config["topics"]:
        if topic_name is None or topic["name"] == topic_name:
            topics_to_scrape.append(topic)

    if not topics_to_scrape:
        print(f"Topic '{topic_name}' not found in config.")
        return {"error": f"Topic '{topic_name}' not found"}

    stats = {
        "topics_scraped": 0,
        "keywords_processed": 0,
        "posts_found": 0,
        "posts_saved": 0,
        "duplicates_skipped": 0,
        "platforms_used": platforms
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=get_random_user_agent(config),
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        for topic in topics_to_scrape:
            print(f"\nScraping topic: {topic['name']}")
            print(f"Platforms: {', '.join(platforms)}")
            topic_id = database.get_or_create_topic(topic["name"])
            max_posts = topic.get("max_posts_per_keyword", 50)

            topic_keywords = topic["keywords"]  # For relevance filtering

            for keyword in topic_keywords:
                print(f"  Keyword: '{keyword}'")
                keyword_id = database.add_keyword(topic_id, keyword, is_seed=True)

                def save_if_relevant(post, keyword, topic_keywords):
                    """Save post only if content is relevant to the topic."""
                    content = f"{post['title']} {post['content']}"
                    if not is_relevant_content(content, keyword, topic_keywords):
                        return "skipped"
                    post_id = database.add_post(
                        topic_id=topic_id,
                        keyword_id=keyword_id,
                        source=post["source"],
                        url=post["url"],
                        title=post["title"],
                        content=post["content"],
                        author=post["author"]
                    )
                    return "saved" if post_id else "duplicate"

                # Scrape each enabled platform
                if "reddit" in platforms:
                    print(f"    Scraping Reddit...")
                    reddit_posts = scrape_reddit(page, keyword, max_posts, config)
                    saved, skipped = 0, 0
                    for post in reddit_posts:
                        result = save_if_relevant(post, keyword, topic_keywords)
                        if result == "saved":
                            stats["posts_saved"] += 1
                            saved += 1
                        elif result == "duplicate":
                            stats["duplicates_skipped"] += 1
                        else:
                            skipped += 1
                        stats["posts_found"] += 1
                    print(f"    Found {len(reddit_posts)}, saved {saved}, filtered {skipped}")

                if "youtube" in platforms:
                    print(f"    Scraping YouTube...")
                    youtube_posts = scrape_youtube(page, keyword, max_posts // 2, config)
                    saved, skipped = 0, 0
                    for post in youtube_posts:
                        result = save_if_relevant(post, keyword, topic_keywords)
                        if result == "saved":
                            stats["posts_saved"] += 1
                            saved += 1
                        elif result == "duplicate":
                            stats["duplicates_skipped"] += 1
                        else:
                            skipped += 1
                        stats["posts_found"] += 1
                    print(f"    Found {len(youtube_posts)}, saved {saved}, filtered {skipped}")

                if "hackernews" in platforms:
                    print(f"    Scraping Hacker News...")
                    hn_posts = scrape_hackernews(page, keyword, max_posts, config)
                    saved, skipped = 0, 0
                    for post in hn_posts:
                        result = save_if_relevant(post, keyword, topic_keywords)
                        if result == "saved":
                            stats["posts_saved"] += 1
                            saved += 1
                        elif result == "duplicate":
                            stats["duplicates_skipped"] += 1
                        else:
                            skipped += 1
                        stats["posts_found"] += 1
                    print(f"    Found {len(hn_posts)}, saved {saved}, filtered {skipped}")

                if "quora" in platforms:
                    print(f"    Scraping Quora...")
                    quora_posts = scrape_quora(page, keyword, max_posts, config)
                    saved, skipped = 0, 0
                    for post in quora_posts:
                        result = save_if_relevant(post, keyword, topic_keywords)
                        if result == "saved":
                            stats["posts_saved"] += 1
                            saved += 1
                        elif result == "duplicate":
                            stats["duplicates_skipped"] += 1
                        else:
                            skipped += 1
                        stats["posts_found"] += 1
                    print(f"    Found {len(quora_posts)}, saved {saved}, filtered {skipped}")

                stats["keywords_processed"] += 1

            stats["topics_scraped"] += 1

        browser.close()

    print(f"\nScraping complete!")
    print(f"  Topics scraped: {stats['topics_scraped']}")
    print(f"  Keywords processed: {stats['keywords_processed']}")
    print(f"  Posts found: {stats['posts_found']}")
    print(f"  Posts saved: {stats['posts_saved']}")
    print(f"  Duplicates skipped: {stats['duplicates_skipped']}")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape platforms for research")
    parser.add_argument("--topic", type=str, help="Topic name to scrape (from config.yaml)")
    parser.add_argument("--platforms", type=str, help="Comma-separated platforms: reddit,youtube,hackernews,quora")
    args = parser.parse_args()

    platforms = None
    if args.platforms:
        platforms = [p.strip() for p in args.platforms.split(",")]

    run_scraper(args.topic, platforms)
