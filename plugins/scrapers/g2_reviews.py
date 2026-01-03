"""
G2 Reviews scraper plugin.

Scrapes product reviews from G2.com.
"""

import logging
from typing import Optional

from plugins.base import ScraperPlugin, ScraperConfig, ScraperResult, ScraperType

logger = logging.getLogger(__name__)


class G2ReviewsScraperPlugin(ScraperPlugin):
    """
    G2 Reviews scraper plugin.

    Wraps the existing G2 scraping functionality from scrape.py.
    """

    def __init__(self):
        super().__init__()
        self._browser = None

    @property
    def name(self) -> str:
        return "g2_reviews"

    @property
    def display_name(self) -> str:
        return "G2 Reviews"

    @property
    def platform(self) -> str:
        return "g2.com"

    @property
    def scraper_type(self) -> ScraperType:
        return ScraperType.REVIEW

    def can_handle(self, source_type: str) -> bool:
        return source_type.lower() in ["g2", "g2_reviews", "review"]

    def validate_config(self, config: ScraperConfig) -> list[str]:
        """Validate that we have tools to scrape."""
        errors = super().validate_config(config)

        tools = config.get("tools", [])
        if not tools:
            errors.append("G2 scraper requires 'tools' configuration with g2_slug")

        return errors

    async def initialize(self) -> None:
        """Initialize browser for scraping."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        logger.info("G2 scraper: Browser initialized")

    async def cleanup(self) -> None:
        """Close browser resources."""
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
        logger.info("G2 scraper: Browser closed")

    async def scrape(self, config: ScraperConfig) -> ScraperResult:
        """
        Scrape G2 for product reviews.

        Uses the existing scrape_g2_reviews function.
        """
        result = ScraperResult()

        try:
            # Import existing scraper function
            from scrape import scrape_g2_reviews, load_config, get_random_user_agent

            yaml_config = load_config()

            # Get tools to scrape from config
            tools = config.get("tools", [])
            if not tools:
                # Try to get from yaml config
                pain_intel = yaml_config.get("pain_intelligence", {})
                tools = pain_intel.get("tool_reviews", {}).get("tools", [])

            # Set up browser context
            context = await self._browser.new_context(
                user_agent=get_random_user_agent(yaml_config),
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()

            try:
                for tool_config in tools:
                    if not tool_config.get("g2_slug"):
                        continue

                    tool_name = tool_config.get("name", "unknown")
                    logger.info(f"G2: Scraping reviews for '{tool_name}'")

                    try:
                        reviews = await scrape_g2_reviews(page, tool_config, yaml_config)

                        for review in reviews:
                            result.add_post({
                                "source": "g2",
                                "platform": "g2",
                                "tool": review.get("tool", tool_name),
                                "star_rating": review.get("star_rating"),
                                "reviewer_role": review.get("reviewer_role", ""),
                                "cons_text": review.get("cons_text", ""),
                                "content": review.get("cons_text", ""),
                                "source_url": review.get("source_url", ""),
                                "url": review.get("source_url", ""),
                            })

                        logger.info(f"G2: Found {len(reviews)} reviews for '{tool_name}'")

                    except Exception as e:
                        error_msg = f"Error scraping G2 for '{tool_name}': {e}"
                        logger.error(error_msg)
                        result.add_error(error_msg)

            finally:
                await context.close()

        except Exception as e:
            error_msg = f"G2 scraper error: {e}"
            logger.exception(error_msg)
            result.add_error(error_msg)

        result.complete()
        logger.info(f"G2 scraper: Collected {len(result.posts)} reviews")
        return result
