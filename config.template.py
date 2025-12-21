"""
Gap Discovery OS - Configuration Template
==========================================
Copy this file to config.py and fill in your API keys.

    cp config.template.py config.py

Then run: python setup_notion.py
"""

# =============================================================================
# API KEYS (Required - fill these in)
# =============================================================================

# Notion API
# Get yours at: https://www.notion.so/my-integrations
NOTION_API_KEY = ""

# Notion Parent Page ID
# Create a page called "Gap Discovery", share it with your integration,
# then copy the page ID from the URL (the 32-character string after the page name)
# Example URL: notion.so/Gap-Discovery-abc123def456...
# The ID is: abc123def456...
NOTION_PARENT_PAGE_ID = ""

# Reddit API (OPTIONAL - currently blocked by Reddit's new policy)
# Get yours at: https://www.reddit.com/prefs/apps (create a "script" type app)
REDDIT_CLIENT_ID = ""
REDDIT_CLIENT_SECRET = ""
REDDIT_USER_AGENT = "GapDiscovery/1.0"

# Claude API (Anthropic)
# Get yours at: https://console.anthropic.com
ANTHROPIC_API_KEY = ""

# =============================================================================
# MODEL SETTINGS
# =============================================================================

# Claude model for clustering and wedge generation
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# =============================================================================
# DATABASE IDs (Auto-populated by setup_notion.py - don't edit manually)
# =============================================================================

DATABASE_IDS = {
    "projects": "",
    "raw_signals": "",
    "pain_clusters": "",
    "scored_opportunities": "",
    "wedges": "",
}

# =============================================================================
# COLOR SCHEME
# =============================================================================

COLORS = {
    # Signal Types (Lane 1)
    "signal_types": {
        "Complaint": "red",
        "Abandonment": "orange",
        "Workaround": "yellow",
        "Shame/Self-blame": "purple",
        "Tool blame": "blue",
    },
    # Status colors
    "status": {
        "Active": "green",
        "In Progress": "blue",
        "Paused": "yellow",
        "Completed": "gray",
        "Killed": "red",
    },
    # Verdict colors
    "verdict": {
        "Pursue": "green",
        "Monitor": "yellow",
        "Kill": "red",
    },
    # Wedge types
    "wedge_types": {
        "Template": "blue",
        "Workflow": "purple",
        "Script/Automation": "green",
        "Checklist": "orange",
        "Guided System": "pink",
    },
    # Themes
    "themes": {
        "Emotional": "purple",
        "Functional": "blue",
        "Behavioral": "green",
    },
    # Blame direction
    "blame": {
        "Self": "purple",
        "Tool": "blue",
        "Both": "gray",
    },
}

# =============================================================================
# DEFAULT SETTINGS
# =============================================================================

# Default number of posts/comments to collect per run
DEFAULT_COLLECTION_LIMIT = 100

# Minimum upvotes for a post to be collected
MIN_UPVOTES = 5

# Minimum comment score to be collected
MIN_COMMENT_SCORE = 3
