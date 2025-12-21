"""
Gap Discovery OS - Notion API Wrapper
=====================================
Handles all read/write operations to Notion databases.
"""

from notion_client import Client
from datetime import datetime
from typing import Optional
import config


def get_client() -> Client:
    """Get authenticated Notion client."""
    if not config.NOTION_API_KEY:
        raise ValueError("NOTION_API_KEY not set in config.py")
    return Client(auth=config.NOTION_API_KEY)


# =============================================================================
# PROJECTS
# =============================================================================

def create_project(name: str, subreddits: list[str] = None) -> str:
    """Create a new research project. Returns the page ID."""
    client = get_client()
    db_id = config.DATABASE_IDS["projects"]

    properties = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Status": {"select": {"name": "Active"}},
        "Created": {"date": {"start": datetime.now().isoformat()}},
    }

    if subreddits:
        properties["Subreddits"] = {
            "multi_select": [{"name": s} for s in subreddits]
        }

    response = client.pages.create(
        parent={"database_id": db_id},
        properties=properties
    )
    return response["id"]


def get_project_by_name(name: str) -> Optional[dict]:
    """Find a project by name."""
    client = get_client()
    db_id = config.DATABASE_IDS["projects"]

    response = client.databases.query(
        database_id=db_id,
        filter={"property": "Name", "title": {"equals": name}}
    )

    if response["results"]:
        return response["results"][0]
    return None


def list_projects(status: str = None) -> list[dict]:
    """List all projects, optionally filtered by status."""
    client = get_client()
    db_id = config.DATABASE_IDS["projects"]

    query_params = {"database_id": db_id}
    if status:
        query_params["filter"] = {"property": "Status", "select": {"equals": status}}

    response = client.databases.query(**query_params)
    return response["results"]


# =============================================================================
# RAW SIGNALS (Lane 1)
# =============================================================================

def add_raw_signal(
    quote: str,
    source_url: str,
    subreddit: str,
    project_id: str,
    signal_type: str = None,
    platform: str = "Reddit"
) -> str:
    """Add a raw signal to the database. Returns the page ID."""
    client = get_client()
    db_id = config.DATABASE_IDS["raw_signals"]

    # Truncate quote if too long for Notion title (max 2000 chars)
    if len(quote) > 1900:
        quote = quote[:1900] + "..."

    properties = {
        "Quote": {"title": [{"text": {"content": quote}}]},
        "Source URL": {"url": source_url},
        "Platform": {"select": {"name": platform}},
        "Subreddit": {"select": {"name": subreddit}},
        "Project": {"relation": [{"id": project_id}]},
        "Collected": {"date": {"start": datetime.now().isoformat()}},
    }

    if signal_type:
        properties["Signal Type"] = {"select": {"name": signal_type}}

    response = client.pages.create(
        parent={"database_id": db_id},
        properties=properties
    )
    return response["id"]


def get_signals_for_project(project_id: str, limit: int = 200) -> list[dict]:
    """Get all raw signals for a project."""
    client = get_client()
    db_id = config.DATABASE_IDS["raw_signals"]

    response = client.databases.query(
        database_id=db_id,
        filter={"property": "Project", "relation": {"contains": project_id}},
        page_size=min(limit, 100)
    )

    results = response["results"]

    # Handle pagination if needed
    while response.get("has_more") and len(results) < limit:
        response = client.databases.query(
            database_id=db_id,
            filter={"property": "Project", "relation": {"contains": project_id}},
            start_cursor=response["next_cursor"],
            page_size=min(limit - len(results), 100)
        )
        results.extend(response["results"])

    return results[:limit]


def extract_quote_text(signal: dict) -> str:
    """Extract the quote text from a signal page object."""
    title_prop = signal["properties"].get("Quote", {})
    title_array = title_prop.get("title", [])
    if title_array:
        return title_array[0].get("text", {}).get("content", "")
    return ""


# =============================================================================
# PAIN CLUSTERS (Lane 2)
# =============================================================================

def create_pain_cluster(
    cluster_name: str,
    theme: str,
    emotional_tone: str,
    blame_direction: str,
    language_patterns: str,
    project_id: str,
    signal_ids: list[str] = None
) -> str:
    """Create a pain cluster. Returns the page ID."""
    client = get_client()
    db_id = config.DATABASE_IDS["pain_clusters"]

    properties = {
        "Cluster Name": {"title": [{"text": {"content": cluster_name}}]},
        "Theme": {"select": {"name": theme}},
        "Emotional Tone": {"select": {"name": emotional_tone}},
        "Blame Direction": {"select": {"name": blame_direction}},
        "Language Patterns": {"rich_text": [{"text": {"content": language_patterns}}]},
        "Project": {"relation": [{"id": project_id}]},
    }

    if signal_ids:
        properties["Sample Quotes"] = {"relation": [{"id": sid} for sid in signal_ids[:10]]}

    response = client.pages.create(
        parent={"database_id": db_id},
        properties=properties
    )
    return response["id"]


def get_clusters_for_project(project_id: str) -> list[dict]:
    """Get all pain clusters for a project."""
    client = get_client()
    db_id = config.DATABASE_IDS["pain_clusters"]

    response = client.databases.query(
        database_id=db_id,
        filter={"property": "Project", "relation": {"contains": project_id}}
    )
    return response["results"]


def get_cluster_by_name(name: str, project_id: str = None) -> Optional[dict]:
    """Find a cluster by name, optionally within a project."""
    client = get_client()
    db_id = config.DATABASE_IDS["pain_clusters"]

    filter_conditions = [{"property": "Cluster Name", "title": {"equals": name}}]
    if project_id:
        filter_conditions.append({"property": "Project", "relation": {"contains": project_id}})

    query_filter = {"and": filter_conditions} if len(filter_conditions) > 1 else filter_conditions[0]

    response = client.databases.query(
        database_id=db_id,
        filter=query_filter
    )

    if response["results"]:
        return response["results"][0]
    return None


# =============================================================================
# SCORED OPPORTUNITIES (Lane 3)
# =============================================================================

def create_scored_opportunity(cluster_id: str) -> str:
    """Create a scored opportunity entry for a cluster. Returns the page ID."""
    client = get_client()
    db_id = config.DATABASE_IDS["scored_opportunities"]

    properties = {
        "Name": {"title": [{"text": {"content": "Opportunity"}}]},
        "Cluster": {"relation": [{"id": cluster_id}]},
        "Frequency Score": {"select": {"name": "3"}},
        "Emotional Weight": {"select": {"name": "3"}},
        "Cost of Inaction": {"select": {"name": "3"}},
        "Existing Spend": {"select": {"name": "3"}},
        "Behavioral Realism": {"select": {"name": "3"}},
        "Verdict": {"select": {"name": "Monitor"}},
    }

    response = client.pages.create(
        parent={"database_id": db_id},
        properties=properties
    )
    return response["id"]


def get_opportunity_for_cluster(cluster_id: str) -> Optional[dict]:
    """Get the scored opportunity for a cluster."""
    client = get_client()
    db_id = config.DATABASE_IDS["scored_opportunities"]

    response = client.databases.query(
        database_id=db_id,
        filter={"property": "Cluster", "relation": {"contains": cluster_id}}
    )

    if response["results"]:
        return response["results"][0]
    return None


def get_high_score_opportunities(min_score: int = 15) -> list[dict]:
    """Get opportunities with high total scores (for wedge generation)."""
    client = get_client()
    db_id = config.DATABASE_IDS["scored_opportunities"]

    # Notion doesn't support formula filtering directly, so we get all and filter
    response = client.databases.query(database_id=db_id)

    high_score = []
    for opp in response["results"]:
        # Calculate total from individual scores
        total = 0
        for score_field in ["Frequency Score", "Emotional Weight", "Cost of Inaction",
                           "Existing Spend", "Behavioral Realism"]:
            select = opp["properties"].get(score_field, {}).get("select")
            if select:
                try:
                    total += int(select["name"])
                except (ValueError, TypeError):
                    pass

        if total >= min_score:
            opp["_calculated_total"] = total
            high_score.append(opp)

    return sorted(high_score, key=lambda x: x["_calculated_total"], reverse=True)


# =============================================================================
# WEDGES (Lane 4)
# =============================================================================

def create_wedge(
    opportunity_id: str,
    wedge_type: str,
    one_sentence_wedge: str,
    first_pain_moment: str = "",
    stuck_moment: str = "",
    current_attempts: str = ""
) -> str:
    """Create a wedge. Returns the page ID."""
    client = get_client()
    db_id = config.DATABASE_IDS["wedges"]

    properties = {
        "One-Sentence Wedge": {"title": [{"text": {"content": one_sentence_wedge}}]},
        "Opportunity": {"relation": [{"id": opportunity_id}]},
        "Wedge Type": {"select": {"name": wedge_type}},
        "Status": {"select": {"name": "Draft"}},
        "First Pain Moment": {"rich_text": [{"text": {"content": first_pain_moment}}]},
        "Stuck Moment": {"rich_text": [{"text": {"content": stuck_moment}}]},
        "Current Attempts": {"rich_text": [{"text": {"content": current_attempts}}]},
    }

    response = client.pages.create(
        parent={"database_id": db_id},
        properties=properties
    )
    return response["id"]


def get_wedges_for_opportunity(opportunity_id: str) -> list[dict]:
    """Get all wedges for an opportunity."""
    client = get_client()
    db_id = config.DATABASE_IDS["wedges"]

    response = client.databases.query(
        database_id=db_id,
        filter={"property": "Opportunity", "relation": {"contains": opportunity_id}}
    )
    return response["results"]


# =============================================================================
# UTILITIES
# =============================================================================

def check_connection() -> bool:
    """Verify Notion API connection works."""
    try:
        client = get_client()
        client.users.me()
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False


def get_database_count(db_name: str) -> int:
    """Get the number of entries in a database."""
    client = get_client()
    db_id = config.DATABASE_IDS.get(db_name)
    if not db_id:
        return 0

    response = client.databases.query(database_id=db_id, page_size=1)
    # Notion doesn't return total count, so we'd need to paginate
    # For now, return a simple check
    return len(response["results"])
