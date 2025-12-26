# Research Pattern Discovery System

Automatically collects real-world complaints from Reddit and YouTube, then synthesizes them into clear problem patterns using AI.

## What This Does

1. Scrapes posts where people express frustration about specific topics
2. Uses Claude AI to group complaints into recurring themes
3. Shows patterns in a visual dashboard with charts and filters

No idea generation. Just surfaces what real people are struggling with.

## What You Need

**Accounts:**
- Anthropic API account (console.anthropic.com)

**Software:**
- Python 3.9 or higher
- Windows 11 (or macOS/Linux with minor adjustments)

**Cost:**
- ~$0.50-$2 per 1000 posts processed
- Everything else is free

## Setup

**1. Install Python dependencies:**
```bash
pip install -r requirements.txt
playwright install chromium
```

**2. Initialize database:**
```bash
python database.py
```

**3. Create config file:**

Copy `config.example.yaml` to `config.yaml` and add your Anthropic API key.

**4. Add your first topic:**

Edit `config.yaml` and add 12-20 keyword phrases for your research topic.

## How to Use

**Scrape new data:**
```bash
python scrape.py
```

Runs for 10-30 minutes. Saves posts to database.

**Synthesize themes:**
```bash
python synthesize.py
```

Sends posts to Claude, extracts patterns.

**View dashboard:**
```bash
streamlit run dashboard.py
```

Opens in browser at http://localhost:8501

## Dashboard Features

- Filter by topic, date range, source
- View theme cards with real quotes
- See top themes bar chart
- Track theme frequency over time
- Monitor intensity distribution
- Auto-suggested new keywords

## Adding New Research Topics

Edit `config.yaml`:
```yaml
topics:
  - name: "Website Decision Paralysis"
    keywords:
      - "can't decide website template"
      - "overthinking my homepage"
      # add 10-18 more
    max_posts_per_keyword: 50

  - name: "Your New Topic"
    keywords:
      - "keyword phrase 1"
      - "keyword phrase 2"
      # add more
    max_posts_per_keyword: 50
```

Run scraper again. Dashboard automatically includes new topic.

## Project Structure
```
research_system/
├── config.yaml           # Topics, keywords, API keys
├── config.example.yaml   # Template for new users
├── database.py           # SQLite schema setup
├── scrape.py             # Reddit/YouTube scraper
├── synthesize.py         # Claude theme extraction
├── dashboard.py          # Streamlit interface
├── requirements.txt      # Dependencies
├── research.db           # SQLite database (created on first run)
└── README.md
```

## Troubleshooting

**Scraper gets blocked:**
- Increase delays in config (5-10 seconds between requests)

**Claude API errors:**
- Check API key in config.yaml
- Verify billing is active on Anthropic account

**Dashboard won't load:**
- Make sure you ran `python database.py` first
- Check that `research.db` exists

## Limitations

- No real-time monitoring (manual scraping only)
- Scraping freezes dashboard while running
- SQLite limits (fine for 10k-100k posts, migrate to Postgres if bigger)
- Rate limiting applies (websites may block aggressive scraping)

## Future Enhancements

- Background scraping (dashboard stays responsive)
- Auto-scheduling (daily scrapes)
- Network graph showing theme relationships
- Export patterns to CSV/PDF
- Cloud deployment for team access
