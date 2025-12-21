"""
Gap Discovery OS - TikTok Comments Collector
=============================================
Fetches TikTok video comments and pushes to Notion.
Uses TikTokApi (no API key required, but requires playwright).

Usage:
    python collector_tiktok.py --query "adhd productivity" --project "ADHD Research"
    python collector_tiktok.py --video-url "https://tiktok.com/@user/video/123" --limit 200
    python collector_tiktok.py --hashtag "adhdtiktok" --preview

Setup:
    pip install TikTokApi
    python -m playwright install
"""

import argparse
import asyncio
import sys
import re
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

import config
import notion_sync
from signal_classifier import classify_signal, get_signal_type_color

console = Console()

# Try to import TikTokApi
try:
    from TikTokApi import TikTokApi
    TIKTOK_AVAILABLE = True
except ImportError:
    TIKTOK_AVAILABLE = False


def check_dependencies():
    """Check if TikTok dependencies are installed."""
    if not TIKTOK_AVAILABLE:
        console.print("[red]Error: TikTokApi not installed[/red]")
        console.print("\nInstall with:")
        console.print("  pip install TikTokApi")
        console.print("  python -m playwright install")
        sys.exit(1)


def extract_video_id(url: str) -> str | None:
    """Extract video ID from TikTok URL."""
    # Match patterns like:
    # https://www.tiktok.com/@user/video/1234567890
    # https://vm.tiktok.com/ABC123/
    patterns = [
        r'tiktok\.com/@[\w.]+/video/(\d+)',
        r'tiktok\.com/t/(\w+)',
        r'vm\.tiktok\.com/(\w+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def fetch_video_comments(video_id: str, limit: int = 100) -> list[dict]:
    """Fetch comments from a specific TikTok video."""
    results = []

    async with TikTokApi() as api:
        await api.create_sessions(ms_tokens=[None], num_sessions=1, sleep_after=3)

        try:
            video = api.video(id=video_id)
            async for comment in video.comments(count=limit):
                text = comment.text
                if len(text) < 10:
                    continue

                results.append({
                    "quote": text[:1000],
                    "url": f"https://www.tiktok.com/@{comment.author.username}/video/{video_id}",
                    "platform": "TikTok",
                    "source": f"@{comment.author.username}",
                    "likes": comment.likes_count or 0,
                })

                if len(results) >= limit:
                    break

        except Exception as e:
            console.print(f"[red]Error fetching comments: {e}[/red]")

    return results


async def search_videos_and_comments(
    query: str = None,
    hashtag: str = None,
    limit: int = 100,
    videos_to_scan: int = 10
) -> list[dict]:
    """Search for videos and collect comments from them."""
    results = []

    async with TikTokApi() as api:
        await api.create_sessions(ms_tokens=[None], num_sessions=1, sleep_after=3)

        try:
            videos = []

            if hashtag:
                console.print(f"[blue]Searching hashtag: #{hashtag}[/blue]")
                tag = api.hashtag(name=hashtag)
                async for video in tag.videos(count=videos_to_scan):
                    videos.append(video)
            else:
                console.print(f"[blue]Searching: {query}[/blue]")
                async for video in api.search.videos(query, count=videos_to_scan):
                    videos.append(video)

            console.print(f"[dim]Found {len(videos)} videos to scan[/dim]")

            for video in videos:
                if len(results) >= limit:
                    break

                try:
                    video_url = f"https://www.tiktok.com/@{video.author.username}/video/{video.id}"

                    async for comment in video.comments(count=min(20, limit - len(results))):
                        text = comment.text
                        if len(text) < 10:
                            continue

                        results.append({
                            "quote": text[:1000],
                            "url": video_url,
                            "platform": "TikTok",
                            "source": f"#{hashtag}" if hashtag else query,
                            "likes": comment.likes_count or 0,
                        })

                        if len(results) >= limit:
                            break

                except Exception as e:
                    console.print(f"[yellow]Skipping video: {e}[/yellow]")
                    continue

        except Exception as e:
            console.print(f"[red]Error searching: {e}[/red]")

    return results


def collect_signals(
    query: str = None,
    hashtag: str = None,
    video_url: str = None,
    project_name: str = None,
    limit: int = 100
) -> int:
    """Main collection function. Returns number of signals collected."""

    if project_name is None:
        source = hashtag or query or "TikTok"
        project_name = f"{source} Research"

    # Get or create project
    project = notion_sync.get_project_by_name(project_name)
    if project:
        project_id = project["id"]
        console.print(f"[blue]Using existing project:[/blue] {project_name}")
    else:
        project_id = notion_sync.create_project(project_name, [])
        console.print(f"[green]Created new project:[/green] {project_name}")

    # Fetch comments
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Fetching TikTok comments...", total=None)

        if video_url:
            video_id = extract_video_id(video_url)
            if not video_id:
                console.print(f"[red]Could not extract video ID from URL[/red]")
                return 0
            signals = asyncio.run(fetch_video_comments(video_id, limit))
        else:
            signals = asyncio.run(search_videos_and_comments(
                query=query,
                hashtag=hashtag,
                limit=limit
            ))

        progress.update(task, description=f"[green]Found {len(signals)} comments[/green]")

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
                        subreddit=signal["source"],
                        project_id=project_id,
                        platform="TikTok",
                        signal_type=signal.get("signal_type")
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to add signal: {e}[/yellow]")

                progress.update(task, advance=1)

        console.print(f"[green]Pushed {len(signals)} signals to Notion[/green]")

    return len(signals)


def show_preview(
    query: str = None,
    hashtag: str = None,
    video_url: str = None,
    limit: int = 10
):
    """Preview what signals would be collected with classification."""
    console.print("\n[bold]Preview Mode[/bold] - showing first 10 results\n")

    if video_url:
        video_id = extract_video_id(video_url)
        if not video_id:
            console.print(f"[red]Could not extract video ID from URL[/red]")
            return
        signals = asyncio.run(fetch_video_comments(video_id, limit))
    else:
        signals = asyncio.run(search_videos_and_comments(
            query=query,
            hashtag=hashtag,
            limit=limit
        ))

    # Classify signals for preview
    for signal in signals:
        signal["signal_type"] = classify_signal(signal["quote"])

    table = Table(show_header=True, header_style="bold")
    table.add_column("Signal Type", width=14)
    table.add_column("Likes", width=6, justify="right")
    table.add_column("Comment", width=55)

    for signal in signals[:10]:
        quote = signal["quote"][:70] + "..." if len(signal["quote"]) > 70 else signal["quote"]
        quote = quote.replace("\n", " ")
        sig_type = signal.get("signal_type") or "—"
        color = get_signal_type_color(sig_type)
        table.add_row(f"[{color}]{sig_type}[/{color}]", str(signal["likes"]), quote)

    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        description="Collect pain signals from TikTok comments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Search by keyword and collect comments
    python collector_tiktok.py --query "adhd productivity" --project "ADHD Research"

    # Search by hashtag
    python collector_tiktok.py --hashtag "adhdtiktok" --limit 200

    # Collect from a specific video
    python collector_tiktok.py --video-url "https://tiktok.com/@user/video/123"

    # Preview without pushing to Notion
    python collector_tiktok.py --query "time management" --preview

Note: Requires TikTokApi and playwright:
    pip install TikTokApi
    python -m playwright install
        """
    )

    parser.add_argument(
        "--query", "-q",
        help="Search query for finding videos"
    )
    parser.add_argument(
        "--hashtag", "-t",
        help="Hashtag to search (without #)"
    )
    parser.add_argument(
        "--video-url", "-v",
        help="Specific TikTok video URL to collect comments from"
    )
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Project name (defaults to query/hashtag + 'Research')"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=config.DEFAULT_COLLECTION_LIMIT,
        help=f"Maximum comments to collect (default: {config.DEFAULT_COLLECTION_LIMIT})"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show what would be collected without pushing to Notion"
    )

    args = parser.parse_args()

    if not args.query and not args.hashtag and not args.video_url:
        console.print("[red]Error: Must specify --query, --hashtag, or --video-url[/red]")
        parser.print_help()
        sys.exit(1)

    check_dependencies()

    console.print(f"\n[bold blue]Gap Discovery - TikTok Collector[/bold blue]\n")

    if args.video_url:
        console.print(f"Video: {args.video_url}")
    elif args.hashtag:
        console.print(f"Hashtag: #{args.hashtag}")
    else:
        console.print(f"Query: {args.query}")
    console.print(f"Limit: {args.limit}")

    if args.preview:
        show_preview(
            query=args.query,
            hashtag=args.hashtag,
            video_url=args.video_url,
            limit=10
        )
    else:
        # Verify Notion connection
        if not notion_sync.check_connection():
            console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
            sys.exit(1)

        count = collect_signals(
            query=args.query,
            hashtag=args.hashtag,
            video_url=args.video_url,
            project_name=args.project,
            limit=args.limit
        )

        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Collected {count} pain signals from TikTok comments.")
        source = args.hashtag or args.query or "TikTok"
        console.print(f"\nNext: Run [cyan]python cluster.py --project \"{args.project or source + ' Research'}\"[/cyan] to analyze patterns")


if __name__ == "__main__":
    main()
