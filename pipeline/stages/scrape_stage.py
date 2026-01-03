"""
Scrape stage for the research pipeline.

Collects data from various platforms using Pain Intelligence scrapers.
"""

import asyncio
import logging
from typing import Optional

from ..base import PipelineStage, StageResult, StageStatus
from ..context import PipelineContext, ResearchPhase

logger = logging.getLogger(__name__)


class ScrapeStage(PipelineStage):
    """
    Pipeline stage that scrapes data from configured platforms.

    Wraps the existing run_pain_scrapers_async() function from scrape.py.
    """

    def __init__(self, scrapers: Optional[list] = None):
        """
        Initialize the scrape stage.

        Args:
            scrapers: Optional list of scraper names to run.
                     If None, uses all scrapers from config.
        """
        super().__init__(name="Scrape")
        self.scrapers = scrapers

    def validate_input(self, context: PipelineContext) -> bool:
        """Validate that we have a topic configured."""
        if not context.config.topic:
            logger.error("No topic configured for scraping")
            return False
        return True

    def validate_output(self, context: PipelineContext, result: StageResult) -> bool:
        """Validate that we collected some data."""
        # Allow empty results - it's valid to find nothing
        return True

    async def execute(self, context: PipelineContext) -> StageResult:
        """
        Execute the scraping stage.

        Calls run_pain_scrapers_async() and stores results in context.
        """
        context.phase = ResearchPhase.SCRAPING

        try:
            # Import here to avoid circular imports
            from scrape import run_pain_scrapers_async
            import database

            # Initialize database
            database.init_database()

            # Determine which scrapers to use
            scrapers_to_run = self.scrapers
            if scrapers_to_run is None and context.config.platforms:
                scrapers_to_run = context.config.platforms

            logger.info(f"Starting scrape with scrapers: {scrapers_to_run or 'all'}")

            # Run the scrapers
            stats = await run_pain_scrapers_async(scrapers_to_run)

            # Get the collected posts from database
            # (scrapers save directly to database)
            collected_posts = self._get_recent_posts(context)
            context.raw_posts = collected_posts

            # Update metrics
            context.update_metric("scrape_stats", stats)
            context.update_metric("posts_collected", len(collected_posts))

            logger.info(f"Scraping complete: {len(collected_posts)} posts collected")

            return StageResult(
                status=StageStatus.COMPLETED,
                data={"posts_collected": len(collected_posts), "stats": stats},
                metrics={"posts_count": len(collected_posts), **stats}
            )

        except Exception as e:
            logger.exception("Scraping failed")
            return StageResult(
                status=StageStatus.FAILED,
                error=e
            )

    def _get_recent_posts(self, context: PipelineContext) -> list:
        """
        Get recently collected posts from the database.

        This retrieves posts that haven't been processed yet.
        """
        try:
            import database

            # Get unprocessed posts for the topic
            # We query for posts where processed = 0
            conn = database.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT p.id, p.source, p.url, p.title, p.content, p.author,
                       p.upvotes, p.comments, p.date_posted
                FROM posts p
                LEFT JOIN topics t ON p.topic_id = t.id
                WHERE p.processed = 0
                ORDER BY p.created_at DESC
                LIMIT ?
            """, (context.config.max_posts_per_platform * 10,))

            posts = []
            for row in cursor.fetchall():
                posts.append({
                    "id": row[0],
                    "source": row[1],
                    "url": row[2],
                    "title": row[3],
                    "content": row[4],
                    "author": row[5],
                    "upvotes": row[6],
                    "comments": row[7],
                    "date_posted": row[8]
                })

            conn.close()
            return posts

        except Exception as e:
            logger.error(f"Error getting recent posts: {e}")
            return []
