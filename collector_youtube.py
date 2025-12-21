"""
Gap Discovery OS - YouTube Comments Collector
==============================================
Collects comments from YouTube videos using the official YouTube Data API v3.
Searches for videos by keyword and extracts comments for pain signal analysis.

Usage:
    python collector_youtube.py --query "adhd productivity tips" --project "ADHD Research"
    python collector_youtube.py --video-id "dQw4w9WgXcQ" --limit 200
    python collector_youtube.py --query "todoist review" --preview

Requires: YOUTUBE_API_KEY in config.py
Get your API key at: https://console.cloud.google.com/apis
"""

import argparse
import re
import sys
from html import unescape

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

import config
import notion_sync
from signal_classifier import classify_signal, get_signal_type_color

console = Console()

# Try to import Google API client
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    YOUTUBE_AVAILABLE = True
except ImportError:
    YOUTUBE_AVAILABLE = False


def check_dependencies():
    """Check if YouTube API dependencies are installed."""
    if not YOUTUBE_AVAILABLE:
        console.print("[red]Error: google-api-python-client not installed[/red]")
        console.print("\nInstall with:")
        console.print("  pip install google-api-python-client")
        sys.exit(1)

    if not config.YOUTUBE_API_KEY:
        console.print("[red]Error: YOUTUBE_API_KEY not set in config.py[/red]")
        console.print("\nGet your API key at:")
        console.print("  https://console.cloud.google.com/apis")
        console.print("\nSteps:")
        console.print("  1. Create a project (or select existing)")
        console.print("  2. Enable 'YouTube Data API v3'")
        console.print("  3. Create credentials → API Key")
        console.print("  4. Add to config.py as YOUTUBE_API_KEY")
        sys.exit(1)


def get_youtube_client():
    """Create authenticated YouTube API client."""
    return build('youtube', 'v3', developerKey=config.YOUTUBE_API_KEY)


def clean_html(text: str) -> str:
    """Remove HTML tags and unescape HTML entities."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = unescape(text)
    # Normalize whitespace
    text = ' '.join(text.split())
    return text


def search_videos(query: str, max_results: int = 10) -> list[dict]:
    """Search for videos by query."""
    youtube = get_youtube_client()

    try:
        response = youtube.search().list(
            q=query,
            part='id,snippet',
            type='video',
            maxResults=max_results,
            order='relevance',
            relevanceLanguage='en'
        ).execute()

        videos = []
        for item in response.get('items', []):
            if item['id']['kind'] == 'youtube#video':
                videos.append({
                    'video_id': item['id']['videoId'],
                    'title': item['snippet']['title'],
                    'channel': item['snippet']['channelTitle'],
                    'description': item['snippet'].get('description', ''),
                })

        return videos

    except HttpError as e:
        console.print(f"[red]YouTube API error: {e}[/red]")
        return []


def get_video_comments(video_id: str, max_results: int = 100) -> list[dict]:
    """Fetch comments from a specific video."""
    youtube = get_youtube_client()
    comments = []

    try:
        # Get top-level comments
        response = youtube.commentThreads().list(
            videoId=video_id,
            part='snippet',
            maxResults=min(max_results, 100),
            order='relevance',
            textFormat='plainText'
        ).execute()

        for item in response.get('items', []):
            snippet = item['snippet']['topLevelComment']['snippet']
            text = clean_html(snippet.get('textDisplay', ''))

            if len(text) >= 20:  # Skip very short comments
                comments.append({
                    'quote': text[:1000],
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'platform': 'YouTube',
                    'source': snippet.get('authorDisplayName', 'Unknown'),
                    'likes': snippet.get('likeCount', 0),
                    'video_id': video_id,
                })

        # Handle pagination if needed
        while 'nextPageToken' in response and len(comments) < max_results:
            response = youtube.commentThreads().list(
                videoId=video_id,
                part='snippet',
                maxResults=min(max_results - len(comments), 100),
                order='relevance',
                textFormat='plainText',
                pageToken=response['nextPageToken']
            ).execute()

            for item in response.get('items', []):
                snippet = item['snippet']['topLevelComment']['snippet']
                text = clean_html(snippet.get('textDisplay', ''))

                if len(text) >= 20:
                    comments.append({
                        'quote': text[:1000],
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'platform': 'YouTube',
                        'source': snippet.get('authorDisplayName', 'Unknown'),
                        'likes': snippet.get('likeCount', 0),
                        'video_id': video_id,
                    })

                if len(comments) >= max_results:
                    break

    except HttpError as e:
        if 'commentsDisabled' in str(e):
            console.print(f"[yellow]Comments disabled for video {video_id}[/yellow]")
        else:
            console.print(f"[yellow]Error fetching comments for {video_id}: {e}[/yellow]")

    return comments


def collect_signals(
    query: str = None,
    video_id: str = None,
    project_name: str = None,
    limit: int = 100,
    videos_to_search: int = 10
) -> list[dict]:
    """Main collection function. Returns list of signals."""

    if video_id:
        # Single video mode
        console.print(f"[blue]Fetching comments from video:[/blue] {video_id}")
        return get_video_comments(video_id, limit)

    # Search mode
    console.print(f"[blue]Searching YouTube for:[/blue] {query}")
    console.print(f"[dim]Will scan top {videos_to_search} videos[/dim]\n")

    all_signals = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:

        # Search for videos
        search_task = progress.add_task("Searching videos...", total=None)
        videos = search_videos(query, max_results=videos_to_search)
        progress.update(search_task, description=f"[green]Found {len(videos)} videos[/green]")

        if not videos:
            console.print("[yellow]No videos found for query[/yellow]")
            return []

        # Collect comments from each video
        comments_task = progress.add_task("Collecting comments...", total=len(videos))

        for video in videos:
            if len(all_signals) >= limit:
                break

            progress.update(
                comments_task,
                description=f"Fetching: {video['title'][:40]}..."
            )

            comments_per_video = min(50, limit - len(all_signals))
            comments = get_video_comments(video['video_id'], comments_per_video)

            # Add video context to each comment
            for comment in comments:
                comment['video_title'] = video['title']
                comment['channel'] = video['channel']

            all_signals.extend(comments)
            progress.update(comments_task, advance=1)

    return all_signals[:limit]


def push_to_notion(signals: list[dict], project_name: str) -> int:
    """Push collected signals to Notion with auto-classification."""

    # Get or create project
    project = notion_sync.get_project_by_name(project_name)
    if project:
        project_id = project["id"]
        console.print(f"[blue]Using existing project:[/blue] {project_name}")
    else:
        project_id = notion_sync.create_project(project_name, [])
        console.print(f"[green]Created new project:[/green] {project_name}")

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
                # Use channel name as source
                source = signal.get('channel', signal.get('source', 'YouTube'))
                notion_sync.add_raw_signal(
                    quote=signal["quote"],
                    source_url=signal["url"],
                    subreddit=source,  # Reusing field for source name
                    project_id=project_id,
                    platform="YouTube",
                    signal_type=signal.get("signal_type")
                )
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to add signal: {e}[/yellow]")

            progress.update(task, advance=1)

    return len(signals)


def show_preview(signals: list[dict], limit: int = 10):
    """Preview collected signals with classification."""
    console.print("\n[bold]Preview Mode[/bold] - showing first 10 results\n")

    # Classify signals for preview
    for signal in signals:
        signal["signal_type"] = classify_signal(signal["quote"])

    table = Table(show_header=True, header_style="bold")
    table.add_column("Signal Type", width=14)
    table.add_column("Likes", width=6, justify="right")
    table.add_column("Comment", width=55)

    for signal in signals[:limit]:
        quote = signal["quote"][:60] + "..." if len(signal["quote"]) > 60 else signal["quote"]
        quote = quote.replace("\n", " ")
        sig_type = signal.get("signal_type") or "—"
        color = get_signal_type_color(sig_type)
        table.add_row(f"[{color}]{sig_type}[/{color}]", str(signal["likes"]), quote)

    console.print(table)
    console.print(f"\n[dim]Total comments found: {len(signals)}[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Collect pain signals from YouTube comments using the official API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Search for videos and collect comments
    python collector_youtube.py --query "adhd productivity tips" --project "ADHD Research"

    # Collect from a specific video
    python collector_youtube.py --video-id "dQw4w9WgXcQ" --limit 200

    # Preview without pushing to Notion
    python collector_youtube.py --query "todoist review" --preview

    # Control how many videos to scan
    python collector_youtube.py --query "notion app" --videos 20 --limit 500

Setup:
    1. Go to https://console.cloud.google.com/
    2. Create a project (or select existing)
    3. Enable "YouTube Data API v3"
    4. Create credentials → API Key
    5. Add to config.py as YOUTUBE_API_KEY

Quota: 10,000 units/day. Search = 100 units, Comments = 1 unit.
        """
    )

    parser.add_argument(
        "--query", "-q",
        help="Search query for finding videos"
    )
    parser.add_argument(
        "--video-id", "-v",
        help="Specific YouTube video ID to collect comments from"
    )
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Project name (defaults to query + 'Research')"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=config.DEFAULT_COLLECTION_LIMIT,
        help=f"Maximum comments to collect (default: {config.DEFAULT_COLLECTION_LIMIT})"
    )
    parser.add_argument(
        "--videos",
        type=int,
        default=10,
        help="Number of videos to scan when searching (default: 10)"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show what would be collected without pushing to Notion"
    )

    args = parser.parse_args()

    if not args.query and not args.video_id:
        console.print("[red]Error: Must specify --query or --video-id[/red]")
        parser.print_help()
        sys.exit(1)

    check_dependencies()

    console.print(f"\n[bold blue]Gap Discovery - YouTube Comments Collector[/bold blue]\n")

    if args.video_id:
        console.print(f"Video ID: {args.video_id}")
    else:
        console.print(f"Query: {args.query}")
        console.print(f"Videos to scan: {args.videos}")
    console.print(f"Limit: {args.limit}")

    # Collect signals
    signals = collect_signals(
        query=args.query,
        video_id=args.video_id,
        project_name=args.project,
        limit=args.limit,
        videos_to_search=args.videos
    )

    console.print(f"\n[bold]Collected {len(signals)} comments[/bold]")

    if args.preview:
        show_preview(signals)
    else:
        # Verify Notion connection
        if not notion_sync.check_connection():
            console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
            sys.exit(1)

        project_name = args.project or f"{args.query or 'YouTube'} Research"
        count = push_to_notion(signals, project_name)

        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Pushed {count} signals to Notion.")
        console.print(f"\nNext: Run [cyan]python cluster.py --project \"{project_name}\"[/cyan] to analyze patterns")


if __name__ == "__main__":
    main()
