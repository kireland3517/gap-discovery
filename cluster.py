"""
Gap Discovery OS - AI Clustering (Lane 2)
==========================================
Sends raw signals to Claude for pattern analysis.

Usage:
    python cluster.py --project "My Project"
    python cluster.py --project "My Project" --limit 100
"""

import argparse
import json
import sys
from pathlib import Path

import anthropic
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table

import config
import notion_sync

console = Console()


def get_claude_client() -> anthropic.Anthropic:
    """Get authenticated Claude client."""
    if not config.ANTHROPIC_API_KEY:
        console.print("[red]Error: ANTHROPIC_API_KEY not set in config.py[/red]")
        console.print("Get your API key at: https://console.anthropic.com")
        sys.exit(1)

    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def load_prompt_template() -> str:
    """Load the clustering prompt template."""
    prompt_path = Path(__file__).parent / "prompts" / "clustering.md"
    if not prompt_path.exists():
        console.print("[red]Error: prompts/clustering.md not found[/red]")
        sys.exit(1)

    return prompt_path.read_text()


def format_signals_for_prompt(signals: list[dict]) -> str:
    """Format raw signals for the AI prompt."""
    formatted = []
    for i, signal in enumerate(signals, 1):
        quote = notion_sync.extract_quote_text(signal)
        if quote:
            formatted.append(f"{i}. \"{quote}\"")
    return "\n\n".join(formatted)


def run_clustering(signals_text: str) -> list[dict]:
    """Send signals to Claude for clustering."""
    client = get_claude_client()
    prompt_template = load_prompt_template()

    # Insert signals into prompt
    prompt = prompt_template.replace("{signals}", signals_text)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Analyzing patterns with Claude...", total=None)

        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        progress.update(task, description="[green]✓[/green] Analysis complete")

    # Extract JSON from response
    response_text = response.content[0].text

    # Find JSON in response
    try:
        # Try to find JSON array in the response
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            clusters = json.loads(json_str)
            return clusters
    except json.JSONDecodeError:
        pass

    # If JSON parsing fails, show the raw response
    console.print("[yellow]Warning: Could not parse AI response as JSON[/yellow]")
    console.print(Panel(response_text, title="Raw AI Response"))
    return []


def display_clusters(clusters: list[dict]):
    """Display discovered clusters in a nice format."""
    console.print("\n[bold]Discovered Pain Clusters[/bold]\n")

    for i, cluster in enumerate(clusters, 1):
        # Cluster header
        theme = cluster.get("theme", "Unknown")
        emotion = cluster.get("emotional_tone", "Unknown")
        blame = cluster.get("blame_direction", "Unknown")

        theme_color = {"Emotional": "purple", "Functional": "blue", "Behavioral": "green"}.get(theme, "white")

        console.print(f"[bold {theme_color}]Cluster {i}: {cluster.get('cluster_name', 'Unnamed')}[/bold {theme_color}]")
        console.print(f"  Theme: {theme} | Emotion: {emotion} | Blame: {blame}")

        # Sample quotes
        quotes = cluster.get("representative_quotes", [])
        if quotes:
            console.print("  [dim]Sample quotes:[/dim]")
            for quote in quotes[:3]:
                short_quote = quote[:80] + "..." if len(quote) > 80 else quote
                console.print(f"    • \"{short_quote}\"")

        # Language patterns
        patterns = cluster.get("language_patterns", [])
        if patterns:
            console.print(f"  [dim]Patterns:[/dim] {', '.join(patterns[:3])}")

        console.print("")


def save_clusters_to_notion(clusters: list[dict], project_id: str, signals: list[dict]):
    """Save clusters to Notion database."""
    console.print("\n[bold]Saving clusters to Notion...[/bold]")

    # Build a map of quotes to signal IDs for linking
    quote_to_id = {}
    for signal in signals:
        quote = notion_sync.extract_quote_text(signal)
        if quote:
            quote_to_id[quote[:100]] = signal["id"]  # Use first 100 chars as key

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:

        for cluster in clusters:
            task = progress.add_task(f"Saving: {cluster.get('cluster_name', 'Unnamed')}...", total=None)

            # Find signal IDs that match representative quotes
            signal_ids = []
            for quote in cluster.get("representative_quotes", []):
                for key, sig_id in quote_to_id.items():
                    if key in quote or quote[:100] in key:
                        signal_ids.append(sig_id)
                        break

            # Format language patterns as text
            patterns = cluster.get("language_patterns", [])
            patterns_text = "\n".join([f"• {p}" for p in patterns])

            try:
                cluster_id = notion_sync.create_pain_cluster(
                    cluster_name=cluster.get("cluster_name", "Unnamed Cluster"),
                    theme=cluster.get("theme", "Functional"),
                    emotional_tone=cluster.get("emotional_tone", "Frustration"),
                    blame_direction=cluster.get("blame_direction", "Both"),
                    language_patterns=patterns_text,
                    project_id=project_id,
                    signal_ids=signal_ids[:5]  # Link up to 5 signals
                )

                # Also create a scored opportunity entry for this cluster
                notion_sync.create_scored_opportunity(cluster_id)

                progress.update(task, description=f"[green]✓[/green] Saved: {cluster.get('cluster_name', 'Unnamed')}")

            except Exception as e:
                progress.update(task, description=f"[red]✗[/red] Failed: {cluster.get('cluster_name', 'Unnamed')}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze raw signals with AI to discover pain clusters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Analyze all signals for a project
    python cluster.py --project "ADHD Research"

    # Analyze with a custom limit
    python cluster.py --project "My Project" --limit 150

    # Preview analysis without saving to Notion
    python cluster.py --project "My Project" --preview
        """
    )

    parser.add_argument(
        "--project", "-p",
        required=True,
        help="Name of the project to analyze"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=100,
        help="Maximum signals to analyze (default: 100)"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show clusters without saving to Notion"
    )

    args = parser.parse_args()

    console.print(f"\n[bold blue]Gap Discovery - AI Clustering[/bold blue]\n")

    # Find project
    project = notion_sync.get_project_by_name(args.project)
    if not project:
        console.print(f"[red]Error: Project '{args.project}' not found[/red]")
        console.print("Available projects:")
        for p in notion_sync.list_projects():
            name = p["properties"]["Name"]["title"][0]["text"]["content"]
            console.print(f"  • {name}")
        sys.exit(1)

    project_id = project["id"]
    console.print(f"[green]✓[/green] Found project: {args.project}")

    # Get raw signals
    console.print(f"Fetching raw signals (limit: {args.limit})...")
    signals = notion_sync.get_signals_for_project(project_id, limit=args.limit)

    if not signals:
        console.print("[yellow]No raw signals found for this project.[/yellow]")
        console.print("Run collector.py first to gather signals.")
        sys.exit(1)

    console.print(f"[green]✓[/green] Found {len(signals)} raw signals")

    # Format for AI
    signals_text = format_signals_for_prompt(signals)

    # Run clustering
    clusters = run_clustering(signals_text)

    if not clusters:
        console.print("[red]No clusters discovered. Check the AI response above.[/red]")
        sys.exit(1)

    # Display results
    display_clusters(clusters)

    # Save to Notion
    if not args.preview:
        save_clusters_to_notion(clusters, project_id, signals)
        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Created {len(clusters)} pain clusters with scored opportunity entries.")
        console.print(f"\nNext steps:")
        console.print(f"  1. Open Notion and review the Pain Clusters")
        console.print(f"  2. Score each opportunity in the Scored Opportunities database")
        console.print(f"  3. Run [cyan]python wedge.py --cluster \"Cluster Name\"[/cyan] for high-scoring clusters")
    else:
        console.print("\n[yellow]Preview mode - clusters not saved to Notion[/yellow]")


if __name__ == "__main__":
    main()
