"""
Gap Discovery OS - App Store Collector
=======================================
Fetches iOS app reviews and pushes to Notion.
No API key required - uses web scraping.

Usage:
    python collector_appstore.py --app "todoist" --project "Productivity Research"
    python collector_appstore.py --app-id 585829637 --limit 200 --stars 1,2,3
"""

import argparse
import sys
from app_store_scraper import AppStore
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

import config
import notion_sync

console = Console()


def search_app(app_name: str, country: str = "us") -> dict | None:
    """Search for an app by name and return its details."""
    try:
        app = AppStore(country=country, app_name=app_name)
        return {
            "id": app.app_id,
            "name": app.app_name,
            "url": f"https://apps.apple.com/{country}/app/{app_name}/id{app.app_id}"
        }
    except Exception as e:
        console.print(f"[yellow]Could not find app '{app_name}': {e}[/yellow]")
        return None


def fetch_reviews(
    app_name: str = None,
    app_id: int = None,
    country: str = "us",
    limit: int = 100,
    star_filter: list[int] = None
) -> list[dict]:
    """Fetch reviews from the App Store."""

    if star_filter is None:
        star_filter = [1, 2, 3]  # Default: pain signals (low ratings)

    results = []

    try:
        if app_id:
            app = AppStore(country=country, app_id=app_id)
        else:
            app = AppStore(country=country, app_name=app_name)

        console.print(f"[blue]Fetching reviews for: {app.app_name}[/blue]")

        # Fetch reviews (the library handles pagination internally)
        app.review(how_many=limit * 2)  # Fetch extra to account for filtering

        for review in app.reviews:
            rating = review.get("rating", 5)

            # Filter by star rating
            if rating not in star_filter:
                continue

            # Extract review data
            title = review.get("title", "")
            content = review.get("review", "")

            # Combine title and content
            quote = f"{title}\n\n{content}" if title and content else (title or content)

            if len(quote) < 20:  # Skip very short reviews
                continue

            results.append({
                "quote": quote[:1000],  # Truncate long reviews
                "url": f"https://apps.apple.com/{country}/app/id{app.app_id}",
                "platform": "App Store",
                "source": app.app_name,
                "rating": rating,
            })

            if len(results) >= limit:
                break

    except Exception as e:
        console.print(f"[red]Error fetching reviews: {e}[/red]")

    return results


def collect_signals(
    app_name: str = None,
    app_id: int = None,
    project_name: str = None,
    country: str = "us",
    limit: int = 100,
    star_filter: list[int] = None
) -> int:
    """Main collection function. Returns number of signals collected."""

    if project_name is None:
        project_name = f"{app_name or 'App'} Research"

    # Get or create project
    project = notion_sync.get_project_by_name(project_name)
    if project:
        project_id = project["id"]
        console.print(f"[blue]Using existing project:[/blue] {project_name}")
    else:
        project_id = notion_sync.create_project(project_name, [])
        console.print(f"[green]Created new project:[/green] {project_name}")

    # Fetch reviews
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Fetching App Store reviews...", total=None)

        signals = fetch_reviews(
            app_name=app_name,
            app_id=app_id,
            country=country,
            limit=limit,
            star_filter=star_filter
        )

        progress.update(task, description=f"[green]Found {len(signals)} reviews[/green]")

    console.print(f"\n[bold]Collected {len(signals)} pain signals[/bold]")

    # Push to Notion
    if signals:
        console.print("\nPushing to Notion...")

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Uploading signals...", total=len(signals))

            for signal in signals:
                try:
                    notion_sync.add_raw_signal(
                        quote=signal["quote"],
                        source_url=signal["url"],
                        subreddit=signal["source"],  # Reusing subreddit field for app name
                        project_id=project_id,
                        platform="App Store"
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to add signal: {e}[/yellow]")

                progress.update(task, advance=1)

        console.print(f"[green]Pushed {len(signals)} signals to Notion[/green]")

    return len(signals)


def show_preview(
    app_name: str = None,
    app_id: int = None,
    country: str = "us",
    star_filter: list[int] = None,
    limit: int = 10
):
    """Preview what signals would be collected."""
    console.print("\n[bold]Preview Mode[/bold] - showing first 10 results\n")

    signals = fetch_reviews(
        app_name=app_name,
        app_id=app_id,
        country=country,
        limit=limit,
        star_filter=star_filter
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Stars", width=6, justify="center")
    table.add_column("Review", width=70)

    for signal in signals[:10]:
        quote = signal["quote"][:100] + "..." if len(signal["quote"]) > 100 else signal["quote"]
        quote = quote.replace("\n", " ")
        stars = "*" * signal["rating"]
        table.add_row(stars, quote)

    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        description="Collect pain signals from iOS App Store reviews.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Collect reviews by app name
    python collector_appstore.py --app "todoist" --project "Productivity Research"

    # Collect by app ID (more reliable)
    python collector_appstore.py --app-id 585829637 --limit 200

    # Filter by star rating (1-3 = pain signals)
    python collector_appstore.py --app "notion" --stars 1,2

    # Preview without pushing to Notion
    python collector_appstore.py --app "todoist" --preview

    # Different country
    python collector_appstore.py --app "todoist" --country gb
        """
    )

    parser.add_argument(
        "--app", "-a",
        help="App name to search for"
    )
    parser.add_argument(
        "--app-id",
        type=int,
        help="App Store app ID (more reliable than name)"
    )
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Project name (defaults to app name + 'Research')"
    )
    parser.add_argument(
        "--country", "-c",
        default="us",
        help="Country code for App Store (default: us)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=config.DEFAULT_COLLECTION_LIMIT,
        help=f"Maximum reviews to collect (default: {config.DEFAULT_COLLECTION_LIMIT})"
    )
    parser.add_argument(
        "--stars",
        default="1,2,3",
        help="Comma-separated star ratings to collect (default: 1,2,3 for pain signals)"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show what would be collected without pushing to Notion"
    )

    args = parser.parse_args()

    if not args.app and not args.app_id:
        console.print("[red]Error: Must specify --app or --app-id[/red]")
        parser.print_help()
        sys.exit(1)

    # Parse star filter
    star_filter = [int(s.strip()) for s in args.stars.split(",")]

    console.print(f"\n[bold blue]Gap Discovery - App Store Collector[/bold blue]\n")
    console.print(f"App: {args.app or f'ID {args.app_id}'}")
    console.print(f"Country: {args.country}")
    console.print(f"Star filter: {star_filter}")
    console.print(f"Limit: {args.limit}")

    if args.preview:
        show_preview(
            app_name=args.app,
            app_id=args.app_id,
            country=args.country,
            star_filter=star_filter
        )
    else:
        # Verify Notion connection
        if not notion_sync.check_connection():
            console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
            sys.exit(1)

        count = collect_signals(
            app_name=args.app,
            app_id=args.app_id,
            project_name=args.project,
            country=args.country,
            limit=args.limit,
            star_filter=star_filter
        )

        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Collected {count} pain signals from App Store reviews.")
        console.print(f"\nNext: Run [cyan]python cluster.py --project \"{args.project or args.app + ' Research'}\"[/cyan] to analyze patterns")


if __name__ == "__main__":
    main()
