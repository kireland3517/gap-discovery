"""
Gap Discovery OS - Wedge Generator (Lane 4)
============================================
Designs minimal viable relief for validated pain points.

Usage:
    python wedge.py --cluster "Time Blindness"
    python wedge.py --auto  # Process all high-scoring opportunities
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
    """Load the wedge design prompt template."""
    prompt_path = Path(__file__).parent / "prompts" / "wedge_design.md"
    if not prompt_path.exists():
        console.print("[red]Error: prompts/wedge_design.md not found[/red]")
        sys.exit(1)

    return prompt_path.read_text()


def get_cluster_data(cluster: dict) -> dict:
    """Extract cluster data from Notion page object."""
    props = cluster["properties"]

    def get_title(prop):
        title = prop.get("title", [])
        return title[0]["text"]["content"] if title else ""

    def get_select(prop):
        select = prop.get("select")
        return select["name"] if select else ""

    def get_rich_text(prop):
        rt = prop.get("rich_text", [])
        return rt[0]["text"]["content"] if rt else ""

    return {
        "cluster_name": get_title(props.get("Cluster Name", {})),
        "theme": get_select(props.get("Theme", {})),
        "emotional_tone": get_select(props.get("Emotional Tone", {})),
        "blame_direction": get_select(props.get("Blame Direction", {})),
        "language_patterns": get_rich_text(props.get("Language Patterns", {})),
    }


def get_opportunity_scores(opportunity: dict) -> dict:
    """Extract scores from opportunity Notion page object."""
    props = opportunity["properties"]

    def get_score(prop_name):
        select = props.get(prop_name, {}).get("select")
        if select:
            try:
                return int(select["name"])
            except (ValueError, TypeError):
                return 3
        return 3

    scores = {
        "frequency": get_score("Frequency Score"),
        "emotional_weight": get_score("Emotional Weight"),
        "cost_of_inaction": get_score("Cost of Inaction"),
        "existing_spend": get_score("Existing Spend"),
        "behavioral_realism": get_score("Behavioral Realism"),
    }
    scores["total"] = sum(scores.values())
    return scores


def build_wedge_prompt(cluster_data: dict, scores: dict, quotes: list[str], workarounds: list[str]) -> str:
    """Build the wedge design prompt with context."""
    template = load_prompt_template()

    # Replace placeholders
    prompt = template.replace("{cluster_name}", cluster_data["cluster_name"])
    prompt = prompt.replace("{theme}", cluster_data["theme"])
    prompt = prompt.replace("{emotional_tone}", cluster_data["emotional_tone"])
    prompt = prompt.replace("{blame_direction}", cluster_data["blame_direction"])

    prompt = prompt.replace("{frequency}", str(scores["frequency"]))
    prompt = prompt.replace("{emotional_weight}", str(scores["emotional_weight"]))
    prompt = prompt.replace("{cost_of_inaction}", str(scores["cost_of_inaction"]))
    prompt = prompt.replace("{existing_spend}", str(scores["existing_spend"]))
    prompt = prompt.replace("{behavioral_realism}", str(scores["behavioral_realism"]))
    prompt = prompt.replace("{total}", str(scores["total"]))

    quotes_text = "\n".join([f"• \"{q}\"" for q in quotes[:5]])
    prompt = prompt.replace("{quotes}", quotes_text)

    prompt = prompt.replace("{language_patterns}", cluster_data["language_patterns"])

    workarounds_text = "\n".join([f"• {w}" for w in workarounds]) if workarounds else "None documented"
    prompt = prompt.replace("{workarounds}", workarounds_text)

    return prompt


def run_wedge_design(prompt: str) -> dict:
    """Send context to Claude for wedge design."""
    client = get_claude_client()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Designing wedges with Claude...", total=None)

        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        progress.update(task, description="[green]✓[/green] Wedge design complete")

    # Extract JSON from response
    response_text = response.content[0].text

    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    console.print("[yellow]Warning: Could not parse AI response as JSON[/yellow]")
    console.print(Panel(response_text, title="Raw AI Response"))
    return {}


def display_wedges(result: dict, cluster_name: str):
    """Display designed wedges in a nice format."""
    console.print(f"\n[bold]Wedge Designs for: {cluster_name}[/bold]\n")

    # Analysis section
    analysis = result.get("analysis", {})
    if analysis:
        console.print("[dim]Analysis:[/dim]")
        console.print(f"  First pain moment: {analysis.get('first_pain_moment', 'N/A')}")
        console.print(f"  Stuck moment: {analysis.get('stuck_moment', 'N/A')}")
        attempts = analysis.get("current_attempts", [])
        if attempts:
            console.print(f"  Current attempts: {', '.join(attempts)}")
        console.print("")

    # Wedges
    wedges = result.get("wedges", [])
    recommended = result.get("recommended", 0)

    for i, wedge in enumerate(wedges):
        is_recommended = i == recommended
        prefix = "[green]★ RECOMMENDED[/green] " if is_recommended else ""

        wedge_type = wedge.get("wedge_type", "Unknown")
        type_color = {
            "Template": "blue",
            "Workflow": "purple",
            "Script": "green",
            "Script/Automation": "green",
            "Checklist": "orange",
            "Guided System": "pink"
        }.get(wedge_type, "white")

        console.print(f"{prefix}[bold {type_color}]Option {i + 1}: {wedge_type}[/bold {type_color}]")
        console.print(f"  [bold]{wedge.get('one_sentence_wedge', 'N/A')}[/bold]")
        console.print(f"  [dim]When to use:[/dim] {wedge.get('first_pain_moment', 'N/A')}")
        console.print(f"  [dim]Why it works:[/dim] {wedge.get('why_this_works', 'N/A')}")

        example = wedge.get("example_implementation", "")
        if example:
            console.print(f"  [dim]Example:[/dim] {example[:100]}...")

        console.print("")


def save_wedges_to_notion(result: dict, opportunity_id: str):
    """Save wedges to Notion database."""
    console.print("\n[bold]Saving wedges to Notion...[/bold]")

    analysis = result.get("analysis", {})
    wedges = result.get("wedges", [])
    recommended = result.get("recommended", 0)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:

        for i, wedge in enumerate(wedges):
            is_recommended = i == recommended
            wedge_type = wedge.get("wedge_type", "Template")

            # Normalize wedge type
            if wedge_type == "Script":
                wedge_type = "Script/Automation"

            task = progress.add_task(f"Saving: {wedge_type}...", total=None)

            # Prepend star to recommended wedge
            one_sentence = wedge.get("one_sentence_wedge", "Unnamed wedge")
            if is_recommended:
                one_sentence = "★ " + one_sentence

            current_attempts = analysis.get("current_attempts", [])
            attempts_text = "\n".join([f"• {a}" for a in current_attempts]) if current_attempts else ""

            try:
                notion_sync.create_wedge(
                    opportunity_id=opportunity_id,
                    wedge_type=wedge_type,
                    one_sentence_wedge=one_sentence,
                    first_pain_moment=wedge.get("first_pain_moment", ""),
                    stuck_moment=analysis.get("stuck_moment", ""),
                    current_attempts=attempts_text
                )
                progress.update(task, description=f"[green]✓[/green] Saved: {wedge_type}")
            except Exception as e:
                progress.update(task, description=f"[red]✗[/red] Failed: {wedge_type}: {e}")


def process_cluster(cluster_name: str, project_name: str = None, preview: bool = False):
    """Process a single cluster to generate wedges."""

    # Find the cluster
    project_id = None
    if project_name:
        project = notion_sync.get_project_by_name(project_name)
        if project:
            project_id = project["id"]

    cluster = notion_sync.get_cluster_by_name(cluster_name, project_id)
    if not cluster:
        console.print(f"[red]Error: Cluster '{cluster_name}' not found[/red]")
        sys.exit(1)

    cluster_id = cluster["id"]
    cluster_data = get_cluster_data(cluster)

    console.print(f"[green]✓[/green] Found cluster: {cluster_name}")

    # Find the scored opportunity for this cluster
    opportunity = notion_sync.get_opportunity_for_cluster(cluster_id)
    if not opportunity:
        console.print("[yellow]Warning: No scored opportunity found for this cluster.[/yellow]")
        console.print("Creating a default opportunity entry...")
        opp_id = notion_sync.create_scored_opportunity(cluster_id)
        opportunity = {"id": opp_id, "properties": {}}
        scores = {"frequency": 3, "emotional_weight": 3, "cost_of_inaction": 3,
                  "existing_spend": 3, "behavioral_realism": 3, "total": 15}
    else:
        scores = get_opportunity_scores(opportunity)

    console.print(f"[green]✓[/green] Opportunity score: {scores['total']}/25")

    # Get sample quotes from cluster
    # For now, extract from language patterns or use placeholder
    quotes = ["Sample quote from cluster analysis"]  # Would need to fetch linked signals

    # Build and run prompt
    prompt = build_wedge_prompt(cluster_data, scores, quotes, [])
    result = run_wedge_design(prompt)

    if not result:
        console.print("[red]No wedge designs generated. Check the AI response above.[/red]")
        sys.exit(1)

    # Display results
    display_wedges(result, cluster_name)

    # Save to Notion
    if not preview:
        save_wedges_to_notion(result, opportunity["id"])
        console.print(f"\n[bold green]Done![/bold green]")
        console.print(f"Created {len(result.get('wedges', []))} wedge options.")
        console.print(f"\nNext: Open Notion and refine your wedges, then move to 'Building' status.")
    else:
        console.print("\n[yellow]Preview mode - wedges not saved to Notion[/yellow]")


def process_auto():
    """Auto-process all high-scoring opportunities."""
    console.print("Finding high-scoring opportunities...")

    opportunities = notion_sync.get_high_score_opportunities(min_score=18)

    if not opportunities:
        console.print("[yellow]No opportunities with score >= 18 found.[/yellow]")
        console.print("Score some pain clusters in Notion first (Scored Opportunities database).")
        return

    console.print(f"Found {len(opportunities)} high-scoring opportunities:\n")

    table = Table(show_header=True)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Cluster", width=40)

    for opp in opportunities:
        score = opp.get("_calculated_total", 0)
        # Would need to fetch cluster name via relation
        table.add_row(str(score), "(Cluster name)")

    console.print(table)
    console.print("\n[yellow]Auto-processing not fully implemented yet.[/yellow]")
    console.print("Run with --cluster to process individual clusters.")


def main():
    parser = argparse.ArgumentParser(
        description="Design minimal viable wedges for validated pain points.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate wedges for a specific cluster
    python wedge.py --cluster "Time Blindness"

    # Specify the project (if cluster names aren't unique)
    python wedge.py --cluster "Overwhelm" --project "ADHD Research"

    # Preview without saving to Notion
    python wedge.py --cluster "Time Blindness" --preview

    # Auto-process all high-scoring opportunities
    python wedge.py --auto
        """
    )

    parser.add_argument(
        "--cluster", "-c",
        help="Name of the pain cluster to design wedges for"
    )
    parser.add_argument(
        "--project", "-p",
        help="Project name (optional, for disambiguation)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-process all high-scoring opportunities"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show wedges without saving to Notion"
    )

    args = parser.parse_args()

    console.print(f"\n[bold blue]Gap Discovery - Wedge Generator[/bold blue]\n")

    if args.auto:
        process_auto()
    elif args.cluster:
        process_cluster(args.cluster, args.project, args.preview)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
