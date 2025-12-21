"""
Gap Discovery OS - Notion Setup Script
=======================================
Run this once to create all databases, views, and color schemes.

Usage: python setup_notion.py
"""

import sys
import os
from notion_client import Client
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
import config

# Fix Windows encoding issues
if sys.platform == "win32":
    os.system("")  # Enable ANSI escape sequences on Windows
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

console = Console(force_terminal=True)


def get_client() -> Client:
    """Get authenticated Notion client."""
    if not config.NOTION_API_KEY:
        console.print("[red]Error: NOTION_API_KEY not set in config.py[/red]")
        console.print("Get your API key at: https://www.notion.so/my-integrations")
        sys.exit(1)

    if not config.NOTION_PARENT_PAGE_ID:
        console.print("[red]Error: NOTION_PARENT_PAGE_ID not set in config.py[/red]")
        console.print("Create a page in Notion, share it with your integration,")
        console.print("and copy the page ID from the URL.")
        sys.exit(1)

    return Client(auth=config.NOTION_API_KEY)


def create_projects_database(client: Client, parent_id: str) -> str:
    """Create the Research Projects database."""
    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": "Research Projects"}}],
        icon={"type": "emoji", "emoji": "🎯"},
        properties={
            "Name": {"title": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Active", "color": "green"},
                        {"name": "Paused", "color": "yellow"},
                        {"name": "Completed", "color": "gray"},
                        {"name": "Killed", "color": "red"},
                    ]
                }
            },
            "Created": {"date": {}},
            "Subreddits": {"multi_select": {"options": []}},
            "Wedge Summary": {"rich_text": {}},
        }
    )
    return response["id"]


def create_raw_signals_database(client: Client, parent_id: str, projects_db_id: str) -> str:
    """Create the Raw Signals database (Lane 1)."""
    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": "Raw Signals"}}],
        icon={"type": "emoji", "emoji": "📡"},
        properties={
            "Quote": {"title": {}},
            "Source URL": {"url": {}},
            "Platform": {
                "select": {
                    "options": [
                        {"name": "Reddit", "color": "orange"},
                        {"name": "Amazon", "color": "yellow"},
                        {"name": "App Store", "color": "blue"},
                        {"name": "YouTube", "color": "red"},
                        {"name": "TikTok", "color": "pink"},
                    ]
                }
            },
            "Subreddit": {"select": {"options": []}},
            "Signal Type": {
                "select": {
                    "options": [
                        {"name": "Complaint", "color": "red"},
                        {"name": "Abandonment", "color": "orange"},
                        {"name": "Workaround", "color": "yellow"},
                        {"name": "Shame/Self-blame", "color": "purple"},
                        {"name": "Tool blame", "color": "blue"},
                    ]
                }
            },
            "Project": {"relation": {"database_id": projects_db_id, "single_property": {}}},
            "Collected": {"date": {}},
        }
    )
    return response["id"]


def create_pain_clusters_database(client: Client, parent_id: str, projects_db_id: str, signals_db_id: str) -> str:
    """Create the Pain Clusters database (Lane 2)."""
    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": "Pain Clusters"}}],
        icon={"type": "emoji", "emoji": "🔥"},
        properties={
            "Cluster Name": {"title": {}},
            "Theme": {
                "select": {
                    "options": [
                        {"name": "Emotional", "color": "purple"},
                        {"name": "Functional", "color": "blue"},
                        {"name": "Behavioral", "color": "green"},
                    ]
                }
            },
            "Emotional Tone": {
                "select": {
                    "options": [
                        {"name": "Frustration", "color": "red"},
                        {"name": "Shame", "color": "purple"},
                        {"name": "Overwhelm", "color": "orange"},
                        {"name": "Anxiety", "color": "yellow"},
                        {"name": "Resignation", "color": "gray"},
                    ]
                }
            },
            "Blame Direction": {
                "select": {
                    "options": [
                        {"name": "Self", "color": "purple"},
                        {"name": "Tool", "color": "blue"},
                        {"name": "Both", "color": "gray"},
                    ]
                }
            },
            "Sample Quotes": {"relation": {"database_id": signals_db_id, "single_property": {}}},
            "Language Patterns": {"rich_text": {}},
            "Project": {"relation": {"database_id": projects_db_id, "single_property": {}}},
        }
    )
    return response["id"]


def create_scored_opportunities_database(client: Client, parent_id: str, clusters_db_id: str) -> str:
    """Create the Scored Opportunities database (Lane 3)."""

    # Create score options (1-5)
    score_options = [{"name": str(i), "color": ["red", "orange", "yellow", "green", "green"][i-1]} for i in range(1, 6)]

    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": "Scored Opportunities"}}],
        icon={"type": "emoji", "emoji": "📊"},
        properties={
            "Name": {"title": {}},
            "Cluster": {"relation": {"database_id": clusters_db_id, "single_property": {}}},
            "Frequency Score": {"select": {"options": score_options.copy()}},
            "Emotional Weight": {"select": {"options": score_options.copy()}},
            "Cost of Inaction": {"select": {"options": score_options.copy()}},
            "Existing Spend": {"select": {"options": score_options.copy()}},
            "Behavioral Realism": {"select": {"options": score_options.copy()}},
            "Red Flag: Behavior Change": {"checkbox": {}},
            "Red Flag: Requires Discipline": {"checkbox": {}},
            "Red Flag: Needs Explanation": {"checkbox": {}},
            "Verdict": {
                "select": {
                    "options": [
                        {"name": "Pursue", "color": "green"},
                        {"name": "Monitor", "color": "yellow"},
                        {"name": "Kill", "color": "red"},
                    ]
                }
            },
        }
    )
    return response["id"]


def create_wedges_database(client: Client, parent_id: str, opportunities_db_id: str) -> str:
    """Create the Wedges database (Lane 4)."""
    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": "Wedges"}}],
        icon={"type": "emoji", "emoji": "🔧"},
        properties={
            "One-Sentence Wedge": {"title": {}},
            "Opportunity": {"relation": {"database_id": opportunities_db_id, "single_property": {}}},
            "Wedge Type": {
                "select": {
                    "options": [
                        {"name": "Template", "color": "blue"},
                        {"name": "Workflow", "color": "purple"},
                        {"name": "Script/Automation", "color": "green"},
                        {"name": "Checklist", "color": "orange"},
                        {"name": "Guided System", "color": "pink"},
                    ]
                }
            },
            "Status": {
                "select": {
                    "options": [
                        {"name": "Draft", "color": "gray"},
                        {"name": "Validated", "color": "blue"},
                        {"name": "Building", "color": "yellow"},
                        {"name": "Shipped", "color": "green"},
                    ]
                }
            },
            "First Pain Moment": {"rich_text": {}},
            "Stuck Moment": {"rich_text": {}},
            "Current Attempts": {"rich_text": {}},
        }
    )
    return response["id"]


def create_dashboard(client: Client, parent_id: str, db_ids: dict) -> str:
    """Create the main dashboard page with linked database views."""

    # Create the dashboard page
    response = client.pages.create(
        parent={"page_id": parent_id},
        icon={"type": "emoji", "emoji": "🚀"},
        properties={"title": [{"text": {"content": "Dashboard"}}]},
        children=[
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": "Gap Discovery Dashboard"}}]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": "Your visual command center for discovering and validating market gaps."}}]
                }
            },
            {
                "object": "block",
                "type": "divider",
                "divider": {}
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "🎯 Active Projects"}}]
                }
            },
            {
                "object": "block",
                "type": "link_to_page",
                "link_to_page": {"type": "database_id", "database_id": db_ids["projects"]}
            },
            {
                "object": "block",
                "type": "divider",
                "divider": {}
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "📡 Lane 1: Raw Signals"}}]
                }
            },
            {
                "object": "block",
                "type": "link_to_page",
                "link_to_page": {"type": "database_id", "database_id": db_ids["raw_signals"]}
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "🔥 Lane 2: Pain Clusters"}}]
                }
            },
            {
                "object": "block",
                "type": "link_to_page",
                "link_to_page": {"type": "database_id", "database_id": db_ids["pain_clusters"]}
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "📊 Lane 3: Scored Opportunities"}}]
                }
            },
            {
                "object": "block",
                "type": "link_to_page",
                "link_to_page": {"type": "database_id", "database_id": db_ids["scored_opportunities"]}
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "🔧 Lane 4: Wedges"}}]
                }
            },
            {
                "object": "block",
                "type": "link_to_page",
                "link_to_page": {"type": "database_id", "database_id": db_ids["wedges"]}
            },
        ]
    )
    return response["id"]


def update_config_file(db_ids: dict):
    """Update config.py with the database IDs."""
    config_path = "config.py"

    with open(config_path, "r") as f:
        content = f.read()

    # Find and replace the DATABASE_IDS section
    import re

    new_db_ids = f'''DATABASE_IDS = {{
    "projects": "{db_ids['projects']}",
    "raw_signals": "{db_ids['raw_signals']}",
    "pain_clusters": "{db_ids['pain_clusters']}",
    "scored_opportunities": "{db_ids['scored_opportunities']}",
    "wedges": "{db_ids['wedges']}",
}}'''

    # Replace the existing DATABASE_IDS block
    pattern = r'DATABASE_IDS = \{[^}]+\}'
    content = re.sub(pattern, new_db_ids, content)

    with open(config_path, "w") as f:
        f.write(content)


def main():
    console.print("\n[bold blue]Gap Discovery OS - Notion Setup[/bold blue]\n")

    client = get_client()
    parent_id = config.NOTION_PARENT_PAGE_ID

    # Verify connection
    try:
        client.users.me()
        print("[OK] Connected to Notion API")
    except Exception as e:
        print(f"[FAIL] Failed to connect: {e}")
        sys.exit(1)

    db_ids = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:

        # Create databases in order (respecting relations)
        task = progress.add_task("Creating Research Projects database...", total=None)
        db_ids["projects"] = create_projects_database(client, parent_id)
        progress.update(task, description="[OK] Research Projects database created")

        task = progress.add_task("Creating Raw Signals database...", total=None)
        db_ids["raw_signals"] = create_raw_signals_database(client, parent_id, db_ids["projects"])
        progress.update(task, description="[OK] Raw Signals database created")

        task = progress.add_task("Creating Pain Clusters database...", total=None)
        db_ids["pain_clusters"] = create_pain_clusters_database(
            client, parent_id, db_ids["projects"], db_ids["raw_signals"]
        )
        progress.update(task, description="[OK] Pain Clusters database created")

        task = progress.add_task("Creating Scored Opportunities database...", total=None)
        db_ids["scored_opportunities"] = create_scored_opportunities_database(
            client, parent_id, db_ids["pain_clusters"]
        )
        progress.update(task, description="[OK] Scored Opportunities database created")

        task = progress.add_task("Creating Wedges database...", total=None)
        db_ids["wedges"] = create_wedges_database(client, parent_id, db_ids["scored_opportunities"])
        progress.update(task, description="[OK] Wedges database created")

        task = progress.add_task("Creating Dashboard...", total=None)
        create_dashboard(client, parent_id, db_ids)
        progress.update(task, description="[OK] Dashboard created")

        task = progress.add_task("Updating config.py...", total=None)
        update_config_file(db_ids)
        progress.update(task, description="[OK] config.py updated with database IDs")

    console.print("\n[bold green]Setup complete![/bold green]\n")
    console.print("Your Gap Discovery workspace is ready in Notion.")
    console.print("\nNext steps:")
    console.print("  1. Open Notion and find your 'Gap Discovery' page")
    console.print("  2. Click on the Dashboard to see your visual command center")
    console.print("  3. Run: [cyan]python collector.py --help[/cyan] to start collecting signals")
    console.print("")


if __name__ == "__main__":
    main()
