"""
Gap Discovery OS - Google Play Store Collector
===============================================
Fetches Android app reviews and pushes to Notion.
No API key required - uses web scraping.

Usage:
    python collector_playstore.py --app "com.todoist" --project "Productivity Research"
    python collector_playstore.py --search "todoist" --limit 200
"""

import argparse
import sys
from google_play_scraper import app, reviews, search, Sort
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

import config
import notion_sync
from signal_classifier import classify_signal, get_signal_type_color

console = Console()


def search_app(query: str, n_results: int = 5) -> list[dict]:
    """Search for apps by name and return top results."""
    try:
        results = search(query, n_hits=n_results, lang="en", country="us")
        return [
            {
                "id": r["appId"],
                "name": r["title"],
                "developer": r.get("developer", "Unknown"),
                "score": r.get("score", 0),
            }
            for r in results
        ]
    except Exception as e:
        console.print(f"[yellow]Search error: {e}[/yellow]")
        return []


def get_app_info(app_id: str) -> dict | None:
    """Get app details by package ID."""
    try:
        info = app(app_id, lang="en", country="us")
        return {
            "id": info["appId"],
            "name": info["title"],
            "developer": info.get("developer", "Unknown"),
            "url": info.get("url", f"https://play.google.com/store/apps/details?id={app_id}"),
        }
    except Exception as e:
        console.print(f"[red]Could not find app '{app_id}': {e}[/red]")
        return None


def fetch_reviews(
    app_id: str,
    limit: int = 100,
    score_filter: list[int] = None,
    sort: Sort = Sort.NEWEST
) -> list[dict]:
    """Fetch reviews from Google Play Store."""

    if score_filter is None:
        score_filter = [1, 2, 3]  # Default: pain signals (low ratings)

    results = []

    try:
        # Get app info for name
        app_info = get_app_info(app_id)
        if not app_info:
            return []

        app_name = app_info["name"]
        app_url = app_info["url"]

        console.print(f"[blue]Fetching reviews for: {app_name}[/blue]")

        # Fetch reviews in batches
        result, continuation_token = reviews(
            app_id,
            lang="en",
            country="us",
            sort=sort,
            count=min(limit * 3, 500),  # Fetch extra to account for filtering
            filter_score_with=None  # We'll filter ourselves for more control
        )

        for review in result:
            score = review.get("score", 5)

            # Filter by score
            if score not in score_filter:
                continue

            content = review.get("content", "")

            if len(content) < 20:  # Skip very short reviews
                continue

            results.append({
                "quote": content[:1000],  # Truncate long reviews
                "url": app_url,
                "platform": "Google Play",
                "source": app_name,
                "rating": score,
                "thumbs_up": review.get("thumbsUpCount", 0),
            })

            if len(results) >= limit:
                break

        # If we need more reviews and have a continuation token
        while len(results) < limit and continuation_token:
            result, continuation_token = reviews(
                app_id,
                continuation_token=continuation_token
            )

            for review in result:
                score = review.get("score", 5)
                if score not in score_filter:
                    continue

                content = review.get("content", "")
                if len(content) < 20:
                    continue

                results.append({
                    "quote": content[:1000],
                    "url": app_url,
                    "platform": "Google Play",
                    "source": app_name,
                    "rating": score,
                    "thumbs_up": review.get("thumbsUpCount", 0),
                })

                if len(results) >= limit:
                    break

    except Exception as e:
        console.print(f"[red]Error fetching reviews: {e}[/red]")

    return results


def collect_signals(
    app_id: str,
    project_name: str = None,
    limit: int = 100,
    score_filter: list[int] = None
) -> int:
    """Main collection function. Returns number of signals collected."""

    # Get app info for project name
    app_info = get_app_info(app_id)
    if not app_info:
        console.print(f"[red]Could not find app: {app_id}[/red]")
        return 0

    if project_name is None:
        project_name = f"{app_info['name']} Research"

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
        task = progress.add_task("Fetching Google Play reviews...", total=None)

        signals = fetch_reviews(
            app_id=app_id,
            limit=limit,
            score_filter=score_filter
        )

        progress.update(task, description=f"[green]Found {len(signals)} reviews[/green]")

    console.print(f"\n[bold]Collected {len(signals)} pain signals[/bold]")

    # Push to Notion
    if signals:
        # Classify signals
        console.print("\nClassifying signals...")
        type_counts = {"Complaint": 0, "Abandonment": 0, "Workaround": 0,
                       "Shame/Self-blame": 0, "Tool blame": 0, "Unclassified": 0}

        for signal in signals:
            signal_type = classify_signal(signal["quote"])
            signal["signal_type"] = signal_type
            if signal_type:
                type_counts[signal_type] += 1
            else:
                type_counts["Unclassified"] += 1

        # Show classification summary
        console.print("[dim]Classification breakdown:[/dim]")
        for sig_type, count in type_counts.items():
            if count > 0:
                color = get_signal_type_color(sig_type)
                console.print(f"  [{color}]{sig_type}:[/{color}] {count}")

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
                        platform="Google Play",
                        signal_type=signal.get("signal_type")
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to add signal: {e}[/yellow]")

                progress.update(task, advance=1)

        console.print(f"[green]Pushed {len(signals)} signals to Notion[/green]")

    return len(signals)


def show_preview(
    app_id: str,
    score_filter: list[int] = None,
    limit: int = 10
):
    """Preview what signals would be collected with classification."""
    console.print("\n[bold]Preview Mode[/bold] - showing first 10 results\n")

    signals = fetch_reviews(
        app_id=app_id,
        limit=limit,
        score_filter=score_filter
    )

    # Classify signals for preview
    for signal in signals:
        signal["signal_type"] = classify_signal(signal["quote"])

    table = Table(show_header=True, header_style="bold")
    table.add_column("Signal Type", width=14)
    table.add_column("Stars", width=6, justify="center")
    table.add_column("Review", width=55)

    for signal in signals[:10]:
        quote = signal["quote"][:70] + "..." if len(signal["quote"]) > 70 else signal["quote"]
        quote = quote.replace("\n", " ")
        stars = "*" * signal["rating"]
        sig_type = signal.get("signal_type") or "—"
        color = get_signal_type_color(sig_type)
        table.add_row(f"[{color}]{sig_type}[/{color}]", stars, quote)

    console.print(table)


def interactive_search():
    """Interactive app search mode."""
    console.print("\n[bold]Interactive Search[/bold]\n")

    query = console.input("Enter app name to search: ")
    results = search_app(query)

    if not results:
        console.print("[yellow]No apps found.[/yellow]")
        return None

    console.print("\n[bold]Found apps:[/bold]\n")
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=3)
    table.add_column("App ID", width=40)
    table.add_column("Name", width=30)
    table.add_column("Rating", width=6)

    for i, app in enumerate(results, 1):
        table.add_row(
            str(i),
            app["id"],
            app["name"][:30],
            f"{app['score']:.1f}" if app["score"] else "-"
        )

    console.print(table)
    console.print("\nUse the App ID with --app flag to collect reviews.")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Collect pain signals from Google Play Store reviews.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Collect reviews by package ID
    python collector_playstore.py --app "com.todoist" --project "Productivity Research"

    # Search for an app first
    python collector_playstore.py --search "todoist"

    # Filter by star rating (1-3 = pain signals)
    python collector_playstore.py --app "com.notion.id" --stars 1,2

    # Preview without pushing to Notion
    python collector_playstore.py --app "com.todoist" --preview

    # Collect more reviews
    python collector_playstore.py --app "com.todoist" --limit 300
        """
    )

    parser.add_argument(
        "--app", "-a",
        help="Android package ID (e.g., com.todoist)"
    )
    parser.add_argument(
        "--search", "-s",
        help="Search for apps by name (interactive mode)"
    )
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Project name (defaults to app name + 'Research')"
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

    console.print(f"\n[bold blue]Gap Discovery - Google Play Collector[/bold blue]\n")

    # Search mode
    if args.search:
        interactive_search()
        return

    if not args.app:
        console.print("[red]Error: Must specify --app (package ID) or --search[/red]")
        parser.print_help()
        sys.exit(1)

    # Parse star filter
    score_filter = [int(s.strip()) for s in args.stars.split(",")]

    console.print(f"App: {args.app}")
    console.print(f"Star filter: {score_filter}")
    console.print(f"Limit: {args.limit}")

    if args.preview:
        show_preview(
            app_id=args.app,
            score_filter=score_filter
        )
    else:
        # Verify Notion connection
        if not notion_sync.check_connection():
            console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
            sys.exit(1)

        count = collect_signals(
            app_id=args.app,
            project_name=args.project,
            limit=args.limit,
            score_filter=score_filter
        )

        if count > 0:
            console.print(f"\n[bold green]Done![/bold green]")
            console.print(f"Collected {count} pain signals from Google Play reviews.")
            project_name = args.project or f"{args.app} Research"
            console.print(f"\nNext: Run [cyan]python cluster.py --project \"{project_name}\"[/cyan] to analyze patterns")


if __name__ == "__main__":
    main()
