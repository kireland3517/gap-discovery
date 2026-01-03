"""
Playwright-based scraper for Reddit, YouTube, Hacker News, Quora, and Pain Intelligence sources.

Collects posts and comments containing complaint-related content.
Pain Intelligence scrapers collect: Google autocomplete/PAA, tool reviews, community forums, job descriptions.
Uses async headless browser with retry logic for reliability.
"""

import argparse
import asyncio
import json
import random
import re
from pathlib import Path
from urllib.parse import quote_plus, urlencode

import yaml
from playwright.async_api import async_playwright, Page, Browser, Error as PlaywrightError, TimeoutError as PlaywrightTimeout

import database

# Retryable exceptions - transient failures that may succeed on retry
RETRYABLE_EXCEPTIONS = (
    PlaywrightError,      # Playwright network/browser errors
    PlaywrightTimeout,    # Page load timeouts
    asyncio.TimeoutError, # Async timeouts
    ConnectionError,      # Network connection issues
    OSError,              # Low-level network errors (includes socket errors)
)
from complaint_detector import is_complaint

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 2  # seconds

# Available platforms
PLATFORMS = ["reddit", "youtube", "hackernews", "quora"]

# Pain Intelligence scraper types
PAIN_SCRAPERS = [
    "google_autocomplete",
    "google_paa",
    "g2_reviews",
    "capterra_reviews",
    "zapier_community",
    "make_community",
    "hubspot_community",
    "linkedin_jobs",
    "indeed_jobs"
]


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def random_delay(config: dict, multiplier: float = 1.0):
    """Wait a random amount of time between requests (async)."""
    delay = random.uniform(
        config["scraping"]["delay_min"],
        config["scraping"]["delay_max"]
    ) * multiplier
    await asyncio.sleep(delay)


def get_random_user_agent(config: dict) -> str:
    """Get a random user agent from config."""
    return random.choice(config["scraping"]["user_agents"])


async def with_retry(coro_func, *args, max_retries: int = MAX_RETRIES, **kwargs):
    """
    Execute async function with exponential backoff retry.

    Only retries on transient network/browser errors (RETRYABLE_EXCEPTIONS).
    Programming errors (TypeError, ValueError, etc.) are raised immediately.
    Delays: 2s, 4s, 8s for attempts 1, 2, 3
    Returns empty list on complete failure.
    """
    last_exception = None
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except RETRYABLE_EXCEPTIONS as e:
            # Transient error - retry with backoff
            last_exception = e
            if attempt < max_retries - 1:
                delay = BASE_DELAY * (2 ** attempt)
                print(f"      Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                print(f"      All {max_retries} attempts failed: {e}")
        # Note: Other exceptions (TypeError, ValueError, etc.) propagate immediately

    return []  # Return empty list on failure


async def scrape_reddit(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape Reddit search results for a keyword (async).

    Uses old.reddit.com for simpler HTML structure.
    Returns list of post dicts with title, content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    base_url = f"https://old.reddit.com/search?q={encoded_keyword}&sort=relevance&t=all"

    try:
        await page.goto(base_url, timeout=config["scraping"]["timeout"] * 1000)
        await random_delay(config)

        pages_scraped = 0
        max_pages = (max_posts // 25) + 1  # Reddit shows ~25 posts per page

        while len(posts) < max_posts and pages_scraped < max_pages:
            # Wait for search results to load
            try:
                await page.wait_for_selector("div.search-result", timeout=10000)
            except:
                break

            # Extract posts from current page
            results = await page.query_selector_all("div.search-result")

            for result in results:
                if len(posts) >= max_posts:
                    break

                try:
                    # Extract title
                    title_elem = await result.query_selector("a.search-title")
                    title = await title_elem.inner_text() if title_elem else ""

                    # Extract URL
                    url = await title_elem.get_attribute("href") if title_elem else ""
                    if url and not url.startswith("http"):
                        url = "https://old.reddit.com" + url

                    # Extract subreddit
                    subreddit_elem = await result.query_selector("a.search-subreddit-link")
                    subreddit = await subreddit_elem.inner_text() if subreddit_elem else ""

                    # Extract post text/snippet
                    text_elem = await result.query_selector("div.search-result-body")
                    content = await text_elem.inner_text() if text_elem else ""

                    # Extract author
                    author_elem = await result.query_selector("a.author")
                    author = await author_elem.inner_text() if author_elem else ""

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
            next_button = await page.query_selector("span.next-button a")
            if next_button and len(posts) < max_posts:
                await next_button.click()
                await random_delay(config)
                pages_scraped += 1
            else:
                break

    except Exception as e:
        print(f"    Error scraping Reddit for '{keyword}': {e}")

    return posts


async def scrape_youtube(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape YouTube comments for videos matching a keyword (async).

    Searches for videos, clicks into each, and extracts comments.
    Returns list of comment dicts with content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    search_url = f"https://www.youtube.com/results?search_query={encoded_keyword}"

    try:
        await page.goto(search_url, timeout=config["scraping"]["timeout"] * 1000)
        await random_delay(config)

        # Wait for video results with longer timeout
        try:
            await page.wait_for_selector("ytd-video-renderer", timeout=20000)
        except:
            print(f"    YouTube search timed out for '{keyword}'")
            return posts

        # Get video links (limit to first 3 videos per keyword for speed)
        video_elements = await page.query_selector_all("ytd-video-renderer a#video-title")
        video_elements = video_elements[:3]
        video_urls = []

        for elem in video_elements:
            href = await elem.get_attribute("href")
            if href and "/watch?" in href:
                full_url = "https://www.youtube.com" + href
                video_urls.append(full_url)

        # Visit each video and extract comments
        for video_url in video_urls:
            if len(posts) >= max_posts:
                break

            try:
                await page.goto(video_url, timeout=config["scraping"]["timeout"] * 1000)
                await random_delay(config, multiplier=1.5)  # Extra delay for YouTube

                # Get video title with longer timeout
                try:
                    await page.wait_for_selector("h1.ytd-watch-metadata, h1.ytd-video-primary-info-renderer", timeout=15000)
                    title_elem = await page.query_selector("h1.ytd-watch-metadata") or await page.query_selector("h1.ytd-video-primary-info-renderer")
                    video_title = await title_elem.inner_text() if title_elem else "Unknown Video"
                except:
                    video_title = "Unknown Video"

                # Scroll down multiple times to load comments
                for _ in range(5):
                    await page.evaluate("window.scrollBy(0, 600)")
                    await asyncio.sleep(0.8)

                # Wait for comments with longer timeout
                try:
                    await page.wait_for_selector("ytd-comment-thread-renderer", timeout=20000)
                except:
                    print(f"    No comments loaded for: {video_title[:40]}...")
                    continue

                # Extra scroll to ensure comments are loaded
                await asyncio.sleep(1)

                # Extract comments
                comments = await page.query_selector_all("ytd-comment-thread-renderer")
                comments = comments[:10]

                for comment in comments:
                    if len(posts) >= max_posts:
                        break

                    try:
                        # Extract comment text
                        text_elem = await comment.query_selector("#content-text")
                        content = await text_elem.inner_text() if text_elem else ""

                        # Extract author
                        author_elem = await comment.query_selector("#author-text")
                        author_text = await author_elem.inner_text() if author_elem else ""
                        author = author_text.strip()

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

                await random_delay(config)

            except Exception as e:
                print(f"    Error scraping video: {e}")
                continue

    except Exception as e:
        print(f"    Error scraping YouTube for '{keyword}': {e}")

    return posts


async def scrape_hackernews(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape Hacker News search results using Algolia search (async).

    Returns list of post/comment dicts with title, content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    # Use Algolia-powered HN search
    search_url = f"https://hn.algolia.com/?q={encoded_keyword}"

    try:
        await page.goto(search_url, timeout=config["scraping"]["timeout"] * 1000)
        await random_delay(config)

        # Wait for results
        try:
            await page.wait_for_selector(".Story, .Comment", timeout=15000)
        except:
            print(f"    No Hacker News results for '{keyword}'")
            return posts

        # Extract stories and comments
        all_items = await page.query_selector_all(".Story, .Comment")
        items = all_items[:max_posts]

        for item in items:
            if len(posts) >= max_posts:
                break

            try:
                # Check if it's a story or comment
                item_class = await item.get_attribute("class") or ""
                is_story = "Story" in item_class

                if is_story:
                    # Extract story title
                    title_elem = await item.query_selector(".Story_title a")
                    title = await title_elem.inner_text() if title_elem else ""

                    # Get HN discussion URL
                    link_elem = await item.query_selector(".Story_meta a[href*='item?id=']")
                    url = await link_elem.get_attribute("href") if link_elem else ""
                    if url and not url.startswith("http"):
                        url = "https://news.ycombinator.com/" + url

                    # Author
                    author_elem = await item.query_selector(".Story_meta a[href*='user?id=']")
                    author = await author_elem.inner_text() if author_elem else ""

                    content = title  # For stories, title is the main content

                else:
                    # It's a comment
                    text_elem = await item.query_selector(".Comment_text")
                    content = await text_elem.inner_text() if text_elem else ""
                    title = content[:100] + "..." if len(content) > 100 else content

                    # Get parent story link
                    link_elem = await item.query_selector("a[href*='item?id=']")
                    url = await link_elem.get_attribute("href") if link_elem else ""
                    if url and not url.startswith("http"):
                        url = "https://news.ycombinator.com/" + url

                    # Author
                    author_elem = await item.query_selector("a[href*='user?id=']")
                    author = await author_elem.inner_text() if author_elem else ""

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


async def scrape_quora(page: Page, keyword: str, max_posts: int, config: dict) -> list:
    """
    Scrape Quora search results for a keyword (async).

    Returns list of question/answer dicts with title, content, url, author.
    """
    posts = []
    encoded_keyword = quote_plus(keyword)
    search_url = f"https://www.quora.com/search?q={encoded_keyword}"

    try:
        await page.goto(search_url, timeout=config["scraping"]["timeout"] * 1000)
        await random_delay(config, multiplier=1.5)  # Quora is slow

        # Wait for results - Quora uses dynamic loading
        try:
            await page.wait_for_selector("[class*='qu-borderBottom']", timeout=20000)
        except:
            print(f"    No Quora results for '{keyword}'")
            return posts

        # Scroll to load more content
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(1)

        # Extract questions/answers - Quora's structure is complex
        # Look for question links and their preview text
        all_items = await page.query_selector_all("[class*='qu-borderBottom']")
        items = all_items[:max_posts * 2]

        seen_urls = set()
        for item in items:
            if len(posts) >= max_posts:
                break

            try:
                # Find question link
                link_elem = await item.query_selector("a[href*='/']")
                if not link_elem:
                    continue

                url = await link_elem.get_attribute("href") or ""
                if not url or url in seen_urls:
                    continue
                if not url.startswith("http"):
                    url = "https://www.quora.com" + url

                # Skip non-question URLs
                if "/profile/" in url or "/topic/" in url:
                    continue

                seen_urls.add(url)

                # Get question text
                title = (await link_elem.inner_text()).strip()

                # Try to get answer preview
                content_elem = await item.query_selector("[class*='q-text']")
                content = await content_elem.inner_text() if content_elem else title

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


# =============================================================================
# PAIN INTELLIGENCE SCRAPERS
# =============================================================================

async def scrape_google_autocomplete(page: Page, tool_name: str, config: dict) -> list:
    """
    Scrape Google autocomplete suggestions for pain-related queries.

    Uses seed queries from config like "why does {tool} not", "{tool} frustrating".
    Returns list of dicts with query, suggestion, and source.
    """
    suggestions = []
    pain_config = config.get("pain_intelligence", {}).get("google_autocomplete", {})

    if not pain_config.get("enabled", False):
        return suggestions

    seed_queries = pain_config.get("seed_queries", [])
    max_suggestions = pain_config.get("max_suggestions_per_query", 10)

    for seed in seed_queries:
        query = seed.replace("{tool}", tool_name)

        try:
            # Go to Google
            await page.goto("https://www.google.com", timeout=config["scraping"]["timeout"] * 1000)
            await random_delay(config)

            # Find search box and type query slowly to trigger autocomplete
            search_box = await page.query_selector("textarea[name='q'], input[name='q']")
            if not search_box:
                continue

            # Type slowly to trigger suggestions
            await search_box.click()
            await search_box.type(query, delay=100)
            await asyncio.sleep(1.5)  # Wait for suggestions to load

            # Extract autocomplete suggestions
            suggestion_elements = await page.query_selector_all(
                "ul[role='listbox'] li, div.OBMEnb ul li, div.aajZCb li"
            )

            for i, elem in enumerate(suggestion_elements[:max_suggestions]):
                try:
                    text = await elem.inner_text()
                    text = text.strip()

                    if text and len(text) > 5 and text.lower() != query.lower():
                        suggestions.append({
                            "query": query,
                            "suggestion": text,
                            "position": i + 1,
                            "source": "google_autocomplete",
                            "tool": tool_name
                        })
                except:
                    continue

            await random_delay(config, multiplier=0.5)

        except Exception as e:
            print(f"    Autocomplete error for '{query}': {e}")
            continue

    return suggestions


async def scrape_google_paa(page: Page, tool_name: str, config: dict) -> list:
    """
    Scrape Google "People Also Ask" questions for a tool.

    Clicks to expand PAA boxes to get more questions.
    Returns list of question dicts with question text and source.
    """
    questions = []
    pain_config = config.get("pain_intelligence", {}).get("google_paa", {})

    if not pain_config.get("enabled", False):
        return questions

    expand_count = pain_config.get("expand_count", 3)

    # Pain-focused search queries
    search_queries = [
        f"{tool_name} problems",
        f"{tool_name} not working",
        f"why is {tool_name} so slow",
        f"{tool_name} issues"
    ]

    for search_query in search_queries:
        try:
            encoded_query = quote_plus(search_query)
            await page.goto(
                f"https://www.google.com/search?q={encoded_query}",
                timeout=config["scraping"]["timeout"] * 1000
            )
            await random_delay(config)

            # Look for PAA container
            paa_container = await page.query_selector("div[data-sgrd], div.related-question-pair")
            if not paa_container:
                continue

            seen_questions = set()

            # Click to expand PAA boxes multiple times
            for _ in range(expand_count + 1):
                # Find PAA items
                paa_items = await page.query_selector_all(
                    "div[data-sgrd] div[role='button'], div.related-question-pair"
                )

                for item in paa_items:
                    try:
                        # Get question text
                        question_text = await item.inner_text()
                        question_text = question_text.strip().split("\n")[0]  # First line only

                        if question_text and len(question_text) > 10 and question_text not in seen_questions:
                            seen_questions.add(question_text)
                            questions.append({
                                "query": search_query,
                                "question": question_text,
                                "source": "google_paa",
                                "tool": tool_name
                            })

                            # Click to expand and get more questions
                            try:
                                await item.click()
                                await asyncio.sleep(0.8)
                            except:
                                pass
                    except:
                        continue

            await random_delay(config)

        except Exception as e:
            print(f"    PAA error for '{search_query}': {e}")
            continue

    return questions


async def scrape_g2_reviews(page: Page, tool_config: dict, config: dict) -> list:
    """
    Scrape G2.com reviews (1-3 stars only) for a tool.

    Focuses on the "Cons" section of reviews.
    Returns list of review dicts with reviewer info and pain content.
    """
    reviews = []
    tool_name = tool_config.get("name", "")
    g2_slug = tool_config.get("g2_slug", "")

    if not g2_slug:
        return reviews

    max_stars = config.get("pain_intelligence", {}).get("tool_reviews", {}).get("max_stars", 3)

    # Filter URLs for 1-3 star reviews
    star_filters = ["one", "two", "three"][:max_stars]

    for star_filter in star_filters:
        try:
            url = f"https://www.g2.com/products/{g2_slug}/reviews?filters%5Bstar_rating%5D={star_filter}"
            await page.goto(url, timeout=config["scraping"]["timeout"] * 1000)
            await random_delay(config, multiplier=1.5)

            # Wait for reviews to load
            try:
                await page.wait_for_selector("div.paper, div[itemprop='review']", timeout=15000)
            except:
                continue

            # Extract reviews
            review_elements = await page.query_selector_all("div.paper, div[itemprop='review']")

            for review_elem in review_elements[:10]:
                try:
                    # Extract reviewer role/title
                    role_elem = await review_elem.query_selector(
                        "div[class*='reviewer-job-title'], span[itemprop='jobTitle']"
                    )
                    role = await role_elem.inner_text() if role_elem else ""

                    # Extract company size
                    company_elem = await review_elem.query_selector("div[class*='company-size']")
                    company_size = await company_elem.inner_text() if company_elem else ""

                    # Extract "What do you dislike?" / Cons section
                    cons_elem = await review_elem.query_selector(
                        "div[class*='dislike'], div:has-text('What do you dislike') + div"
                    )
                    cons_text = await cons_elem.inner_text() if cons_elem else ""

                    # Also get the main review text as fallback
                    if not cons_text:
                        review_text_elem = await review_elem.query_selector(
                            "div[itemprop='reviewBody'], div[class*='review-body']"
                        )
                        cons_text = await review_text_elem.inner_text() if review_text_elem else ""

                    # Extract star rating
                    stars_elem = await review_elem.query_selector("span[class*='star']")
                    stars_text = await stars_elem.get_attribute("class") if stars_elem else ""
                    stars = 1 if "one" in stars_text else 2 if "two" in stars_text else 3

                    if cons_text and len(cons_text) > 20:
                        reviews.append({
                            "tool": tool_name,
                            "platform": "g2",
                            "star_rating": stars,
                            "reviewer_role": role.strip()[:200] if role else None,
                            "company_size": company_size.strip()[:100] if company_size else None,
                            "cons_text": cons_text.strip()[:3000],
                            "source_url": url
                        })

                except Exception as e:
                    continue

            await random_delay(config)

        except Exception as e:
            print(f"    G2 error for {tool_name} ({star_filter} star): {e}")
            continue

    return reviews


async def scrape_capterra_reviews(page: Page, tool_config: dict, config: dict) -> list:
    """
    Scrape Capterra reviews (1-3 stars only) for a tool.

    Focuses on "Cons" section.
    Returns list of review dicts with reviewer info and pain content.
    """
    reviews = []
    tool_name = tool_config.get("name", "")
    capterra_id = tool_config.get("capterra_id", "")

    if not capterra_id:
        return reviews

    max_stars = config.get("pain_intelligence", {}).get("tool_reviews", {}).get("max_stars", 3)

    try:
        # Capterra review page with rating filter
        url = f"https://www.capterra.com/p/{capterra_id}/reviews/?rating=1-{max_stars}"
        await page.goto(url, timeout=config["scraping"]["timeout"] * 1000)
        await random_delay(config, multiplier=1.5)

        # Wait for reviews
        try:
            await page.wait_for_selector("div[class*='review-card'], div[data-testid='review']", timeout=15000)
        except:
            return reviews

        # Scroll to load more reviews
        for _ in range(2):
            await page.evaluate("window.scrollBy(0, 1000)")
            await asyncio.sleep(1)

        # Extract reviews
        review_elements = await page.query_selector_all(
            "div[class*='review-card'], div[data-testid='review']"
        )

        for review_elem in review_elements[:15]:
            try:
                # Reviewer info
                role_elem = await review_elem.query_selector("span[class*='reviewer-job']")
                role = await role_elem.inner_text() if role_elem else ""

                industry_elem = await review_elem.query_selector("span[class*='industry']")
                industry = await industry_elem.inner_text() if industry_elem else ""

                # Rating
                rating_elem = await review_elem.query_selector("div[class*='rating'] span, span[class*='overall-rating']")
                rating_text = await rating_elem.inner_text() if rating_elem else "0"
                try:
                    stars = int(float(rating_text.replace("/5", "").strip()))
                except:
                    stars = 0

                # Skip if rating too high
                if stars > max_stars:
                    continue

                # Cons section
                cons_elem = await review_elem.query_selector(
                    "div[class*='cons'], div:has-text('Cons:') + div, div:has-text('CONS') + div"
                )
                cons_text = await cons_elem.inner_text() if cons_elem else ""

                if cons_text and len(cons_text) > 20:
                    reviews.append({
                        "tool": tool_name,
                        "platform": "capterra",
                        "star_rating": stars,
                        "reviewer_role": role.strip()[:200] if role else None,
                        "reviewer_industry": industry.strip()[:100] if industry else None,
                        "cons_text": cons_text.strip()[:3000],
                        "source_url": url
                    })

            except Exception as e:
                continue

    except Exception as e:
        print(f"    Capterra error for {tool_name}: {e}")

    return reviews


async def scrape_zapier_community(page: Page, config: dict) -> list:
    """
    Scrape Zapier community forums for troubleshooting posts and complaints.

    Focuses on Troubleshooting and Bugs & Issues categories.
    Returns list of post dicts with title, content, author.
    """
    posts = []
    community_config = config.get("pain_intelligence", {}).get("communities", {}).get("zapier", {})

    if not community_config.get("enabled", False):
        return posts

    urls = community_config.get("urls", [
        "https://community.zapier.com/c/troubleshooting/5",
        "https://community.zapier.com/c/bugs-and-issues/9"
    ])

    for forum_url in urls:
        try:
            await page.goto(forum_url, timeout=config["scraping"]["timeout"] * 1000)
            await random_delay(config)

            # Wait for posts to load
            try:
                await page.wait_for_selector("tr.topic-list-item, div.topic-list-item", timeout=15000)
            except:
                continue

            # Extract topic links
            topic_elements = await page.query_selector_all("tr.topic-list-item a.title, div.topic-list-item a.title")
            topic_links = []

            for elem in topic_elements[:15]:
                href = await elem.get_attribute("href")
                title = await elem.inner_text()
                if href:
                    full_url = href if href.startswith("http") else f"https://community.zapier.com{href}"
                    topic_links.append({"url": full_url, "title": title.strip()})

            # Visit each topic and extract content
            for topic in topic_links[:10]:
                try:
                    await page.goto(topic["url"], timeout=config["scraping"]["timeout"] * 1000)
                    await random_delay(config, multiplier=0.7)

                    # Get the main post content
                    content_elem = await page.query_selector("div.post:first-of-type div.cooked, div.topic-body div.cooked")
                    content = await content_elem.inner_text() if content_elem else ""

                    # Get author
                    author_elem = await page.query_selector("span.creator a, a.username")
                    author = await author_elem.inner_text() if author_elem else ""

                    if content and len(content) > 30:
                        posts.append({
                            "title": topic["title"][:200],
                            "content": content.strip()[:3000],
                            "url": topic["url"],
                            "author": author.strip(),
                            "source": "zapier_community",
                            "tool": "zapier"
                        })

                except Exception as e:
                    continue

        except Exception as e:
            print(f"    Zapier community error: {e}")
            continue

    return posts


async def scrape_make_community(page: Page, config: dict) -> list:
    """
    Scrape Make.com community forums for complaints and issues.

    Returns list of post dicts with title, content, author.
    """
    posts = []
    community_config = config.get("pain_intelligence", {}).get("communities", {}).get("make", {})

    if not community_config.get("enabled", False):
        return posts

    urls = community_config.get("urls", ["https://www.make.com/en/community"])

    for forum_url in urls:
        try:
            await page.goto(forum_url, timeout=config["scraping"]["timeout"] * 1000)
            await random_delay(config, multiplier=1.5)

            # Make uses a custom forum, look for topic listings
            try:
                await page.wait_for_selector("a[href*='/t/'], div.topic-title", timeout=15000)
            except:
                # Try alternative selectors
                pass

            # Scroll to load content
            for _ in range(2):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(0.8)

            # Find topic links - Make.com forum structure
            topic_elements = await page.query_selector_all("a[href*='/t/'], a.topic-link")
            topic_links = []

            for elem in topic_elements[:20]:
                href = await elem.get_attribute("href")
                title = await elem.inner_text()
                if href and "/t/" in href and len(title) > 5:
                    full_url = href if href.startswith("http") else f"https://www.make.com{href}"
                    if full_url not in [t["url"] for t in topic_links]:
                        topic_links.append({"url": full_url, "title": title.strip()})

            # Visit topics
            for topic in topic_links[:10]:
                try:
                    await page.goto(topic["url"], timeout=config["scraping"]["timeout"] * 1000)
                    await random_delay(config, multiplier=0.7)

                    # Get post content
                    content_elem = await page.query_selector("div.post-content, article.post div.cooked")
                    content = await content_elem.inner_text() if content_elem else ""

                    author_elem = await page.query_selector("span.username, a.author")
                    author = await author_elem.inner_text() if author_elem else ""

                    if content and len(content) > 30:
                        posts.append({
                            "title": topic["title"][:200],
                            "content": content.strip()[:3000],
                            "url": topic["url"],
                            "author": author.strip(),
                            "source": "make_community",
                            "tool": "make"
                        })

                except Exception as e:
                    continue

        except Exception as e:
            print(f"    Make community error: {e}")

    return posts


async def scrape_hubspot_community(page: Page, config: dict) -> list:
    """
    Scrape HubSpot community forums for CRM-related complaints.

    Returns list of post dicts with title, content, author.
    """
    posts = []
    community_config = config.get("pain_intelligence", {}).get("communities", {}).get("hubspot", {})

    if not community_config.get("enabled", False):
        return posts

    urls = community_config.get("urls", ["https://community.hubspot.com/t5/CRM/ct-p/crm"])

    for forum_url in urls:
        try:
            await page.goto(forum_url, timeout=config["scraping"]["timeout"] * 1000)
            await random_delay(config, multiplier=1.5)

            # HubSpot uses Khoros/Lithium forum software
            try:
                await page.wait_for_selector("a.page-link, h2.message-subject a", timeout=15000)
            except:
                continue

            # Find topic links
            topic_elements = await page.query_selector_all("h2.message-subject a, a.page-link")
            topic_links = []

            for elem in topic_elements[:20]:
                href = await elem.get_attribute("href")
                title = await elem.inner_text()
                if href and len(title) > 5:
                    full_url = href if href.startswith("http") else f"https://community.hubspot.com{href}"
                    topic_links.append({"url": full_url, "title": title.strip()})

            # Visit topics
            for topic in topic_links[:10]:
                try:
                    await page.goto(topic["url"], timeout=config["scraping"]["timeout"] * 1000)
                    await random_delay(config, multiplier=0.7)

                    # Get post content - Khoros/Lithium structure
                    content_elem = await page.query_selector("div.lia-message-body-content, div.message-body")
                    content = await content_elem.inner_text() if content_elem else ""

                    author_elem = await page.query_selector("a.lia-user-name-link, span.author-name")
                    author = await author_elem.inner_text() if author_elem else ""

                    if content and len(content) > 30:
                        posts.append({
                            "title": topic["title"][:200],
                            "content": content.strip()[:3000],
                            "url": topic["url"],
                            "author": author.strip(),
                            "source": "hubspot_community",
                            "tool": "hubspot"
                        })

                except Exception as e:
                    continue

        except Exception as e:
            print(f"    HubSpot community error: {e}")

    return posts


async def scrape_linkedin_jobs(page: Page, config: dict) -> list:
    """
    Scrape LinkedIn job postings to identify manual task language.

    Looks for phrases like "fast-paced", "data entry", "manually".
    Returns list of job signal dicts.
    """
    jobs = []
    job_config = config.get("pain_intelligence", {}).get("job_scrapers", {})

    if not job_config.get("enabled", False):
        return jobs

    if "linkedin" not in job_config.get("platforms", []):
        return jobs

    job_titles = job_config.get("job_titles", [])
    max_jobs = job_config.get("max_jobs_per_title", 20)
    manual_signals = job_config.get("manual_task_signals", [])

    for job_title in job_titles[:5]:  # Limit to prevent rate limiting
        try:
            encoded_title = quote_plus(job_title)
            url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_title}"

            await page.goto(url, timeout=config["scraping"]["timeout"] * 1000)
            await random_delay(config, multiplier=2)  # LinkedIn is aggressive with rate limits

            # Scroll to load more jobs
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(1)

            # Find job cards
            job_cards = await page.query_selector_all(
                "div.base-card, li.jobs-search-results__list-item"
            )

            for card in job_cards[:max_jobs]:
                try:
                    # Get job link
                    link_elem = await card.query_selector("a.base-card__full-link, a[href*='/jobs/view']")
                    if not link_elem:
                        continue

                    job_url = await link_elem.get_attribute("href")

                    # Get title
                    title_elem = await card.query_selector("h3.base-search-card__title, span.job-card-list__title")
                    title_text = await title_elem.inner_text() if title_elem else ""

                    # Get company
                    company_elem = await card.query_selector("h4.base-search-card__subtitle, a.job-card-container__company-name")
                    company = await company_elem.inner_text() if company_elem else ""

                    # Click to get description (or fetch page)
                    try:
                        await link_elem.click()
                        await asyncio.sleep(1.5)

                        desc_elem = await page.query_selector(
                            "div.show-more-less-html__markup, div.jobs-description-content"
                        )
                        description = await desc_elem.inner_text() if desc_elem else ""
                    except:
                        description = ""

                    if description:
                        # Check for manual task signals
                        desc_lower = description.lower()
                        detected_signals = [s for s in manual_signals if s.lower() in desc_lower]

                        if detected_signals:
                            jobs.append({
                                "platform": "linkedin",
                                "job_title": title_text.strip()[:200],
                                "company": company.strip()[:200],
                                "description_snippet": description[:2000],
                                "detected_signals": json.dumps(detected_signals),
                                "source_url": job_url
                            })

                except Exception as e:
                    continue

            await random_delay(config, multiplier=1.5)

        except Exception as e:
            print(f"    LinkedIn jobs error for '{job_title}': {e}")

    return jobs


async def scrape_indeed_jobs(page: Page, config: dict) -> list:
    """
    Scrape Indeed job postings to identify manual task language.

    Returns list of job signal dicts.
    """
    jobs = []
    job_config = config.get("pain_intelligence", {}).get("job_scrapers", {})

    if not job_config.get("enabled", False):
        return jobs

    if "indeed" not in job_config.get("platforms", []):
        return jobs

    job_titles = job_config.get("job_titles", [])
    max_jobs = job_config.get("max_jobs_per_title", 20)
    manual_signals = job_config.get("manual_task_signals", [])

    for job_title in job_titles[:5]:
        try:
            encoded_title = quote_plus(job_title)
            url = f"https://www.indeed.com/jobs?q={encoded_title}"

            await page.goto(url, timeout=config["scraping"]["timeout"] * 1000)
            await random_delay(config, multiplier=1.5)

            # Wait for job cards
            try:
                await page.wait_for_selector("div.job_seen_beacon, div.jobsearch-ResultsList", timeout=15000)
            except:
                continue

            # Find job cards
            job_cards = await page.query_selector_all("div.job_seen_beacon, li.css-1ac2h1q")

            for card in job_cards[:max_jobs]:
                try:
                    # Title and link
                    title_elem = await card.query_selector("h2.jobTitle a, a.jcs-JobTitle")
                    if not title_elem:
                        continue

                    title_text = await title_elem.inner_text()
                    job_url = await title_elem.get_attribute("href")
                    if job_url and not job_url.startswith("http"):
                        job_url = f"https://www.indeed.com{job_url}"

                    # Company
                    company_elem = await card.query_selector("span.companyName, span[data-testid='company-name']")
                    company = await company_elem.inner_text() if company_elem else ""

                    # Snippet/description preview
                    snippet_elem = await card.query_selector("div.job-snippet, ul.css-9446fg")
                    snippet = await snippet_elem.inner_text() if snippet_elem else ""

                    # Click to expand for full description
                    try:
                        await title_elem.click()
                        await asyncio.sleep(1.5)

                        desc_elem = await page.query_selector("div#jobDescriptionText, div.jobsearch-jobDescriptionText")
                        full_description = await desc_elem.inner_text() if desc_elem else snippet
                    except:
                        full_description = snippet

                    if full_description:
                        desc_lower = full_description.lower()
                        detected_signals = [s for s in manual_signals if s.lower() in desc_lower]

                        if detected_signals:
                            jobs.append({
                                "platform": "indeed",
                                "job_title": title_text.strip()[:200],
                                "company": company.strip()[:200],
                                "description_snippet": full_description[:2000],
                                "detected_signals": json.dumps(detected_signals),
                                "source_url": job_url
                            })

                except Exception as e:
                    continue

            await random_delay(config)

        except Exception as e:
            print(f"    Indeed jobs error for '{job_title}': {e}")

    return jobs


# =============================================================================
# PAIN INTELLIGENCE SCRAPER ORCHESTRATION
# =============================================================================

async def run_pain_scrapers_async(scrapers: list = None) -> dict:
    """
    Run Pain Intelligence scrapers.

    Scrapes Google autocomplete/PAA, tool reviews, community forums, and job postings.
    Saves data to search_signals, tool_reviews, and job_signals tables.

    Args:
        scrapers: List of scraper names to run (None = all enabled)
    """
    config = load_config()
    database.init_database()

    if scrapers is None:
        scrapers = PAIN_SCRAPERS

    stats = {
        "autocomplete_suggestions": 0,
        "paa_questions": 0,
        "reviews_collected": 0,
        "community_posts": 0,
        "job_signals": 0,
        "errors": 0
    }

    pain_config = config.get("pain_intelligence", {})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = None
        page = None

        try:
            # Get tools to scrape from config
            tools = pain_config.get("tool_reviews", {}).get("tools", [])
            tool_names = [t["name"] for t in tools]

            # Create browser context
            context = await browser.new_context(
                user_agent=get_random_user_agent(config),
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()

            # --- Google Autocomplete ---
            if "google_autocomplete" in scrapers:
                print("\n[Google Autocomplete]")
                for tool_name in tool_names:
                    print(f"  Tool: {tool_name}")
                    try:
                        suggestions = await with_retry(scrape_google_autocomplete, page, tool_name, config)
                        for s in suggestions:
                            database.add_search_signal(
                                signal_type="autocomplete",
                                query=s["query"],
                                result_text=s["suggestion"],
                                position=s.get("position"),
                                tool=s.get("tool"),
                                source_url="google.com"
                            )
                            stats["autocomplete_suggestions"] += 1
                        print(f"    Saved {len(suggestions)} suggestions")
                    except Exception as e:
                        print(f"    Error: {e}")
                        stats["errors"] += 1

            # --- Google PAA ---
            if "google_paa" in scrapers:
                print("\n[Google People Also Ask]")
                for tool_name in tool_names:
                    print(f"  Tool: {tool_name}")
                    try:
                        questions = await with_retry(scrape_google_paa, page, tool_name, config)
                        for q in questions:
                            database.add_search_signal(
                                signal_type="paa",
                                query=q["query"],
                                result_text=q["question"],
                                tool=q.get("tool"),
                                source_url="google.com"
                            )
                            stats["paa_questions"] += 1
                        print(f"    Saved {len(questions)} PAA questions")
                    except Exception as e:
                        print(f"    Error: {e}")
                        stats["errors"] += 1

            # --- G2 Reviews ---
            if "g2_reviews" in scrapers:
                print("\n[G2 Reviews]")
                for tool_config_item in tools:
                    if tool_config_item.get("g2_slug"):
                        print(f"  Tool: {tool_config_item['name']}")
                        try:
                            reviews = await with_retry(scrape_g2_reviews, page, tool_config_item, config)
                            for r in reviews:
                                database.add_tool_review(
                                    tool=r["tool"],
                                    platform=r["platform"],
                                    star_rating=r["star_rating"],
                                    reviewer_role=r.get("reviewer_role"),
                                    cons_text=r["cons_text"],
                                    source_url=r["source_url"]
                                )
                                stats["reviews_collected"] += 1
                            print(f"    Saved {len(reviews)} reviews")
                        except Exception as e:
                            print(f"    Error: {e}")
                            stats["errors"] += 1

            # --- Capterra Reviews ---
            if "capterra_reviews" in scrapers:
                print("\n[Capterra Reviews]")
                for tool_config_item in tools:
                    if tool_config_item.get("capterra_id"):
                        print(f"  Tool: {tool_config_item['name']}")
                        try:
                            reviews = await with_retry(scrape_capterra_reviews, page, tool_config_item, config)
                            for r in reviews:
                                database.add_tool_review(
                                    tool=r["tool"],
                                    platform=r["platform"],
                                    star_rating=r["star_rating"],
                                    reviewer_role=r.get("reviewer_role"),
                                    reviewer_industry=r.get("reviewer_industry"),
                                    cons_text=r["cons_text"],
                                    source_url=r["source_url"]
                                )
                                stats["reviews_collected"] += 1
                            print(f"    Saved {len(reviews)} reviews")
                        except Exception as e:
                            print(f"    Error: {e}")
                            stats["errors"] += 1

            # --- Community Forums ---
            if "zapier_community" in scrapers:
                print("\n[Zapier Community]")
                try:
                    posts = await with_retry(scrape_zapier_community, page, config)
                    for post in posts:
                        # Add to posts table with source marking
                        database.add_post(
                            topic_id=1,  # Will be linked to topic later
                            keyword_id=None,
                            source=post["source"],
                            url=post["url"],
                            title=post["title"],
                            content=post["content"],
                            author=post.get("author", "")
                        )
                        stats["community_posts"] += 1
                    print(f"  Saved {len(posts)} posts")
                except Exception as e:
                    print(f"  Error: {e}")
                    stats["errors"] += 1

            if "make_community" in scrapers:
                print("\n[Make Community]")
                try:
                    posts = await with_retry(scrape_make_community, page, config)
                    for post in posts:
                        database.add_post(
                            topic_id=1,
                            keyword_id=None,
                            source=post["source"],
                            url=post["url"],
                            title=post["title"],
                            content=post["content"],
                            author=post.get("author", "")
                        )
                        stats["community_posts"] += 1
                    print(f"  Saved {len(posts)} posts")
                except Exception as e:
                    print(f"  Error: {e}")
                    stats["errors"] += 1

            if "hubspot_community" in scrapers:
                print("\n[HubSpot Community]")
                try:
                    posts = await with_retry(scrape_hubspot_community, page, config)
                    for post in posts:
                        database.add_post(
                            topic_id=1,
                            keyword_id=None,
                            source=post["source"],
                            url=post["url"],
                            title=post["title"],
                            content=post["content"],
                            author=post.get("author", "")
                        )
                        stats["community_posts"] += 1
                    print(f"  Saved {len(posts)} posts")
                except Exception as e:
                    print(f"  Error: {e}")
                    stats["errors"] += 1

            # --- Job Scrapers ---
            if "linkedin_jobs" in scrapers:
                print("\n[LinkedIn Jobs]")
                try:
                    jobs = await with_retry(scrape_linkedin_jobs, page, config)
                    for job in jobs:
                        database.add_job_signal(
                            platform=job["platform"],
                            job_title=job["job_title"],
                            company=job.get("company"),
                            description_snippet=job["description_snippet"],
                            detected_signals=job["detected_signals"],
                            source_url=job["source_url"]
                        )
                        stats["job_signals"] += 1
                    print(f"  Saved {len(jobs)} job signals")
                except Exception as e:
                    print(f"  Error: {e}")
                    stats["errors"] += 1

            if "indeed_jobs" in scrapers:
                print("\n[Indeed Jobs]")
                try:
                    jobs = await with_retry(scrape_indeed_jobs, page, config)
                    for job in jobs:
                        database.add_job_signal(
                            platform=job["platform"],
                            job_title=job["job_title"],
                            company=job.get("company"),
                            description_snippet=job["description_snippet"],
                            detected_signals=job["detected_signals"],
                            source_url=job["source_url"]
                        )
                        stats["job_signals"] += 1
                    print(f"  Saved {len(jobs)} job signals")
                except Exception as e:
                    print(f"  Error: {e}")
                    stats["errors"] += 1

        finally:
            # Ensure browser resources are always cleaned up
            if context:
                await context.close()
            await browser.close()

    # Print summary
    print("\n" + "=" * 50)
    print("Pain Intelligence Scraping Complete")
    print("=" * 50)
    print(f"  Autocomplete suggestions: {stats['autocomplete_suggestions']}")
    print(f"  PAA questions: {stats['paa_questions']}")
    print(f"  Tool reviews: {stats['reviews_collected']}")
    print(f"  Community posts: {stats['community_posts']}")
    print(f"  Job signals: {stats['job_signals']}")
    print(f"  Errors: {stats['errors']}")

    return stats


def run_pain_scrapers(scrapers: list = None) -> dict:
    """Sync wrapper for run_pain_scrapers_async."""
    return asyncio.run(run_pain_scrapers_async(scrapers))


async def scrape_keyword_async(
    browser: Browser,
    keyword: str,
    topic_id: int,
    keyword_id: int,
    topic_keywords: list,
    max_posts: int,
    platforms: list,
    config: dict
) -> dict:
    """
    Scrape all platforms for a single keyword concurrently.

    Creates separate browser contexts for each platform to enable parallel scraping.
    Returns stats dict with posts_found, posts_saved, duplicates_skipped.
    """
    stats = {"posts_found": 0, "posts_saved": 0, "duplicates_skipped": 0, "filtered": 0}

    def save_if_complaint(post, keyword, topic_keywords):
        """Save post only if content is a complaint (not casual mention)."""
        content = f"{post['title']} {post['content']}"
        is_comp, complaint_score = is_complaint(content, keyword, topic_keywords)
        if not is_comp:
            return "skipped"
        post_id = database.add_post(
            topic_id=topic_id,
            keyword_id=keyword_id,
            source=post["source"],
            url=post["url"],
            title=post["title"],
            content=post["content"],
            author=post["author"],
            complaint_score=complaint_score
        )
        return "saved" if post_id else "duplicate"

    # Create scraping tasks for enabled platforms
    async def scrape_platform(platform: str) -> tuple:
        """Scrape a single platform and return (platform, posts)."""
        context = await browser.new_context(
            user_agent=get_random_user_agent(config),
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        try:
            if platform == "reddit":
                posts = await with_retry(scrape_reddit, page, keyword, max_posts, config)
            elif platform == "youtube":
                posts = await with_retry(scrape_youtube, page, keyword, max_posts // 2, config)
            elif platform == "hackernews":
                posts = await with_retry(scrape_hackernews, page, keyword, max_posts, config)
            elif platform == "quora":
                posts = await with_retry(scrape_quora, page, keyword, max_posts, config)
            else:
                posts = []
            return (platform, posts)
        finally:
            await context.close()

    # Run all platform scrapers concurrently
    tasks = [scrape_platform(p) for p in platforms]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results from all platforms
    for result in results:
        if isinstance(result, Exception):
            print(f"    Platform error: {result}")
            continue

        platform, posts = result
        saved, filtered = 0, 0

        for post in posts:
            result_type = save_if_complaint(post, keyword, topic_keywords)
            if result_type == "saved":
                stats["posts_saved"] += 1
                saved += 1
            elif result_type == "duplicate":
                stats["duplicates_skipped"] += 1
            else:
                filtered += 1
            stats["posts_found"] += 1

        stats["filtered"] += filtered
        print(f"    {platform.capitalize()}: found {len(posts)}, saved {saved}, filtered {filtered}")

    return stats


async def run_scraper_async(topic_name: str = None, platforms: list = None) -> dict:
    """
    Async scraper entry point.

    Scrapes specified platforms for a topic concurrently.
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

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        try:
            for topic in topics_to_scrape:
                print(f"\nScraping topic: {topic['name']}")
                print(f"Platforms: {', '.join(platforms)} (concurrent)")
                topic_id = database.get_or_create_topic(topic["name"])
                max_posts = topic.get("max_posts_per_keyword", 50)
                topic_keywords = topic["keywords"]

                for keyword in topic_keywords:
                    print(f"  Keyword: '{keyword}'")
                    keyword_id = database.add_keyword(topic_id, keyword, is_seed=True)

                    # Scrape all platforms concurrently for this keyword
                    keyword_stats = await scrape_keyword_async(
                        browser, keyword, topic_id, keyword_id,
                        topic_keywords, max_posts, platforms, config
                    )

                    stats["posts_found"] += keyword_stats["posts_found"]
                    stats["posts_saved"] += keyword_stats["posts_saved"]
                    stats["duplicates_skipped"] += keyword_stats["duplicates_skipped"]
                    stats["keywords_processed"] += 1

                stats["topics_scraped"] += 1
        finally:
            # Ensure browser is always closed to prevent zombie processes
            await browser.close()

    print(f"\nScraping complete!")
    print(f"  Topics scraped: {stats['topics_scraped']}")
    print(f"  Keywords processed: {stats['keywords_processed']}")
    print(f"  Posts found: {stats['posts_found']}")
    print(f"  Posts saved: {stats['posts_saved']}")
    print(f"  Duplicates skipped: {stats['duplicates_skipped']}")

    return stats


def run_scraper(topic_name: str = None, platforms: list = None) -> dict:
    """
    Sync wrapper for run_scraper_async.

    Main scraper entry point for CLI and external callers.
    """
    return asyncio.run(run_scraper_async(topic_name, platforms))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape platforms for research")
    parser.add_argument("--topic", type=str, help="Topic name to scrape (from config.yaml)")
    parser.add_argument("--platforms", type=str, help="Comma-separated platforms: reddit,youtube,hackernews,quora")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["standard", "pain"],
        default="standard",
        help="Scraping mode: 'standard' for Reddit/YouTube/etc, 'pain' for Pain Intelligence scrapers"
    )
    parser.add_argument(
        "--pain-scrapers",
        type=str,
        help="Comma-separated pain scrapers: google_autocomplete,google_paa,g2_reviews,capterra_reviews,zapier_community,make_community,hubspot_community,linkedin_jobs,indeed_jobs"
    )
    args = parser.parse_args()

    if args.mode == "pain":
        # Run Pain Intelligence scrapers
        scrapers = None
        if args.pain_scrapers:
            scrapers = [s.strip() for s in args.pain_scrapers.split(",")]
        run_pain_scrapers(scrapers)
    else:
        # Run standard platform scrapers
        platforms = None
        if args.platforms:
            platforms = [p.strip() for p in args.platforms.split(",")]
        run_scraper(args.topic, platforms)
