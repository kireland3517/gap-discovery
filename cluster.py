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


def run_clustering(signals_text: str) -> dict:
    """Send signals to Claude for deep research synthesis."""
    client = get_claude_client()
    prompt_template = load_prompt_template()

    # Insert signals into prompt
    prompt = prompt_template.replace("{signals}", signals_text)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Running deep research synthesis...", total=None)

        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )

        progress.update(task, description="[green]✓[/green] Synthesis complete")

    # Extract JSON from response
    response_text = response.content[0].text

    # Find JSON in response - try object format first (new), then array (legacy)
    try:
        # Try to find JSON object (new format with patterns + meta)
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            result = json.loads(json_str)
            # If it has "patterns" key, it's the new format
            if "patterns" in result:
                return result
            # Otherwise, wrap single pattern in expected format
            return {"patterns": [result], "meta": {}}
    except json.JSONDecodeError:
        pass

    # Try legacy array format
    try:
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            clusters = json.loads(json_str)
            # Convert legacy format to new format
            return {"patterns": clusters, "meta": {}}
    except json.JSONDecodeError:
        pass

    # If JSON parsing fails, show the raw response
    console.print("[yellow]Warning: Could not parse AI response as JSON[/yellow]")
    console.print(Panel(response_text, title="Raw AI Response"))
    return {"patterns": [], "meta": {}}


def display_clusters(result: dict):
    """Display discovered patterns in a nice format."""
    patterns = result.get("patterns", [])
    meta = result.get("meta", {})

    console.print("\n[bold]Deep Research Synthesis Results[/bold]\n")

    # Display meta information if available
    if meta:
        if meta.get("total_signals_analyzed"):
            console.print(f"[dim]Signals analyzed: {meta['total_signals_analyzed']}[/dim]")
        if meta.get("dominant_emotion"):
            console.print(f"[dim]Dominant emotion: {meta['dominant_emotion']}[/dim]")
        if meta.get("common_tools_mentioned"):
            console.print(f"[dim]Tools mentioned: {', '.join(meta['common_tools_mentioned'][:5])}[/dim]")
        console.print("")

    console.print(f"[bold]Discovered {len(patterns)} Pain Patterns[/bold]\n")

    for i, pattern in enumerate(patterns, 1):
        # Pattern header - support both old and new field names
        name = pattern.get("pattern_name") or pattern.get("cluster_name", "Unnamed")
        emotion = pattern.get("emotional_tone", "Unknown")
        blame = pattern.get("blame_direction", "Unknown")
        intensity = pattern.get("emotional_intensity", "")
        frequency = pattern.get("frequency", "")

        # Color by emotion
        emotion_colors = {
            "Frustration": "red",
            "Shame": "purple",
            "Overwhelm": "yellow",
            "Anxiety": "orange",
            "Resignation": "gray"
        }
        emotion_color = emotion_colors.get(emotion, "white")

        console.print(f"[bold {emotion_color}]Pattern {i}: {name}[/bold {emotion_color}]")

        # Core frustration
        frustration = pattern.get("recurring_frustration", "")
        if frustration:
            console.print(f"  [bold]Core pain:[/bold] {frustration}")

        # Metadata line
        meta_parts = []
        if emotion:
            meta_parts.append(f"Emotion: {emotion}")
        if intensity:
            meta_parts.append(f"Intensity: {intensity}")
        if blame:
            meta_parts.append(f"Blame: {blame}")
        if frequency:
            meta_parts.append(f"Frequency: {frequency}")
        if meta_parts:
            console.print(f"  [dim]{' | '.join(meta_parts)}[/dim]")

        # Abandonment trigger
        trigger = pattern.get("abandonment_trigger")
        if trigger:
            console.print(f"  [red]Quit because:[/red] {trigger}")

        # Workarounds
        workarounds = pattern.get("workarounds") or pattern.get("workarounds_mentioned", [])
        if workarounds:
            console.print(f"  [yellow]Workarounds:[/yellow] {', '.join(workarounds[:3])}")

        # Sample quotes
        quotes = pattern.get("representative_quotes", [])
        if quotes:
            console.print("  [dim]Representative quotes:[/dim]")
            for quote in quotes[:3]:
                short_quote = quote[:80] + "..." if len(quote) > 80 else quote
                console.print(f"    • \"{short_quote}\"")

        # Language patterns
        lang_patterns = pattern.get("language_patterns", [])
        if lang_patterns:
            console.print(f"  [dim]Language patterns:[/dim] {', '.join(lang_patterns[:3])}")

        console.print("")

    # Research gaps
    gaps = meta.get("research_gaps", [])
    if gaps:
        console.print("[dim]Research gaps (couldn't determine from data):[/dim]")
        for gap in gaps:
            console.print(f"  • {gap}")


def save_clusters_to_notion(result: dict, project_id: str, signals: list[dict]):
    """Save patterns to Notion database."""
    patterns = result.get("patterns", [])

    console.print("\n[bold]Saving patterns to Notion...[/bold]")

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

        for pattern in patterns:
            # Support both old and new field names
            name = pattern.get("pattern_name") or pattern.get("cluster_name", "Unnamed Pattern")
            task = progress.add_task(f"Saving: {name}...", total=None)

            # Find signal IDs that match representative quotes
            signal_ids = []
            for quote in pattern.get("representative_quotes", []):
                for key, sig_id in quote_to_id.items():
                    if key in quote or quote[:100] in key:
                        signal_ids.append(sig_id)
                        break

            # Format language patterns as text
            lang_patterns = pattern.get("language_patterns", [])
            patterns_text = "\n".join([f"• {p}" for p in lang_patterns])

            # Add core frustration and abandonment trigger if present
            frustration = pattern.get("recurring_frustration", "")
            trigger = pattern.get("abandonment_trigger")
            if frustration:
                patterns_text = f"Core pain: {frustration}\n\n{patterns_text}"
            if trigger:
                patterns_text += f"\n\nQuit because: {trigger}"

            # Map emotional tone - handle both old values and "External" blame
            emotion = pattern.get("emotional_tone", "Frustration")
            blame = pattern.get("blame_direction", "Both")
            if blame == "External" or blame == "Mixed":
                blame = "Both"  # Map to existing Notion options

            # Infer theme from emotion if not present
            theme = pattern.get("theme")
            if not theme:
                if emotion in ["Shame", "Anxiety", "Overwhelm"]:
                    theme = "Emotional"
                elif emotion == "Frustration":
                    theme = "Functional"
                else:
                    theme = "Behavioral"

            try:
                cluster_id = notion_sync.create_pain_cluster(
                    cluster_name=name,
                    theme=theme,
                    emotional_tone=emotion,
                    blame_direction=blame,
                    language_patterns=patterns_text,
                    project_id=project_id,
                    signal_ids=signal_ids[:5]  # Link up to 5 signals
                )

                # Also create a scored opportunity entry for this cluster
                notion_sync.create_scored_opportunity(cluster_id)

                progress.update(task, description=f"[green]✓[/green] Saved: {name}")

            except Exception as e:
                progress.update(task, description=f"[red]✗[/red] Failed: {name}: {e}")


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

    # Run deep research synthesis
    result = run_clustering(signals_text)
    patterns = result.get("patterns", [])

    if not patterns:
        console.print("[red]No patterns discovered. Check the AI response above.[/red]")
        sys.exit(1)

    # Display results
    display_clusters(result)

    # Save to Notion
    if not args.preview:
        save_clusters_to_notion(result, project_id, signals)
        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Created {len(patterns)} pain patterns with scored opportunity entries.")
        console.print(f"\nNext steps:")
        console.print(f"  1. Open Notion and review the Pain Clusters")
        console.print(f"  2. Score each opportunity in the Scored Opportunities database")
        console.print(f"  3. Run [cyan]python wedge.py --auto[/cyan] to generate wedges for high-scoring clusters")
    else:
        console.print("\n[yellow]Preview mode - patterns not saved to Notion[/yellow]")


if __name__ == "__main__":
    main()
