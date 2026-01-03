"""
Reddit scraper plugin.

Scrapes Reddit posts and comments from relevant subreddits.
"""

import logging
from typing import Optional

from plugins.base import ScraperPlugin, ScraperConfig, ScraperResult, ScraperType

logger = logging.getLogger(__name__)


class RedditScraperPlugin(ScraperPlugin):
    """
    Reddit scraper plugin.

    Wraps the existing Reddit scraping functionality from scrape.py.
    """

    def __init__(self):
        super().__init__()
        self._browser = None
        self._page = None

    @property
    def name(self) -> str:
        return "reddit"

    @property
    def display_name(self) -> str:
        return "Reddit"

    @property
    def platform(self) -> str:
        return "reddit.com"

    @property
    def scraper_type(self) -> ScraperType:
        return ScraperType.SOCIAL

    def can_handle(self, source_type: str) -> bool:
        return source_type.lower() in ["reddit", "social", "forum"]

    async def initialize(self) -> None:
        """Initialize browser for scraping."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        logger.info("Reddit scraper: Browser initialized")

    async def cleanup(self) -> None:
        """Close browser resources."""
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
        logger.info("Reddit scraper: Browser closed")

    async def scrape(self, config: ScraperConfig) -> ScraperResult:
        """
        Scrape Reddit for relevant posts.

        Uses the existing scrape_reddit function.
        """
        result = ScraperResult()

        try:
            # Import existing scraper function
            from scrape import scrape_reddit, load_config, get_random_user_agent

            yaml_config = load_config()

            # Set up browser context
            context = await self._browser.new_context(
                user_agent=get_random_user_agent(yaml_config),
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()

            try:
                # Build search queries from config
                keywords = config.keywords or [config.topic]

                for keyword in keywords:
                    logger.info(f"Reddit: Searching for '{keyword}'")

                    try:
                        posts = await scrape_reddit(page, keyword, yaml_config)

                        for post in posts:
                            result.add_post({
                                "source": "reddit",
                                "url": post.get("url", ""),
                                "title": post.get("title", ""),
                                "content": post.get("content", ""),
                                "author": post.get("author", ""),
                                "upvotes": post.get("upvotes", 0),
                                "comments": post.get("comments", 0),
                                "subreddit": post.get("subreddit", ""),
                            })

                        logger.info(f"Reddit: Found {len(posts)} posts for '{keyword}'")

                    except Exception as e:
                        error_msg = f"Error searching '{keyword}': {e}"
                        logger.error(error_msg)
                        result.add_error(error_msg)

                        # Check for max results
                        if len(result.posts) >= config.max_results:
                            break

            finally:
                await context.close()

        except Exception as e:
            error_msg = f"Reddit scraper error: {e}"
            logger.exception(error_msg)
            result.add_error(error_msg)

        result.complete()
        logger.info(f"Reddit scraper: Collected {len(result.posts)} posts")
        return result
