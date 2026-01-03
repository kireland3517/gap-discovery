"""
Google Autocomplete scraper plugin.

Scrapes Google search autocomplete suggestions.
"""

import logging
from typing import Optional

from plugins.base import ScraperPlugin, ScraperConfig, ScraperResult, ScraperType

logger = logging.getLogger(__name__)


class GoogleAutocompleteScraperPlugin(ScraperPlugin):
    """
    Google Autocomplete scraper plugin.

    Wraps the existing Google autocomplete scraping functionality from scrape.py.
    """

    def __init__(self):
        super().__init__()
        self._browser = None

    @property
    def name(self) -> str:
        return "google_autocomplete"

    @property
    def display_name(self) -> str:
        return "Google Autocomplete"

    @property
    def platform(self) -> str:
        return "google.com"

    @property
    def scraper_type(self) -> ScraperType:
        return ScraperType.SEARCH

    def can_handle(self, source_type: str) -> bool:
        return source_type.lower() in ["google_autocomplete", "autocomplete", "search"]

    async def initialize(self) -> None:
        """Initialize browser for scraping."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        logger.info("Google Autocomplete scraper: Browser initialized")

    async def cleanup(self) -> None:
        """Close browser resources."""
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
        logger.info("Google Autocomplete scraper: Browser closed")

    async def scrape(self, config: ScraperConfig) -> ScraperResult:
        """
        Scrape Google autocomplete suggestions.

        Uses the existing scrape_google_autocomplete function.
        """
        result = ScraperResult()

        try:
            # Import existing scraper function
            from scrape import scrape_google_autocomplete, load_config, get_random_user_agent

            yaml_config = load_config()

            # Get tools to query from config
            tools = config.get("tools", [])
            if not tools:
                # Use keywords or topic as tools
                tools = [{"name": k} for k in (config.keywords or [config.topic])]

            # Set up browser context
            context = await self._browser.new_context(
                user_agent=get_random_user_agent(yaml_config),
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()

            try:
                for tool_config in tools:
                    tool_name = tool_config.get("name", tool_config) if isinstance(tool_config, dict) else tool_config
                    logger.info(f"Google Autocomplete: Searching for '{tool_name}'")

                    try:
                        suggestions = await scrape_google_autocomplete(page, tool_name, yaml_config)

                        for suggestion in suggestions:
                            result.add_post({
                                "source": "google_autocomplete",
                                "signal_type": "autocomplete",
                                "query": suggestion.get("query", ""),
                                "suggestion": suggestion.get("suggestion", ""),
                                "content": suggestion.get("suggestion", ""),
                                "position": suggestion.get("position"),
                                "tool": suggestion.get("tool", tool_name),
                            })

                        logger.info(f"Google Autocomplete: Found {len(suggestions)} suggestions for '{tool_name}'")

                    except Exception as e:
                        error_msg = f"Error searching autocomplete for '{tool_name}': {e}"
                        logger.error(error_msg)
                        result.add_error(error_msg)

            finally:
                await context.close()

        except Exception as e:
            error_msg = f"Google Autocomplete scraper error: {e}"
            logger.exception(error_msg)
            result.add_error(error_msg)

        result.complete()
        logger.info(f"Google Autocomplete scraper: Collected {len(result.posts)} suggestions")
        return result
