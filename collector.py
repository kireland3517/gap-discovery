"""
Gap Discovery OS - Reddit Collector
====================================
Fetches posts and comments from Reddit and pushes to Notion.

Usage:
    python collector.py --subreddits "adhd,productivity" --keywords "frustrated,gave up"
    python collector.py --subreddits "productivity" --project "My Project" --limit 50
"""

import argparse
import sys
import praw
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

import config
import notion_sync

console = Console()


def get_reddit_client() -> praw.Reddit:
    """Get authenticated Reddit client."""
    if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
        console.print("[red]Error: Reddit API credentials not set in config.py[/red]")
        console.print("Get your credentials at: https://www.reddit.com/prefs/apps")
        sys.exit(1)

    return praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT
    )


def search_subreddit(
    reddit: praw.Reddit,
    subreddit_name: str,
    keywords: list[str],
    limit: int = 100,
    min_upvotes: int = None,
    min_comments: int = 3
) -> list[dict]:
    """Search a subreddit for posts matching keywords."""

    if min_upvotes is None:
        min_upvotes = config.MIN_UPVOTES

    results = []
    subreddit = reddit.subreddit(subreddit_name)

    # Build search query
    query = " OR ".join(keywords) if keywords else ""

    try:
        # Search posts
        if query:
            posts = subreddit.search(query, limit=limit * 2, sort="relevance", time_filter="year")
        else:
            posts = subreddit.hot(limit=limit * 2)

        for post in posts:
            if len(results) >= limit:
                break

            # Filter by engagement
            if post.score < min_upvotes:
                continue
            if post.num_comments < min_comments:
                continue

            # Add post title + selftext as a signal
            text = post.title
            if post.selftext and len(post.selftext) > 50:
                text = f"{post.title}\n\n{post.selftext[:500]}"

            results.append({
                "quote": text,
                "url": f"https://reddit.com{post.permalink}",
                "subreddit": subreddit_name,
                "score": post.score,
                "type": "post"
            })

            # Also get top comments from the post
            post.comments.replace_more(limit=0)
            for comment in post.comments[:5]:
                if hasattr(comment, 'body') and comment.score >= config.MIN_COMMENT_SCORE:
                    if len(comment.body) > 30:  # Skip very short comments
                        results.append({
                            "quote": comment.body[:1000],
                            "url": f"https://reddit.com{post.permalink}",
                            "subreddit": subreddit_name,
                            "score": comment.score,
                            "type": "comment"
                        })

            if len(results) >= limit:
                break

    except Exception as e:
        console.print(f"[yellow]Warning: Error searching r/{subreddit_name}: {e}[/yellow]")

    return results[:limit]


def collect_signals(
    subreddits: list[str],
    keywords: list[str],
    project_name: str,
    limit: int = 100
) -> int:
    """Main collection function. Returns number of signals collected."""

    reddit = get_reddit_client()

    # Get or create project
    project = notion_sync.get_project_by_name(project_name)
    if project:
        project_id = project["id"]
        console.print(f"[blue]Using existing project:[/blue] {project_name}")
    else:
        project_id = notion_sync.create_project(project_name, subreddits)
        console.print(f"[green]Created new project:[/green] {project_name}")

    all_signals = []

    # Collect from each subreddit
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:

        for subreddit in subreddits:
            task = progress.add_task(f"Searching r/{subreddit}...", total=None)

            signals = search_subreddit(
                reddit,
                subreddit,
                keywords,
                limit=limit // len(subreddits) + 1,
            )

            progress.update(task, description=f"[green]✓[/green] r/{subreddit}: {len(signals)} signals")
            all_signals.extend(signals)

    console.print(f"\n[bold]Collected {len(all_signals)} raw signals[/bold]")

    # Push to Notion
    if all_signals:
        console.print("\nPushing to Notion...")

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:

            task = progress.add_task("Uploading signals...", total=len(all_signals))

            for signal in all_signals:
                try:
                    notion_sync.add_raw_signal(
                        quote=signal["quote"],
                        source_url=signal["url"],
                        subreddit=signal["subreddit"],
                        project_id=project_id,
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to add signal: {e}[/yellow]")

                progress.update(task, advance=1)

        console.print(f"[green]✓ Pushed {len(all_signals)} signals to Notion[/green]")

    return len(all_signals)


def show_preview(subreddits: list[str], keywords: list[str], limit: int = 10):
    """Preview what signals would be collected without pushing to Notion."""

    reddit = get_reddit_client()

    console.print("\n[bold]Preview Mode[/bold] - showing first 10 results\n")

    for subreddit in subreddits:
        console.print(f"\n[blue]r/{subreddit}[/blue]")

        signals = search_subreddit(reddit, subreddit, keywords, limit=limit)

        table = Table(show_header=True, header_style="bold")
        table.add_column("Type", width=8)
        table.add_column("Score", width=6, justify="right")
        table.add_column("Quote", width=60)

        for signal in signals[:10]:
            quote = signal["quote"][:100] + "..." if len(signal["quote"]) > 100 else signal["quote"]
            quote = quote.replace("\n", " ")
            table.add_row(signal["type"], str(signal["score"]), quote)

        console.print(table)


def main():
    parser = argparse.ArgumentParser(
        description="Collect raw signals from Reddit for gap discovery.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Collect from multiple subreddits with keywords
    python collector.py --subreddits "adhd,productivity" --keywords "frustrated,gave up,stopped using"

    # Collect from one subreddit, create a new project
    python collector.py --subreddits "entrepreneur" --project "Side Hustle Research"

    # Preview what would be collected (no Notion push)
    python collector.py --subreddits "fitness" --keywords "quit,failed" --preview

    # Collect more signals
    python collector.py --subreddits "cooking" --limit 200
        """
    )

    parser.add_argument(
        "--subreddits", "-s",
        required=True,
        help="Comma-separated list of subreddits to search (without r/)"
    )
    parser.add_argument(
        "--keywords", "-k",
        default="",
        help="Comma-separated list of keywords to search for"
    )
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Project name (defaults to first subreddit name)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=config.DEFAULT_COLLECTION_LIMIT,
        help=f"Maximum signals to collect (default: {config.DEFAULT_COLLECTION_LIMIT})"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show what would be collected without pushing to Notion"
    )

    args = parser.parse_args()

    # Parse inputs
    subreddits = [s.strip() for s in args.subreddits.split(",")]
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    project_name = args.project or f"{subreddits[0].title()} Research"

    console.print(f"\n[bold blue]Gap Discovery - Reddit Collector[/bold blue]\n")
    console.print(f"Subreddits: {', '.join(['r/' + s for s in subreddits])}")
    if keywords:
        console.print(f"Keywords: {', '.join(keywords)}")
    console.print(f"Limit: {args.limit}")

    if args.preview:
        show_preview(subreddits, keywords, limit=10)
    else:
        # Verify Notion connection first
        if not notion_sync.check_connection():
            console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
            sys.exit(1)

        count = collect_signals(subreddits, keywords, project_name, args.limit)

        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Collected {count} signals for project: {project_name}")
        console.print(f"\nNext: Run [cyan]python cluster.py --project \"{project_name}\"[/cyan] to analyze patterns")


if __name__ == "__main__":
    main()
