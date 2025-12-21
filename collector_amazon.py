"""
Gap Discovery OS - Amazon Reviews Collector
============================================
Fetches Amazon product reviews and pushes to Notion.
Focuses on 2-3 star reviews (best pain signals).
No API key required - uses web scraping.

Usage:
    python collector_amazon.py --asin "B08N5WRWNW" --project "Product Research"
    python collector_amazon.py --url "https://amazon.com/dp/B08N5WRWNW" --stars 2,3
    python collector_amazon.py --search "adhd planner" --preview

Setup:
    pip install requests beautifulsoup4 lxml
"""

import argparse
import random
import re
import sys
import time
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.table import Table

import config
import notion_sync
from signal_classifier import classify_signal, get_signal_type_color

console = Console()

# Rotate user agents to avoid blocking
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
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


def extract_asin(url_or_asin: str) -> str | None:
    """Extract ASIN from Amazon URL or return if already ASIN."""
    # If it's already an ASIN (10-char alphanumeric starting with B)
    if re.match(r'^[A-Z0-9]{10}$', url_or_asin):
        return url_or_asin

    # Extract from URL patterns
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/product/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'asin=([A-Z0-9]{10})',
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_asin, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    return None


def get_product_info(asin: str, domain: str = "amazon.com") -> dict | None:
    """Fetch basic product info."""
    session = get_session()
    url = f"https://www.{domain}/dp/{asin}"

    try:
        response = session.get(url, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "lxml")

        title_elem = soup.select_one("#productTitle")
        title = title_elem.get_text(strip=True) if title_elem else "Unknown Product"

        return {
            "asin": asin,
            "title": title[:100],
            "url": url,
        }

    except Exception as e:
        console.print(f"[yellow]Could not fetch product info: {e}[/yellow]")
        return None


def fetch_reviews(
    asin: str,
    domain: str = "amazon.com",
    limit: int = 100,
    star_filter: list[int] = None
) -> list[dict]:
    """Fetch reviews from Amazon product page."""

    if star_filter is None:
        star_filter = [2, 3]  # Default: 2-3 stars (best pain signals)

    results = []
    session = get_session()

    # Get product title first
    product_info = get_product_info(asin, domain)
    product_title = product_info["title"] if product_info else asin

    console.print(f"[blue]Fetching reviews for: {product_title}[/blue]")

    # Build filter string for stars
    star_filter_str = ",".join([f"{s}star" for s in star_filter])

    page = 1
    max_pages = 10

    while len(results) < limit and page <= max_pages:
        # Amazon review URL with star filter
        url = f"https://www.{domain}/product-reviews/{asin}"
        params = {
            "pageNumber": page,
            "filterByStar": star_filter_str.replace(",", "_") if len(star_filter) == 1 else "all_stars",
            "sortBy": "recent",
        }

        # If single star filter, use Amazon's filter
        if len(star_filter) == 1:
            params["filterByStar"] = f"{star_filter[0]}_star"

        try:
            time.sleep(random.uniform(1, 2))  # Rate limiting
            response = session.get(url, params=params, timeout=15)

            if response.status_code != 200:
                console.print(f"[yellow]Page {page}: HTTP {response.status_code}[/yellow]")
                break

            soup = BeautifulSoup(response.text, "lxml")

            # Find review elements
            reviews = soup.select("[data-hook='review']")

            if not reviews:
                break

            for review in reviews:
                if len(results) >= limit:
                    break

                try:
                    # Extract star rating
                    star_elem = review.select_one("[data-hook='review-star-rating']")
                    if star_elem:
                        star_text = star_elem.get_text()
                        star_match = re.search(r'(\d+)', star_text)
                        stars = int(star_match.group(1)) if star_match else 3
                    else:
                        stars = 3

                    # Filter by stars
                    if stars not in star_filter:
                        continue

                    # Extract review title
                    title_elem = review.select_one("[data-hook='review-title'] span:not(.a-icon-alt)")
                    title = title_elem.get_text(strip=True) if title_elem else ""

                    # Extract review body
                    body_elem = review.select_one("[data-hook='review-body'] span")
                    body = body_elem.get_text(strip=True) if body_elem else ""

                    # Combine title and body
                    quote = f"{title}\n\n{body}" if title and body else (title or body)

                    if len(quote) < 20:
                        continue

                    # Get helpful votes
                    helpful_elem = review.select_one("[data-hook='helpful-vote-statement']")
                    helpful_text = helpful_elem.get_text(strip=True) if helpful_elem else ""
                    helpful_match = re.search(r'(\d+)', helpful_text)
                    helpful = int(helpful_match.group(1)) if helpful_match else 0

                    # Get review link
                    link_elem = review.select_one("[data-hook='review-title']")
                    review_url = urljoin(f"https://www.{domain}", link_elem.get("href", "")) if link_elem else ""

                    results.append({
                        "quote": quote[:1000],
                        "url": review_url or f"https://www.{domain}/dp/{asin}",
                        "platform": "Amazon",
                        "source": product_title[:50],
                        "stars": stars,
                        "helpful": helpful,
                    })

                except Exception as e:
                    continue

            page += 1

        except Exception as e:
            console.print(f"[red]Error on page {page}: {e}[/red]")
            break

    return results


def search_products(query: str, domain: str = "amazon.com", limit: int = 5) -> list[dict]:
    """Search for products and return ASINs."""
    session = get_session()
    url = f"https://www.{domain}/s"
    params = {"k": query}

    try:
        response = session.get(url, params=params, timeout=15)
        soup = BeautifulSoup(response.text, "lxml")

        products = []
        items = soup.select("[data-asin]")

        for item in items:
            asin = item.get("data-asin")
            if not asin or len(asin) != 10:
                continue

            title_elem = item.select_one("h2 a span")
            title = title_elem.get_text(strip=True) if title_elem else "Unknown"

            products.append({
                "asin": asin,
                "title": title[:80],
            })

            if len(products) >= limit:
                break

        return products

    except Exception as e:
        console.print(f"[red]Search error: {e}[/red]")
        return []


def collect_signals(
    asin: str,
    project_name: str = None,
    domain: str = "amazon.com",
    limit: int = 100,
    star_filter: list[int] = None
) -> int:
    """Main collection function. Returns number of signals collected."""

    if project_name is None:
        product_info = get_product_info(asin, domain)
        product_name = product_info["title"][:30] if product_info else asin
        project_name = f"{product_name} Research"

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
        task = progress.add_task("Fetching Amazon reviews...", total=None)

        signals = fetch_reviews(
            asin=asin,
            domain=domain,
            limit=limit,
            star_filter=star_filter
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
                        subreddit=signal["source"],  # Reusing for product name
                        project_id=project_id,
                        platform="Amazon",
                        signal_type=signal.get("signal_type")
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to add signal: {e}[/yellow]")

                progress.update(task, advance=1)

        console.print(f"[green]Pushed {len(signals)} signals to Notion[/green]")

    return len(signals)


def show_preview(
    asin: str,
    domain: str = "amazon.com",
    star_filter: list[int] = None,
    limit: int = 10
):
    """Preview what signals would be collected with classification."""
    console.print("\n[bold]Preview Mode[/bold] - showing first 10 results\n")

    signals = fetch_reviews(
        asin=asin,
        domain=domain,
        limit=limit,
        star_filter=star_filter
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
        stars = "*" * signal["stars"]
        sig_type = signal.get("signal_type") or "—"
        color = get_signal_type_color(sig_type)
        table.add_row(f"[{color}]{sig_type}[/{color}]", stars, quote)

    console.print(table)


def interactive_search(query: str, domain: str = "amazon.com"):
    """Search for products and let user select one."""
    console.print(f"\n[bold]Searching Amazon for:[/bold] {query}\n")

    products = search_products(query, domain)

    if not products:
        console.print("[yellow]No products found.[/yellow]")
        return None

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=3)
    table.add_column("ASIN", width=12)
    table.add_column("Title", width=60)

    for i, product in enumerate(products, 1):
        table.add_row(str(i), product["asin"], product["title"])

    console.print(table)
    console.print("\n[dim]Use the ASIN with --asin to collect reviews[/dim]")

    return products


def main():
    parser = argparse.ArgumentParser(
        description="Collect pain signals from Amazon product reviews (2-3 stars).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Collect reviews by ASIN
    python collector_amazon.py --asin "B08N5WRWNW" --project "Planner Research"

    # Collect from product URL
    python collector_amazon.py --url "https://amazon.com/dp/B08N5WRWNW" --limit 200

    # Filter by star rating (2-3 stars = best pain signals)
    python collector_amazon.py --asin "B08N5WRWNW" --stars 2,3

    # Search for products (shows ASINs)
    python collector_amazon.py --search "adhd planner"

    # Preview without pushing to Notion
    python collector_amazon.py --asin "B08N5WRWNW" --preview

    # Different Amazon domain
    python collector_amazon.py --asin "B08N5WRWNW" --domain amazon.co.uk
        """
    )

    parser.add_argument(
        "--asin",
        help="Amazon product ASIN (10-character ID)"
    )
    parser.add_argument(
        "--url",
        help="Amazon product URL (ASIN will be extracted)"
    )
    parser.add_argument(
        "--search", "-s",
        help="Search for products by keyword (shows ASINs)"
    )
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Project name (defaults to product name + 'Research')"
    )
    parser.add_argument(
        "--domain", "-d",
        default="amazon.com",
        help="Amazon domain (default: amazon.com, e.g., amazon.co.uk)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=config.DEFAULT_COLLECTION_LIMIT,
        help=f"Maximum reviews to collect (default: {config.DEFAULT_COLLECTION_LIMIT})"
    )
    parser.add_argument(
        "--stars",
        default="2,3",
        help="Comma-separated star ratings to collect (default: 2,3 for pain signals)"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show what would be collected without pushing to Notion"
    )

    args = parser.parse_args()

    console.print(f"\n[bold blue]Gap Discovery - Amazon Reviews Collector[/bold blue]\n")

    # Handle search mode
    if args.search:
        interactive_search(args.search, args.domain)
        return

    # Get ASIN
    asin = args.asin
    if args.url:
        asin = extract_asin(args.url)
        if not asin:
            console.print(f"[red]Could not extract ASIN from URL[/red]")
            sys.exit(1)

    if not asin:
        console.print("[red]Error: Must specify --asin, --url, or --search[/red]")
        parser.print_help()
        sys.exit(1)

    # Parse star filter
    star_filter = [int(s.strip()) for s in args.stars.split(",")]

    console.print(f"ASIN: {asin}")
    console.print(f"Domain: {args.domain}")
    console.print(f"Star filter: {star_filter}")
    console.print(f"Limit: {args.limit}")

    if args.preview:
        show_preview(
            asin=asin,
            domain=args.domain,
            star_filter=star_filter
        )
    else:
        # Verify Notion connection
        if not notion_sync.check_connection():
            console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
            sys.exit(1)

        count = collect_signals(
            asin=asin,
            project_name=args.project,
            domain=args.domain,
            limit=args.limit,
            star_filter=star_filter
        )

        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Collected {count} pain signals from Amazon reviews.")
        console.print(f"\nNext: Run [cyan]python cluster.py --project \"{args.project or 'Research'}\"[/cyan] to analyze patterns")


if __name__ == "__main__":
    main()
