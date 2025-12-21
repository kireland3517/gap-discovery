"""
Gap Discovery OS - Scoring Helper CLI (Lane 3)
===============================================
Helps score opportunities from pain clusters.
Lists unscored opportunities, sets scores, and shows recommendations.

Usage:
    python score.py --list                    # List all opportunities with scores
    python score.py --project "ADHD Research" # Show opportunities for a project
    python score.py --unscored                # Show only unscored/default opportunities
    python score.py --top                     # Show top-scoring opportunities

Scoring dimensions (1-5 each):
    - Frequency Score: How often does this pain occur?
    - Emotional Weight: How intense is the frustration?
    - Cost of Inaction: What happens if they don't solve it?
    - Existing Spend: Are they already paying for solutions?
    - Behavioral Realism: Can we solve this without changing behavior?
"""

import argparse
import sys

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

import config
import notion_sync

console = Console()


def get_all_opportunities() -> list[dict]:
    """Get all scored opportunities from Notion."""
    client = notion_sync.get_client()
    db_id = config.DATABASE_IDS["scored_opportunities"]

    response = client.databases.query(database_id=db_id)

    results = response["results"]

    # Handle pagination
    while response.get("has_more"):
        response = client.databases.query(
            database_id=db_id,
            start_cursor=response["next_cursor"]
        )
        results.extend(response["results"])

    return results


def get_opportunities_for_project(project_name: str) -> list[dict]:
    """Get opportunities for a specific project."""
    project = notion_sync.get_project_by_name(project_name)
    if not project:
        return []

    project_id = project["id"]
    clusters = notion_sync.get_clusters_for_project(project_id)

    opportunities = []
    for cluster in clusters:
        opp = notion_sync.get_opportunity_for_cluster(cluster["id"])
        if opp:
            opp["_cluster"] = cluster
            opportunities.append(opp)

    return opportunities


def extract_opp_data(opp: dict) -> dict:
    """Extract relevant data from an opportunity page object."""
    props = opp["properties"]

    # Get scores
    scores = {}
    score_fields = [
        "Frequency Score", "Emotional Weight", "Cost of Inaction",
        "Existing Spend", "Behavioral Realism"
    ]

    for field in score_fields:
        select = props.get(field, {}).get("select")
        if select:
            try:
                scores[field] = int(select["name"])
            except (ValueError, TypeError):
                scores[field] = 3
        else:
            scores[field] = 3

    total = sum(scores.values())

    # Get verdict
    verdict_select = props.get("Verdict", {}).get("select")
    verdict = verdict_select["name"] if verdict_select else "Monitor"

    # Get name
    title_prop = props.get("Name", {})
    title_array = title_prop.get("title", [])
    name = title_array[0]["text"]["content"] if title_array else "Unnamed"

    # Get cluster name if available
    cluster_name = ""
    if "_cluster" in opp:
        cluster_props = opp["_cluster"]["properties"]
        cluster_title = cluster_props.get("Cluster Name", {}).get("title", [])
        if cluster_title:
            cluster_name = cluster_title[0]["text"]["content"]

    return {
        "id": opp["id"],
        "name": name,
        "cluster_name": cluster_name,
        "scores": scores,
        "total": total,
        "verdict": verdict,
    }


def is_default_scores(data: dict) -> bool:
    """Check if all scores are at default value (3)."""
    return all(s == 3 for s in data["scores"].values())


def get_verdict_color(verdict: str) -> str:
    """Get color for verdict."""
    colors = {
        "Pursue": "green",
        "Monitor": "yellow",
        "Kill": "red",
    }
    return colors.get(verdict, "white")


def get_score_color(total: int) -> str:
    """Get color based on total score."""
    if total >= 20:
        return "green"
    elif total >= 15:
        return "yellow"
    else:
        return "dim"


def show_opportunities(opps: list[dict], title: str = "Scored Opportunities"):
    """Display opportunities in a table."""
    if not opps:
        console.print("[yellow]No opportunities found[/yellow]")
        return

    # Extract data and sort by total score
    opp_data = [extract_opp_data(o) for o in opps]
    opp_data.sort(key=lambda x: x["total"], reverse=True)

    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Cluster / Opportunity", width=30)
    table.add_column("Freq", width=5, justify="center")
    table.add_column("Emot", width=5, justify="center")
    table.add_column("Cost", width=5, justify="center")
    table.add_column("Spend", width=5, justify="center")
    table.add_column("Real", width=5, justify="center")
    table.add_column("Total", width=6, justify="center")
    table.add_column("Verdict", width=10)

    for data in opp_data:
        name = data["cluster_name"] or data["name"]
        name = name[:28] + ".." if len(name) > 30 else name

        scores = data["scores"]
        total = data["total"]
        verdict = data["verdict"]

        score_color = get_score_color(total)
        verdict_color = get_verdict_color(verdict)

        table.add_row(
            name,
            str(scores["Frequency Score"]),
            str(scores["Emotional Weight"]),
            str(scores["Cost of Inaction"]),
            str(scores["Existing Spend"]),
            str(scores["Behavioral Realism"]),
            f"[{score_color}]{total}[/{score_color}]",
            f"[{verdict_color}]{verdict}[/{verdict_color}]"
        )

    console.print(table)

    # Summary
    total_opps = len(opp_data)
    pursue = sum(1 for d in opp_data if d["verdict"] == "Pursue")
    monitor = sum(1 for d in opp_data if d["verdict"] == "Monitor")
    kill = sum(1 for d in opp_data if d["verdict"] == "Kill")
    unscored = sum(1 for d in opp_data if is_default_scores(d))

    console.print(f"\n[dim]Total: {total_opps} | "
                  f"[green]Pursue: {pursue}[/green] | "
                  f"[yellow]Monitor: {monitor}[/yellow] | "
                  f"[red]Kill: {kill}[/red] | "
                  f"Unscored: {unscored}[/dim]")


def show_scoring_guide():
    """Display the scoring guide."""
    guide = """
[bold]Scoring Dimensions (1-5 each)[/bold]

[cyan]Frequency Score[/cyan] - How often does this pain occur?
  1 = Rare (once a year)
  3 = Occasional (monthly)
  5 = Constant (daily or multiple times per day)

[cyan]Emotional Weight[/cyan] - How intense is the frustration?
  1 = Mild annoyance
  3 = Moderate frustration
  5 = Rage-inducing, causes shame/self-blame

[cyan]Cost of Inaction[/cyan] - What happens if they don't solve it?
  1 = Nothing significant
  3 = Missed opportunities, wasted time
  5 = Job loss, relationship damage, health impact

[cyan]Existing Spend[/cyan] - Are they already paying for solutions?
  1 = No spending
  3 = Trying free tools, occasional purchases
  5 = Paying for multiple tools, services, coaching

[cyan]Behavioral Realism[/cyan] - Can we solve without changing their behavior?
  1 = Requires major behavior change
  3 = Requires moderate adaptation
  5 = Fits existing behavior perfectly (lowest friction)

[bold]Verdict Guidelines[/bold]
  [green]Pursue[/green] (18-25): High pain, real spending, low friction solution possible
  [yellow]Monitor[/yellow] (12-17): Promising but needs validation or refinement
  [red]Kill[/red] (5-11): Low pain, no spending, or requires too much behavior change
"""
    console.print(Panel(guide, title="Scoring Guide", border_style="blue"))


def show_recommendations(opps: list[dict]):
    """Show actionable recommendations based on current scores."""
    if not opps:
        return

    opp_data = [extract_opp_data(o) for o in opps]

    # Find issues
    unscored = [d for d in opp_data if is_default_scores(d)]
    high_score_monitor = [d for d in opp_data if d["total"] >= 18 and d["verdict"] == "Monitor"]
    low_score_pursue = [d for d in opp_data if d["total"] < 15 and d["verdict"] == "Pursue"]

    console.print("\n[bold]Recommendations[/bold]\n")

    if unscored:
        console.print(f"[yellow]! {len(unscored)} opportunities need scoring:[/yellow]")
        for d in unscored[:5]:
            name = d["cluster_name"] or d["name"]
            console.print(f"  - {name[:50]}")
        if len(unscored) > 5:
            console.print(f"  ... and {len(unscored) - 5} more")
        console.print()

    if high_score_monitor:
        console.print(f"[green]! {len(high_score_monitor)} high-scoring opportunities still on Monitor:[/green]")
        for d in high_score_monitor:
            name = d["cluster_name"] or d["name"]
            console.print(f"  - {name[:40]} (score: {d['total']}) - Consider setting to Pursue")
        console.print()

    if low_score_pursue:
        console.print(f"[red]! {len(low_score_pursue)} low-scoring opportunities marked Pursue:[/red]")
        for d in low_score_pursue:
            name = d["cluster_name"] or d["name"]
            console.print(f"  - {name[:40]} (score: {d['total']}) - Reconsider or improve scores")
        console.print()

    # Show ready for wedge generation
    ready = [d for d in opp_data if d["total"] >= 18 and d["verdict"] == "Pursue"]
    if ready:
        console.print(f"[bold green]{len(ready)} opportunities ready for wedge generation:[/bold green]")
        for d in ready:
            name = d["cluster_name"] or d["name"]
            console.print(f"  - {name[:50]} (score: {d['total']})")
        console.print(f"\n[dim]Run: python wedge.py --auto[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Lane 3 scoring helper - view and manage opportunity scores.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List all opportunities with scores
    python score.py --list

    # Show opportunities for a specific project
    python score.py --project "ADHD Research"

    # Show only unscored opportunities
    python score.py --unscored

    # Show top-scoring opportunities (ready for wedges)
    python score.py --top

    # Show scoring guide
    python score.py --guide

Scoring is done in Notion directly. This CLI helps you:
    - See which opportunities need scoring
    - Identify high-potential opportunities
    - Find inconsistencies (high score but Monitor verdict)
        """
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all opportunities with scores"
    )
    parser.add_argument(
        "--project", "-p",
        help="Filter by project name"
    )
    parser.add_argument(
        "--unscored", "-u",
        action="store_true",
        help="Show only unscored opportunities (all scores at default 3)"
    )
    parser.add_argument(
        "--top", "-t",
        action="store_true",
        help="Show top-scoring opportunities (score >= 18)"
    )
    parser.add_argument(
        "--guide", "-g",
        action="store_true",
        help="Show the scoring guide"
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=18,
        help="Minimum score for --top (default: 18)"
    )

    args = parser.parse_args()

    console.print(f"\n[bold blue]Gap Discovery - Scoring Helper (Lane 3)[/bold blue]\n")

    # Show guide if requested
    if args.guide:
        show_scoring_guide()
        return

    # Verify Notion connection
    if not notion_sync.check_connection():
        console.print("[red]Cannot connect to Notion. Check your API key in config.py[/red]")
        sys.exit(1)

    # Get opportunities
    if args.project:
        console.print(f"[dim]Fetching opportunities for project: {args.project}[/dim]")
        opps = get_opportunities_for_project(args.project)
        if not opps:
            console.print(f"[yellow]No opportunities found for project '{args.project}'[/yellow]")
            console.print("[dim]Make sure you've run cluster.py first[/dim]")
            return
    else:
        console.print("[dim]Fetching all opportunities...[/dim]")
        opps = get_all_opportunities()

    # Filter based on options
    if args.unscored:
        opp_data = [extract_opp_data(o) for o in opps]
        unscored_ids = {d["id"] for d in opp_data if is_default_scores(d)}
        opps = [o for o in opps if o["id"] in unscored_ids]
        show_opportunities(opps, "Unscored Opportunities")

    elif args.top:
        opp_data = [extract_opp_data(o) for o in opps]
        top_ids = {d["id"] for d in opp_data if d["total"] >= args.min_score}
        opps = [o for o in opps if o["id"] in top_ids]
        show_opportunities(opps, f"Top Opportunities (score >= {args.min_score})")

    else:
        # Default: list all
        show_opportunities(opps)

    # Always show recommendations at the end
    show_recommendations(opps)


if __name__ == "__main__":
    main()
