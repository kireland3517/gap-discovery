# Gap Discovery OS

A Notion-based pipeline for discovering, validating, and designing solutions for real pain points. Funnel raw user feedback into actionable product ideas validated against behavioral reality.

## The 4-Lane Pipeline

```
Lane 1: Raw Signals      Collect pain signals from Reddit, App Store, Play Store, etc.
        ↓
Lane 2: Pain Clusters    AI identifies recurring patterns and themes
        ↓
Lane 3: Scored Opps      Rate opportunities on 5 dimensions (manual + auto)
        ↓
Lane 4: Wedges           Design minimal viable solutions
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cp config.template.py config.py
```

Edit `config.py` and fill in:

| Key | Where to get it |
|-----|-----------------|
| `NOTION_API_KEY` | [notion.so/my-integrations](https://www.notion.so/my-integrations) |
| `NOTION_PARENT_PAGE_ID` | Create a "Gap Discovery" page, share with integration, copy ID from URL |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `YOUTUBE_API_KEY` (optional) | [console.cloud.google.com](https://console.cloud.google.com) - see setup below |
| `REDDIT_*` (optional) | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) - create a "script" app |

### YouTube API Setup (for YouTube collector)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Go to "APIs & Services" → "Library"
4. Search for "YouTube Data API v3" and enable it
5. Go to "Credentials" → "Create Credentials" → "API Key"
6. Copy the key to `config.py` as `YOUTUBE_API_KEY`

**Quota:** 10,000 units/day free. Search = 100 units, comments = 1 unit. Typical run uses ~500 units.

### 3. Set Up Notion Databases

```bash
python setup_notion.py
```

This creates all 5 databases and a dashboard in your Notion workspace.

## Typical Workflow

### Step 1: Collect Pain Signals (Lane 1)

Choose your signal source:

```bash
# Reddit via search (no API key needed - recommended!)
python collector_reddit_search.py --topic "adhd productivity" --project "ADHD Research"

# YouTube comments (requires API key)
python collector_youtube.py --query "adhd tips" --project "ADHD Research"

# App Store reviews (no API key needed)
python collector_appstore.py --app "todoist" --project "Productivity Research"

# Google Play reviews (no API key needed)
python collector_playstore.py --app "com.todoist" --project "Productivity Research"

# Reddit via API (requires API keys - often blocked)
python collector.py --subreddits "adhd,productivity" --keywords "frustrated,gave up"

# TikTok comments (no API key needed)
python collector_tiktok.py --query "adhd productivity" --project "ADHD Research"

# Amazon reviews (no API key needed)
python collector_amazon.py --asin "B08N5WRWNW" --project "Product Research"
```

**Automated deep research pipeline:**
```bash
# Collect from Reddit + YouTube, then run synthesis
python collector_reddit_search.py --topic "adhd" --project "Research" && \
python collector_youtube.py --query "adhd" --project "Research" && \
python cluster.py --project "Research"
```

Use `--preview` to see what would be collected without saving.

**Auto-classification:** All collectors automatically classify signals into pain types:
- **Complaint**: General frustration, annoyance
- **Abandonment**: Gave up, stopped using, switched away
- **Workaround**: DIY solutions, hacks, "I ended up..."
- **Shame/Self-blame**: "I should be able to", "why can't I"
- **Tool blame**: Blaming the app/tool/service

### Step 2: Cluster Pain Patterns (Lane 2)

```bash
python cluster.py --project "Productivity Research"
```

Claude analyzes your signals and groups them into pain clusters with:
- Theme (Emotional / Functional / Behavioral)
- Emotional tone (Frustration / Shame / Overwhelm / etc.)
- Blame direction (Self / Tool / Both)
- Language patterns

This also creates a Scored Opportunity entry for each cluster.

### Step 3: Score Opportunities (Lane 3)

Use the scoring helper to track opportunities:

```bash
# List all opportunities with scores
python score.py --list

# Show only unscored opportunities
python score.py --unscored

# Show top-scoring opportunities
python score.py --top

# Show scoring guide
python score.py --guide
```

Open Notion and score each opportunity on 5 dimensions (1-5):

| Dimension | Question |
|-----------|----------|
| **Frequency Score** | How often does this pain occur? |
| **Emotional Weight** | How intense is the frustration? |
| **Cost of Inaction** | What happens if they don't solve it? |
| **Existing Spend** | Are they already paying for solutions? |
| **Behavioral Realism** | Can we solve this without changing behavior? |

Set **Verdict** to Pursue / Monitor / Kill.

### Step 4: Generate Wedges (Lane 4)

```bash
# Single cluster
python wedge.py --cluster "Time Blindness"

# Auto-process all high-scoring opportunities (score >= 18)
python wedge.py --auto

# Custom threshold
python wedge.py --auto --min-score 20 --preview
```

Claude designs 2-3 minimal solutions per cluster:
- **Template**: Fill-in-the-blank document
- **Workflow**: Step-by-step process
- **Script/Automation**: Small code that does one thing
- **Checklist**: Context-aware list
- **Guided System**: Decision tree or framework

## Collectors Reference

### Reddit Search (Recommended - No API Key)
```bash
python collector_reddit_search.py --topic "adhd productivity" --project "ADHD Research"
python collector_reddit_search.py --topic "todoist" --limit 50 --preview
```
Uses DuckDuckGo to find Reddit posts matching pain patterns ("gave up", "frustrated", etc.) and extracts content from public pages.

### YouTube Comments (Requires API Key)
```bash
python collector_youtube.py --query "adhd productivity tips" --project "ADHD Research"
python collector_youtube.py --video-id "dQw4w9WgXcQ" --limit 200
python collector_youtube.py --query "todoist review" --videos 20 --limit 500
```

### App Store (iOS)
```bash
python collector_appstore.py --app "notion" --stars 1,2 --limit 200
python collector_appstore.py --app-id 585829637 --country gb
```

### Google Play (Android)
```bash
python collector_playstore.py --search "todoist"  # Interactive search
python collector_playstore.py --app "com.todoist" --stars 1,2,3
```

### Reddit API (Often Blocked)
```bash
python collector.py --subreddits "adhd" --keywords "can't focus,gave up"
python collector.py --subreddits "productivity,getdisciplined" --limit 200
```

### TikTok Comments
```bash
python collector_tiktok.py --query "adhd tips" --limit 100
python collector_tiktok.py --video-url "https://tiktok.com/..." --project "Research"
```

### Amazon Reviews
```bash
python collector_amazon.py --asin "B08N5WRWNW" --stars 2,3 --limit 150
python collector_amazon.py --search "planner adhd" --project "Planner Research"
```

## CLI Options Summary

| Flag | Description | Available in |
|------|-------------|--------------|
| `--project`, `-p` | Project name | All collectors, cluster, wedge |
| `--limit`, `-l` | Max items to collect | All collectors, cluster |
| `--preview` | Show without saving | All scripts |
| `--stars` | Filter by rating (1-5) | App stores, Amazon |
| `--auto` | Process all high-scoring | wedge.py |
| `--min-score` | Threshold for --auto | wedge.py, score.py |
| `--unscored` | Show unscored only | score.py |
| `--top` | Show high-scoring only | score.py |
| `--guide` | Show scoring guide | score.py |

## File Structure

```
gap-discovery/
├── config.py               # Your API keys (git-ignored)
├── config.template.py      # Template for config
├── setup_notion.py         # One-time database setup
├── notion_sync.py          # Notion API wrapper
│
├── collector_reddit_search.py  # Reddit via DuckDuckGo (recommended)
├── collector_youtube.py        # YouTube comments
├── collector_appstore.py       # iOS App Store
├── collector_playstore.py      # Google Play Store
├── collector_tiktok.py         # TikTok comments
├── collector_amazon.py         # Amazon reviews
├── collector.py                # Reddit via API (often blocked)
│
├── signal_classifier.py    # Auto-classify signals by pain type
├── cluster.py              # Lane 2: Deep research synthesis
├── score.py                # Lane 3: Scoring helper CLI
├── wedge.py                # Lane 4: Solution design
│
└── prompts/
    ├── clustering.md       # Deep research prompt for Lane 2
    └── wedge_design.md     # Claude prompt for Lane 4
```

## Next Steps

After your first run:

1. **Expand sources**: Add more apps, subreddits, or search terms
2. **Refine clusters**: Re-run clustering with more signals for better patterns
3. **Validate wedges**: Build the recommended wedge and test with real users
4. **Track outcomes**: Update wedge Status in Notion (Draft → Validated → Building → Shipped)

## Troubleshooting

**"NOTION_API_KEY not set"**
- Make sure you copied `config.template.py` to `config.py`
- Fill in your API keys in `config.py`

**"Cannot connect to Notion"**
- Check your API key is correct
- Make sure you shared the parent page with your integration

**"Database ID not found"**
- Run `python setup_notion.py` to create databases
- This updates `config.py` with the database IDs

**Scraper returns empty results**
- Some apps/pages may block scrapers
- Try a different country code (`--country`)
- Try using the app ID instead of name (`--app-id`)

## License

MIT
