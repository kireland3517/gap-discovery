"""
Gap Discovery OS - Reddit Search Collector
===========================================
Collects Reddit signals via DuckDuckGo search (no Reddit API needed).
Searches for pain-related posts and extracts content from public pages.

Usage:
    python collector_reddit_search.py --topic "adhd productivity" --project "ADHD Research"
    python collector_reddit_search.py --topic "todoist" --limit 50 --preview

No API keys required - uses public search and HTML parsing.
"""

import argparse
import random
import re
import sys
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

import config
import notion_sync

console = Console()

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Pain-focused search query templates
PAIN_QUERIES = [
    'site:reddit.com "{topic}" "I gave up"',
    'site:reddit.com "{topic}" "I stopped using"',
    'site:reddit.com "{topic}" "does anyone else"',
    'site:reddit.com "{topic}" "frustrated"',
    'site:reddit.com "{topic}" "I cant" OR "I can\'t"',
    'site:reddit.com "{topic}" "switched to"',
    'site:reddit.com "{topic}" "workaround"',
    'site:reddit.com "{topic}" "gave up on"',
    'site:reddit.com "{topic}" "anyone else struggle"',
    'site:reddit.com "{topic}" "why is it so hard"',
]


def get_session() -> requests.Session:
    """Create a session with rotating headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return session


def search_duckduckgo(query: str, max_results: int = 20) -> list[dict]:
    """Search DuckDuckGo and return results."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return results
    except Exception as e:
        console.print(f"[yellow]Search error: {e}[/yellow]")
        return []


def is_reddit_post_url(url: str) -> bool:
    """Check if URL is a Reddit post (not subreddit or user page)."""
    parsed = urlparse(url)
    if 'reddit.com' not in parsed.netloc:
        return False
    # Match /r/subreddit/comments/id/ pattern
    return bool(re.search(r'/r/\w+/comments/\w+', parsed.path))


def extract_subreddit(url: str) -> str:
    """Extract subreddit name from Reddit URL."""
    match = re.search(r'/r/(\w+)/', url)
    return match.group(1) if match else "unknown"


def fetch_reddit_page(url: str) -> str | None:
    """Fetch Reddit page HTML with retry logic."""
    session = get_session()

    # Use old.reddit.com for simpler HTML structure
    url = url.replace('www.reddit.com', 'old.reddit.com')
    url = url.replace('reddit.com', 'old.reddit.com')

    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.5, 3.0))  # Rate limiting
            response = session.get(url, timeout=15)
            if response.status_code == 200:
                return response.text
            elif response.status_code == 429:
                console.print(f"[yellow]Rate limited, waiting...[/yellow]")
                time.sleep(10)
        except Exception as e:
            if attempt == 2:
                console.print(f"[yellow]Failed to fetch {url}: {e}[/yellow]")

    return None


def extract_reddit_content(html: str, url: str) -> list[dict]:
    """Extract post and top comments from Reddit page HTML."""
    signals = []
    soup = BeautifulSoup(html, "lxml")
    subreddit = extract_subreddit(url)

    # Extract post title
    title_elem = soup.select_one("a.title")
    title = title_elem.get_text(strip=True) if title_elem else ""

    # Extract post body (self-text)
    body_elem = soup.select_one("div.usertext-body .md")
    body = body_elem.get_text(strip=True) if body_elem else ""

    # Combine title + body for post signal
    if title:
        post_quote = f"{title}\n\n{body}" if body else title
        if len(post_quote) >= 30:
            signals.append({
                "quote": post_quote[:1000],
                "url": url,
                "platform": "Reddit",
                "source": f"r/{subreddit}",
                "type": "post",
                "score": 0,
            })

    # Extract top comments
    comments = soup.select("div.comment .usertext-body .md")
    for i, comment in enumerate(comments[:10]):  # Top 10 comments
        text = comment.get_text(strip=True)
        if len(text) >= 30:
            signals.append({
                "quote": text[:1000],
                "url": url,
                "platform": "Reddit",
                "source": f"r/{subreddit}",
                "type": "comment",
                "score": 0,
            })

    return signals


def collect_signals(
    topic: str,
    project_name: str = None,
    limit: int = 100,
    queries_per_pattern: int = 15
) -> list[dict]:
    """Main collection function. Returns list of signals."""

    if project_name is None:
        project_name = f"{topic} Research"

    console.print(f"[blue]Searching Reddit for:[/blue] {topic}")
    console.print(f"[dim]Using {len(PAIN_QUERIES)} pain-focused query patterns[/dim]\n")

    all_signals = []
    seen_urls = set()

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:

        search_task = progress.add_task("Searching...", total=len(PAIN_QUERIES))

        for query_template in PAIN_QUERIES:
            query = query_template.format(topic=topic)
            progress.update(search_task, description=f"Searching: {query[:50]}...")

            # Search DuckDuckGo
            results = search_duckduckgo(query, max_results=queries_per_pattern)

            for result in results:
                url = result.get("href", "")

                # Skip non-Reddit or duplicate URLs
                if not is_reddit_post_url(url):
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Fetch and extract content
                html = fetch_reddit_page(url)
                if html:
                    signals = extract_reddit_content(html, url)
                    all_signals.extend(signals)

                    if len(all_signals) >= limit:
                        break

            progress.update(search_task, advance=1)

            if len(all_signals) >= limit:
                break

    return all_signals[:limit]


def push_to_notion(signals: list[dict], project_name: str) -> int:
    """Push collected signals to Notion."""

    # Get or create project
    project = notion_sync.get_project_by_name(project_name)
    if project:
        project_id = project["id"]
        console.print(f"[blue]Using existing project:[/blue] {project_name}")
    else:
        project_id = notion_sync.create_project(project_name, [])
        console.print(f"[green]Created new project:[/green] {project_name}")

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
                    platform="Reddit"
                )
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to add signal: {e}[/yellow]")

            progress.update(task, advance=1)

    return len(signals)


def show_preview(signals: list[dict], limit: int = 10):
    """Preview collected signals."""
    console.print("\n[bold]Preview Mode[/bold] - showing first 10 results\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Type", width=8)
    table.add_column("Source", width=15)
    table.add_column("Quote", width=60)

    for signal in signals[:limit]:
        quote = signal["quote"][:80] + "..." if len(signal["quote"]) > 80 else signal["quote"]
        quote = quote.replace("\n", " ")
        table.add_row(signal["type"], signal["source"], quote)

    console.print(table)
    console.print(f"\n[dim]Total signals found: {len(signals)}[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Collect pain signals from Reddit via DuckDuckGo search (no API key needed).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic collection
    python collector_reddit_search.py --topic "adhd productivity" --project "ADHD Research"

    # Search for app/tool pain points
    python collector_reddit_search.py --topic "todoist" --limit 50

    # Preview without pushing to Notion
    python collector_reddit_search.py --topic "notion app" --preview

How it works:
    1. Searches DuckDuckGo for Reddit posts matching pain patterns
       ("gave up", "frustrated", "switched to", etc.)
    2. Fetches each Reddit page and extracts post + comments
    3. Pushes signals to Notion for clustering

No Reddit API key required - uses public search results.
        """
    )

    parser.add_argument(
        "--topic", "-t",
        required=True,
        help="Topic to search for (e.g., 'adhd productivity', 'todoist', 'notion app')"
    )
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Project name (defaults to topic + 'Research')"
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

    console.print(f"\n[bold blue]Gap Discovery - Reddit Search Collector[/bold blue]\n")
    console.print(f"Topic: {args.topic}")
    console.print(f"Limit: {args.limit}")

    # Collect signals
    signals = collect_signals(
        topic=args.topic,
        project_name=args.project,
        limit=args.limit
    )

    console.print(f"\n[bold]Collected {len(signals)} pain signals[/bold]")

    if args.preview:
        show_preview(signals)
    else:
        # Verify Notion connection
        if not notion_sync.check_connection():
            console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
            sys.exit(1)

        count = push_to_notion(signals, args.project or f"{args.topic} Research")

        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Pushed {count} signals to Notion.")
        project = args.project or f"{args.topic} Research"
        console.print(f"\nNext: Run [cyan]python cluster.py --project \"{project}\"[/cyan] to analyze patterns")


if __name__ == "__main__":
    main()
