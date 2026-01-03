"""
Pain-Point Intelligence Synthesis using Claude API.

Extracts pain evidence from posts and classifies against the four questions:
1. What manual task is causing frustration?
2. What does it cost them (time, money, errors)?
3. What have they already tried that failed?
4. What would "better" look like in their words?
"""

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import yaml
from anthropic import Anthropic, APIError, RateLimitError, APIConnectionError

import database

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds, will be multiplied for exponential backoff


# ============================================
# CIRCUIT BREAKER FOR API COST PROTECTION
# ============================================

class CircuitBreaker:
    """
    Circuit breaker to prevent runaway API costs and infinite retry loops.

    Opens circuit after consecutive failures or cost threshold exceeded.
    Tracks estimated costs based on token usage.
    """

    # Approximate costs per 1K tokens (Claude 3.5 Sonnet pricing)
    INPUT_COST_PER_1K = 0.003   # $3 per million input tokens
    OUTPUT_COST_PER_1K = 0.015  # $15 per million output tokens

    def __init__(
        self,
        max_consecutive_failures: int = 5,
        max_session_cost_usd: float = 10.0,
        cooldown_seconds: int = 300  # 5 minutes
    ):
        self.max_consecutive_failures = max_consecutive_failures
        self.max_session_cost_usd = max_session_cost_usd
        self.cooldown_seconds = cooldown_seconds

        # State
        self.consecutive_failures = 0
        self.total_cost_usd = 0.0
        self.total_api_calls = 0
        self.circuit_open = False
        self.circuit_opened_at = None
        self.last_error = None

    def is_open(self) -> bool:
        """Check if circuit is open (blocking API calls)."""
        if not self.circuit_open:
            return False

        # Check if cooldown period has passed
        if self.circuit_opened_at:
            elapsed = time.time() - self.circuit_opened_at
            if elapsed >= self.cooldown_seconds:
                print(f"  Circuit breaker: Cooldown elapsed, resetting circuit")
                self.reset()
                return False

        return True

    def get_status(self) -> dict:
        """Get current circuit breaker status."""
        return {
            "circuit_open": self.circuit_open,
            "consecutive_failures": self.consecutive_failures,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "total_api_calls": self.total_api_calls,
            "last_error": str(self.last_error) if self.last_error else None
        }

    def record_success(self, input_tokens: int = 0, output_tokens: int = 0):
        """Record a successful API call."""
        self.consecutive_failures = 0
        self.total_api_calls += 1

        # Estimate cost
        cost = (input_tokens / 1000 * self.INPUT_COST_PER_1K +
                output_tokens / 1000 * self.OUTPUT_COST_PER_1K)
        self.total_cost_usd += cost

        # Check cost threshold
        if self.total_cost_usd >= self.max_session_cost_usd:
            self._open_circuit(f"Session cost limit exceeded: ${self.total_cost_usd:.2f}")

    def record_failure(self, error: Exception):
        """Record a failed API call."""
        self.consecutive_failures += 1
        self.total_api_calls += 1
        self.last_error = error

        if self.consecutive_failures >= self.max_consecutive_failures:
            self._open_circuit(f"Max consecutive failures ({self.max_consecutive_failures}) reached")

    def _open_circuit(self, reason: str):
        """Open the circuit breaker."""
        self.circuit_open = True
        self.circuit_opened_at = time.time()
        print(f"\n  ⚠️  CIRCUIT BREAKER OPENED: {reason}")
        print(f"      API calls will be blocked for {self.cooldown_seconds}s")
        print(f"      Status: {self.get_status()}")

    def reset(self):
        """Reset the circuit breaker state."""
        self.consecutive_failures = 0
        self.circuit_open = False
        self.circuit_opened_at = None
        self.last_error = None
        # Note: We don't reset total_cost_usd or total_api_calls
        # Those persist for session-level tracking


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    """Get the global circuit breaker instance."""
    return _circuit_breaker


def reset_circuit_breaker():
    """Reset the global circuit breaker (for new sessions)."""
    global _circuit_breaker
    _circuit_breaker = CircuitBreaker()


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass


# ============================================
# PAIN EXTRACTION PROMPT (Pass 1)
# ============================================

PAIN_EXTRACTION_PROMPT = """
You are a pain-point researcher analyzing raw user language from online communities.
Your job is to extract EVIDENCE of pain and classify it against the Four Questions framework.

## THE FOUR QUESTIONS FRAMEWORK

Every piece of pain evidence should answer at least ONE of these questions:

1. **MANUAL_TASK**: What manual task is causing frustration?
   - Look for: repetitive work, tedious processes, time sinks
   - Example: "I spend 2 hours every week copying data between spreadsheets"

2. **COST_IMPACT**: What does it cost them in time, money, or errors?
   - Look for: quantified losses, missed deadlines, mistakes, financial impact
   - Example: "Lost a $5000 client because I missed the follow-up"

3. **FAILED_SOLUTIONS**: What have they already tried that failed?
   - Look for: tools mentioned negatively, abandoned approaches, "I tried X but..."
   - Example: "Tried Asana, Trello, and Notion but none of them stuck"

4. **IDEAL_STATE**: What would "better" look like in their words?
   - Look for: wishes, "if only", hypothetical solutions, desired outcomes
   - Example: "I just want something that automatically reminds clients"

## HUMAN-CENTERED LENS TAGS

Tag each evidence entry with applicable lenses (can be multiple):

- **trust_issue**: People don't rely on the system ("I double-check everything anyway")
- **cognitive_load**: Too many steps or mental overhead ("I have to remember 10 things")
- **change_resistance**: Process changes cause failure ("My team refuses to use it")
- **error_sensitivity**: Mistakes are costly ("One wrong click and I lose everything")
- **emotional_stakes**: Involves clients, money, compliance, reputation ("My boss would kill me")

## CRITICAL RULES

1. **EXTRACT VERBATIM** - Use their exact words, never paraphrase or summarize
2. **FLAG FOR REMOVAL** - If a passage doesn't answer ANY of the four questions, set flagged_for_removal: true
3. **ONE QUOTE = ONE ENTRY** - Don't combine multiple complaints into one entry
4. **PRESERVE CONTEXT** - Include enough text to understand the pain without the full post
5. **DETECT INDUSTRY** - Infer industry if possible (freelance, agency, ecommerce, saas, consulting, healthcare, real_estate, other)
6. **DETECT EMOTION** - One of: frustrated, overwhelmed, anxious, resigned

## OUTPUT FORMAT

Return JSON with this exact structure:

```json
{
  "pain_evidence": [
    {
      "post_id": 123,
      "verbatim_quote": "I spend 3 hours every Monday morning just organizing my inbox and it drives me crazy",
      "four_questions": {
        "manual_task": "Email inbox organization and sorting",
        "cost_impact": "3 hours per week",
        "failed_solutions": null,
        "ideal_state": null
      },
      "questions_answered": ["manual_task", "cost_impact"],
      "human_lens_tags": ["cognitive_load"],
      "industry": "freelance",
      "emotion": "frustrated",
      "intensity": "medium",
      "ai_confidence": 0.85,
      "flagged_for_removal": false
    }
  ],
  "failed_solutions_detected": [
    {
      "tool_name": "Trello",
      "tool_category": "automation",
      "why_failed": "Too complex for simple task tracking",
      "what_broke_first": "Team stopped updating it",
      "human_behavior": "People reverted to email",
      "mentioned_in_posts": [123, 456]
    }
  ],
  "meta": {
    "total_posts_analyzed": 50,
    "evidence_extracted": 35,
    "flagged_for_removal": 5,
    "dominant_emotion": "frustrated"
  }
}
```

## QUALITY CHECKS BEFORE RESPONDING

- Every verbatim_quote is EXACT text from the post (copy-paste, do not rephrase)
- Every entry answers at least ONE of the four questions (or is flagged)
- Industry inference is reasonable (use null if unclear)
- No solutions or recommendations included
- Human lens tags are justified by the quote content

## POSTS TO ANALYZE

{posts}
"""


# ============================================
# CLUSTER VALIDATION PROMPT (Pass 2)
# ============================================

CLUSTER_VALIDATION_PROMPT = """
You are validating pain evidence and identifying patterns for clustering.

## INPUT
You received extracted pain evidence entries. Your tasks:

1. **VALIDATE** each entry for quality
2. **IDENTIFY CLUSTERS** where 3+ entries share the same core pain
3. **AGGREGATE FAILED SOLUTIONS** across entries

## VALIDATION CRITERIA

For each evidence entry, score:
- **Quote Quality** (0.0-1.0): Is this a genuine complaint with clear pain?
- **Classification Quality** (0.0-1.0): Are the four-question classifications accurate?
- **Specificity** (0.0-1.0): Is this specific enough to act on?

## CLUSTERING RULES

- **MINIMUM 3 ENTRIES** to form a cluster
- Cluster by the PRIMARY pain, not surface keywords
- Name clusters with action verbs: "Struggling to...", "Losing time on...", "Fear of..."
- Do NOT merge distinct pains into vague categories

## OUTPUT FORMAT

```json
{
  "validated_evidence": [
    {
      "evidence_index": 0,
      "quality_score": 0.85,
      "keep": true,
      "adjusted_classifications": {
        "manual_task": "Updated classification if needed",
        "cost_impact": null,
        "failed_solutions": null,
        "ideal_state": null
      },
      "notes": "Clear pain, well-documented"
    }
  ],
  "pain_clusters": [
    {
      "name": "Struggling to maintain consistent follow-up",
      "description": "Users repeatedly losing track of client communications",
      "primary_question": "manual_task",
      "evidence_indices": [0, 3, 7, 12],
      "repeated_manual_tasks": ["client follow-up", "email tracking", "reminder setting"],
      "trigger_moment": "growth or busy season",
      "current_workaround": "Sticky notes and calendar reminders",
      "consequence_of_failure": "Lost clients, missed opportunities",
      "dominant_emotion": "anxious",
      "dominant_lens": "error_sensitivity",
      "industries": ["freelance", "agency"]
    }
  ],
  "aggregated_failed_solutions": [
    {
      "tool_name": "Spreadsheets",
      "tool_category": "manual_process",
      "failure_reasons": ["Too manual", "Easy to forget to update", "No reminders"],
      "frequency": 8
    }
  ],
  "meta": {
    "evidence_kept": 30,
    "evidence_discarded": 5,
    "clusters_formed": 4
  }
}
```

## EVIDENCE TO VALIDATE

{evidence}
"""


# ============================================
# LEGACY PROMPTS (for backward compatibility)
# ============================================

SYNTHESIS_PROMPT = """
You are a qualitative researcher analyzing raw user language from online communities.
Your job is to surface patterns of PAIN, not solutions.

## CRITICAL BEHAVIORAL LOCKS

1. **Suppress novelty** - Only report patterns that appear 3+ times in the data
2. **Prioritize repetition** - Exact phrases matter more than paraphrases
3. **Refuse to brainstorm** - If you catch yourself suggesting solutions, stop immediately
4. **Infer behavior** - Focus on what people actually DID, not what they said they want
5. **Preserve their language** - Use their words, not your interpretation

## FORBIDDEN ACTIONS

- DO NOT propose solutions, products, or improvements
- DO NOT interpret or editorialize beyond the evidence
- DO NOT merge distinct pain points into vague categories
- DO NOT include pains that only appear once or twice
- DO NOT speculate about what they "might" want

## Your Task

Analyze these posts and identify recurring THEMES of pain or frustration.

For each theme, determine:
1. **Name**: Short descriptive name (2-4 words)
2. **Description**: The core complaint in THEIR words (not your interpretation)
3. **Intensity**: High, Medium, or Low based on emotional language
4. **Emotional Tone**: Frustration, Shame, Overwhelm, Anxiety, or Resignation
5. **Representative Quotes**: 3-5 exact quotes capturing the theme
6. **Post IDs**: Which posts belong to this theme

## Output Format

Return a JSON object with this exact structure:

```json
{
  "themes": [
    {
      "name": "Theme Name Here",
      "description": "Core complaint in their words",
      "intensity": "high",
      "emotional_tone": "Frustration",
      "quotes": ["exact quote 1", "exact quote 2", "exact quote 3"],
      "post_ids": [1, 5, 12, 34]
    }
  ],
  "discovered_keywords": ["potential keyword 1", "potential keyword 2"],
  "meta": {
    "total_posts_analyzed": 50,
    "dominant_emotion": "Frustration"
  }
}
```

## Quality Checks

Before responding, verify:
- Every theme appears in at least 3 posts
- Quotes are EXACT text, not paraphrased
- No solutions or recommendations slipped in
- Distinct pains are NOT merged into vague categories

## Posts to Analyze

{posts}
"""

VALIDATION_PROMPT = """
You are validating themes extracted from user complaints for quality and accuracy.

## Input
You received candidate themes extracted from posts. For each theme, evaluate:

1. **Evidence Quality** (0.0-1.0): Are the quotes truly representative of the theme?
2. **Pattern Strength** (0.0-1.0): How consistent is this pattern across posts?
3. **Distinctiveness** (0.0-1.0): Is this theme clearly different from others?
4. **Actionability** (0.0-1.0): Is this specific enough to act on?

## Output Format

Return JSON with validated themes:

```json
{
  "validated_themes": [
    {
      "name": "Original Theme Name",
      "confidence_score": 0.85,
      "scores": {
        "evidence_quality": 0.9,
        "pattern_strength": 0.8,
        "distinctiveness": 0.85,
        "actionability": 0.85
      },
      "recommended_action": "keep",
      "notes": "Brief validation notes"
    }
  ]
}
```

## Rules
- Set confidence_score = average of the 4 component scores
- recommended_action: "keep" (confidence >= 0.5), "discard" (confidence < 0.5)
- Be critical - only high-quality themes should pass validation

## Themes to Validate

{themes}
"""


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_unprocessed_posts(topic_id: int, limit: int = 100) -> list:
    """Get posts that haven't been processed yet."""
    conn = database.get_connection()
    cursor = conn.cursor()

    # Get posts with processed = 0 (or NULL for legacy data)
    cursor.execute("""
        SELECT p.id, p.title, p.content, p.source, p.url
        FROM posts p
        WHERE p.topic_id = ?
        AND (p.processed = 0 OR p.processed IS NULL)
        ORDER BY p.scraped_at DESC
        LIMIT ?
    """, (topic_id, limit))

    posts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return posts


def mark_posts_processed(post_ids: list):
    """Mark posts as processed after synthesis."""
    if not post_ids:
        return
    conn = database.get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" * len(post_ids))
    cursor.execute(f"UPDATE posts SET processed = 1 WHERE id IN ({placeholders})", post_ids)
    conn.commit()
    conn.close()


def determine_intensity(content: str, config: dict) -> str:
    """Determine intensity based on config keywords."""
    content_lower = content.lower()
    intensity_keywords = config["synthesis"]["intensity_keywords"]

    high_count = sum(1 for kw in intensity_keywords["high"] if kw in content_lower)
    medium_count = sum(1 for kw in intensity_keywords["medium"] if kw in content_lower)
    low_count = sum(1 for kw in intensity_keywords["low"] if kw in content_lower)

    if high_count > 0:
        return "high"
    elif medium_count > 0:
        return "medium"
    else:
        return "low"


def format_posts_for_prompt(posts: list) -> str:
    """Format posts for inclusion in the prompt."""
    formatted = []
    for post in posts:
        formatted.append(f"[Post ID: {post['id']}]\n"
                        f"Source: {post['source']}\n"
                        f"Title: {post['title']}\n"
                        f"Content: {post['content']}\n")
    return "\n---\n".join(formatted)


def parse_claude_response(response_text: str) -> dict | None:
    """Extract JSON from Claude's response."""
    # Try to find JSON in the response
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try parsing the whole response as JSON
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        print("Failed to parse Claude response as JSON")
        print(f"Response preview: {response_text[:500]}...")
        return None


def save_themes(themes: list, topic_id: int, config: dict) -> int:
    """Save extracted themes to database. Returns number saved."""
    conn = database.get_connection()
    cursor = conn.cursor()
    saved_count = 0

    for theme in themes:
        try:
            post_ids = theme.get("post_ids", [])

            # Determine intensity if not provided
            intensity = theme.get("intensity", "medium")
            if isinstance(intensity, str):
                intensity = intensity.lower()
            if intensity not in ("low", "medium", "high"):
                intensity = "medium"

            # Get theme name - handle different formats
            name = theme.get("name") or theme.get("theme_name") or "Unnamed Theme"

            # Get confidence score from validation (default 0.6 if not present)
            confidence_score = theme.get("confidence_score", 0.6)

            # Insert theme
            cursor.execute("""
                INSERT INTO themes (topic_id, name, description, intensity, emotional_tone, post_count, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                topic_id,
                name,
                theme.get("description", ""),
                intensity,
                theme.get("emotional_tone", ""),
                len(post_ids) if post_ids else 0,
                confidence_score
            ))
            theme_id = cursor.lastrowid
            saved_count += 1

            # Link posts to theme (if post_ids are valid)
            for i, post_id in enumerate(post_ids):
                try:
                    # Ensure post_id is an integer
                    post_id = int(post_id)
                    relevance = max(0.1, 1.0 - (i * 0.1))
                    cursor.execute("""
                        INSERT OR IGNORE INTO theme_posts (theme_id, post_id, relevance_score)
                        VALUES (?, ?, ?)
                    """, (theme_id, post_id, relevance))
                except (ValueError, TypeError):
                    continue
                except Exception as e:
                    continue

            print(f"  Saved theme: '{name}' ({len(post_ids) if post_ids else 0} posts)")

        except Exception as e:
            print(f"  Error saving theme: {e}")
            continue

    conn.commit()
    conn.close()
    return saved_count


def save_discovered_keywords(keywords: list, topic_id: int):
    """Save discovered keywords. Only inserts new ones, doesn't increment existing."""
    conn = database.get_connection()
    cursor = conn.cursor()

    for keyword in keywords:
        keyword = keyword.strip().lower()
        if len(keyword) < 5:  # Skip very short keywords
            continue

        try:
            # Only insert if new - don't increment count on duplicates
            cursor.execute("""
                INSERT OR IGNORE INTO discovered_keywords (topic_id, keyword)
                VALUES (?, ?)
            """, (topic_id, keyword))
        except Exception as e:
            print(f"  Warning: Could not save keyword '{keyword}': {e}")

    conn.commit()
    conn.close()


def batch_synthesize(posts: list, config: dict) -> dict | None:
    """Send a batch of posts to Claude for analysis with retry logic.

    Uses circuit breaker to prevent runaway API costs.
    """
    cb = get_circuit_breaker()

    # Check circuit breaker before making API call
    if cb.is_open():
        print("  Circuit breaker is OPEN - skipping API call")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return None
    client = Anthropic(api_key=api_key)

    formatted_posts = format_posts_for_prompt(posts)
    prompt = SYNTHESIS_PROMPT.replace("{posts}", formatted_posts)

    for attempt in range(MAX_RETRIES):
        # Re-check circuit breaker on each retry
        if cb.is_open():
            print("  Circuit breaker opened during retries - aborting")
            return None

        try:
            response = client.messages.create(
                model=config["anthropic"]["model"],
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.content[0].text
            result = parse_claude_response(response_text)

            # Record success with token usage
            usage = response.usage
            cb.record_success(
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0
            )

            if result is None:
                print(f"  Parse failed, response preview: {response_text[:300]}...")

            return result

        except (APIError, RateLimitError, APIConnectionError) as e:
            cb.record_failure(e)
            delay = RETRY_DELAY * (2 ** attempt)
            print(f"  Claude API error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1 and not cb.is_open():
                print(f"  Retrying in {delay}s...")
                time.sleep(delay)
            else:
                print("  Max retries reached or circuit open, giving up.")
                return None
        except Exception as e:
            # Non-API errors - don't count against circuit breaker
            print(f"  Unexpected error: {e}")
            return None

    return None


def validate_themes(themes: list, config: dict) -> list:
    """
    Second pass: Validate themes and assign confidence scores.

    Returns themes with confidence_score added, filtered to keep only valid ones.
    Uses circuit breaker to prevent runaway API costs.
    """
    if not themes:
        return []

    cb = get_circuit_breaker()

    # Check circuit breaker - return defaults if open
    if cb.is_open():
        print("  Circuit breaker is OPEN - using default confidence")
        for theme in themes:
            theme["confidence_score"] = 0.6
        return themes

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # If no API key, return themes with default confidence
        for theme in themes:
            theme["confidence_score"] = 0.6
        return themes

    client = Anthropic(api_key=api_key)

    # Format themes for validation
    themes_json = json.dumps(themes, indent=2)
    prompt = VALIDATION_PROMPT.replace("{themes}", themes_json)

    try:
        print("  Pass 2: Validating themes...")
        response = client.messages.create(
            model=config["anthropic"]["model"],
            max_tokens=2048,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = response.content[0].text
        result = parse_claude_response(response_text)

        # Record success with token usage
        usage = response.usage
        cb.record_success(
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0
        )

        if not result or "validated_themes" not in result:
            # Validation failed, return themes with default confidence
            print("  Validation parse failed, using default confidence")
            for theme in themes:
                theme["confidence_score"] = 0.6
            return themes

        # Merge validation results back into themes
        validation_map = {
            v["name"]: v for v in result.get("validated_themes", [])
        }

        validated_themes = []
        for theme in themes:
            theme_name = theme.get("name", "")
            validation = validation_map.get(theme_name)

            if validation:
                theme["confidence_score"] = validation.get("confidence_score", 0.6)
                action = validation.get("recommended_action", "keep")
                if action == "keep":
                    validated_themes.append(theme)
                else:
                    print(f"    Discarded theme: '{theme_name}' (low confidence)")
            else:
                # Theme not in validation results, keep with default confidence
                theme["confidence_score"] = 0.5
                validated_themes.append(theme)

        print(f"  Validated {len(validated_themes)}/{len(themes)} themes")
        return validated_themes

    except (APIError, RateLimitError, APIConnectionError) as e:
        cb.record_failure(e)
        print(f"  Validation API error: {e}, using default confidence")
        for theme in themes:
            theme["confidence_score"] = 0.6
        return themes
    except Exception as e:
        print(f"  Validation error: {e}, using default confidence")
        for theme in themes:
            theme["confidence_score"] = 0.6
        return themes


def batch_synthesize_multipass(posts: list, config: dict) -> dict | None:
    """
    Multi-pass synthesis: extract themes, then validate.

    Pass 1: Extract candidate themes from posts
    Pass 2: Validate themes and assign confidence scores
    """
    # Pass 1: Extract themes
    print("  Pass 1: Extracting themes...")
    result = batch_synthesize(posts, config)

    if not result:
        return None

    themes = result.get("themes", [])
    if not themes:
        return result

    # Pass 2: Validate themes
    validated_themes = validate_themes(themes, config)

    # Update result with validated themes
    result["themes"] = validated_themes
    result["meta"] = result.get("meta", {})
    result["meta"]["themes_before_validation"] = len(themes)
    result["meta"]["themes_after_validation"] = len(validated_themes)

    return result


# ============================================
# PAIN INTELLIGENCE FUNCTIONS
# ============================================

def extract_pain_evidence(posts: list, config: dict) -> dict | None:
    """
    Pass 1: Extract pain evidence from posts using the four-question framework.

    Returns dict with pain_evidence, failed_solutions_detected, and meta.
    Uses circuit breaker to prevent runaway API costs.
    """
    cb = get_circuit_breaker()

    # Check circuit breaker before making API call
    if cb.is_open():
        print("  Circuit breaker is OPEN - skipping API call")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return None

    client = Anthropic(api_key=api_key)
    formatted_posts = format_posts_for_prompt(posts)
    prompt = PAIN_EXTRACTION_PROMPT.replace("{posts}", formatted_posts)

    for attempt in range(MAX_RETRIES):
        # Re-check circuit breaker on each retry
        if cb.is_open():
            print("  Circuit breaker opened during retries - aborting")
            return None

        try:
            response = client.messages.create(
                model=config["anthropic"]["model"],
                max_tokens=8192,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.content[0].text
            result = parse_claude_response(response_text)

            # Record success with token usage
            usage = response.usage
            cb.record_success(
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0
            )

            if result is None:
                print(f"  Parse failed, response preview: {response_text[:300]}...")

            return result

        except (APIError, RateLimitError, APIConnectionError) as e:
            cb.record_failure(e)
            delay = RETRY_DELAY * (2 ** attempt)
            print(f"  Claude API error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1 and not cb.is_open():
                print(f"  Retrying in {delay}s...")
                time.sleep(delay)
            else:
                print("  Max retries reached or circuit open, giving up.")
                return None
        except Exception as e:
            # Non-API errors (parsing, etc.) - don't count against circuit breaker
            print(f"  Unexpected error: {e}")
            return None

    return None


def validate_and_cluster(evidence_list: list, config: dict) -> dict | None:
    """
    Pass 2: Validate evidence and identify clusters.

    Only creates clusters when 3+ evidence entries share the same pain.
    Uses circuit breaker to prevent runaway API costs.
    """
    if not evidence_list:
        return None

    cb = get_circuit_breaker()

    # Check circuit breaker - return defaults if open
    if cb.is_open():
        print("  Circuit breaker is OPEN - using default validation")
        return {
            "validated_evidence": [
                {"evidence_index": i, "quality_score": 0.6, "keep": True}
                for i in range(len(evidence_list))
            ],
            "pain_clusters": [],
            "aggregated_failed_solutions": []
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Return evidence with default quality scores
        return {
            "validated_evidence": [
                {"evidence_index": i, "quality_score": 0.7, "keep": True}
                for i in range(len(evidence_list))
            ],
            "pain_clusters": [],
            "aggregated_failed_solutions": []
        }

    client = Anthropic(api_key=api_key)
    evidence_json = json.dumps(evidence_list, indent=2)
    prompt = CLUSTER_VALIDATION_PROMPT.replace("{evidence}", evidence_json)

    try:
        print("  Pass 2: Validating evidence and clustering...")
        response = client.messages.create(
            model=config["anthropic"]["model"],
            max_tokens=4096,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = response.content[0].text
        result = parse_claude_response(response_text)

        # Record success with token usage
        usage = response.usage
        cb.record_success(
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0
        )

        if not result:
            print("  Validation parse failed, using defaults")
            return {
                "validated_evidence": [
                    {"evidence_index": i, "quality_score": 0.6, "keep": True}
                    for i in range(len(evidence_list))
                ],
                "pain_clusters": [],
                "aggregated_failed_solutions": []
            }

        return result

    except (APIError, RateLimitError, APIConnectionError) as e:
        cb.record_failure(e)
        print(f"  Validation API error: {e}")
        return None
    except Exception as e:
        print(f"  Validation error: {e}")
        return None


def save_pain_evidence(evidence_list: list, validation_result: dict, topic_id: int, posts: list) -> dict:
    """
    Save extracted pain evidence to the database.

    Returns dict with counts of saved, flagged, and discarded evidence.
    """
    stats = {"saved": 0, "flagged": 0, "discarded": 0}

    # Build validation lookup
    validation_map = {}
    if validation_result and "validated_evidence" in validation_result:
        for v in validation_result["validated_evidence"]:
            validation_map[v.get("evidence_index", -1)] = v

    # Build post lookup for source URLs
    post_lookup = {p["id"]: p for p in posts}

    for i, evidence in enumerate(evidence_list):
        try:
            # Get validation info
            validation = validation_map.get(i, {"quality_score": 0.6, "keep": True})

            if not validation.get("keep", True):
                stats["discarded"] += 1
                continue

            # Get four questions
            four_q = evidence.get("four_questions", {})

            # Check if should be flagged
            flagged = evidence.get("flagged_for_removal", False)
            if not flagged:
                # Also flag if no questions answered
                has_answer = any([
                    four_q.get("manual_task"),
                    four_q.get("cost_impact"),
                    four_q.get("failed_solutions"),
                    four_q.get("ideal_state")
                ])
                flagged = not has_answer

            # Get post info
            post_id = evidence.get("post_id")
            source_url = None
            source = "unknown"
            if post_id and post_id in post_lookup:
                post = post_lookup[post_id]
                source_url = post.get("url")
                source = post.get("source", "unknown")

            # Apply adjusted classifications from validation
            adjusted = validation.get("adjusted_classifications", {})

            # Save to database
            evidence_id = database.add_pain_evidence(
                topic_id=topic_id,
                verbatim_quote=evidence.get("verbatim_quote", ""),
                source=source,
                post_id=post_id,
                source_url=source_url,
                manual_task=adjusted.get("manual_task") or four_q.get("manual_task"),
                cost_impact=adjusted.get("cost_impact") or four_q.get("cost_impact"),
                failed_solutions=adjusted.get("failed_solutions") or four_q.get("failed_solutions"),
                ideal_state=adjusted.get("ideal_state") or four_q.get("ideal_state"),
                human_lens_tags=evidence.get("human_lens_tags", []),
                industry=evidence.get("industry"),
                emotion=evidence.get("emotion"),
                intensity=evidence.get("intensity"),
                ai_confidence=validation.get("quality_score", evidence.get("ai_confidence", 0.6)),
                flagged_for_removal=flagged
            )

            if flagged:
                stats["flagged"] += 1
            else:
                stats["saved"] += 1

        except Exception as e:
            print(f"  Error saving evidence: {e}")
            continue

    return stats


def save_pain_clusters(clusters: list, evidence_list: list, topic_id: int) -> int:
    """
    Save pain clusters to the database.

    Only saves clusters with 3+ evidence entries.
    Returns count of clusters saved.
    """
    saved = 0

    for cluster in clusters:
        evidence_indices = cluster.get("evidence_indices", [])

        # Only save clusters with 3+ evidence
        if len(evidence_indices) < 3:
            continue

        try:
            cluster_id = database.add_pain_cluster(
                topic_id=topic_id,
                name=cluster.get("name", "Unnamed Cluster"),
                description=cluster.get("description"),
                repeated_manual_tasks=cluster.get("repeated_manual_tasks", []),
                trigger_moment=cluster.get("trigger_moment"),
                current_workaround=cluster.get("current_workaround"),
                consequence_of_failure=cluster.get("consequence_of_failure"),
                primary_question=cluster.get("primary_question"),
                dominant_emotion=cluster.get("dominant_emotion"),
                dominant_lens=cluster.get("dominant_lens"),
                industries=cluster.get("industries", []),
                intensity=cluster.get("intensity")
            )

            # Link evidence to cluster
            # Note: evidence_indices refer to positions in the evidence_list
            # We need to look up the actual evidence IDs from the database
            # For now, we'll link based on the order they were saved

            saved += 1
            print(f"    Saved cluster: '{cluster.get('name')}' ({len(evidence_indices)} evidence)")

        except Exception as e:
            print(f"  Error saving cluster: {e}")
            continue

    return saved


def save_extracted_failed_solutions(solutions: list, topic_id: int) -> int:
    """
    Save failed solutions detected during extraction.

    Returns count of solutions saved/updated.
    """
    saved = 0

    for solution in solutions:
        try:
            database.add_failed_solution(
                topic_id=topic_id,
                tool_tried=solution.get("tool_name", "Unknown"),
                tool_category=solution.get("tool_category"),
                why_failed=solution.get("why_failed"),
                what_broke_first=solution.get("what_broke_first"),
                human_behavior_involved=solution.get("human_behavior")
            )
            saved += 1
        except Exception as e:
            print(f"  Error saving failed solution: {e}")
            continue

    return saved


def run_pain_intelligence_synthesis(topic_name: str = None, process_all: bool = False) -> dict:
    """
    Main entry point for pain intelligence synthesis.

    Extracts pain evidence, validates, clusters, and saves to database.

    Args:
        topic_name: Topic to process (or first topic if None)
        process_all: If True, process all batches; if False, process one batch

    Returns dict with synthesis statistics.
    """
    config = load_config()
    database.init_database()

    # Get topic ID
    conn = database.get_connection()
    cursor = conn.cursor()

    if topic_name:
        cursor.execute("SELECT id, name FROM topics WHERE name = ?", (topic_name,))
    else:
        cursor.execute("SELECT id, name FROM topics LIMIT 1")

    row = cursor.fetchone()
    conn.close()

    if not row:
        print(f"Topic '{topic_name}' not found in database.")
        return {"error": "Topic not found"}

    topic_id = row["id"]
    topic_name = row["name"]

    print(f"\n=== Pain Intelligence Synthesis for: {topic_name} ===")

    stats = {
        "posts_processed": 0,
        "evidence_saved": 0,
        "evidence_flagged": 0,
        "evidence_discarded": 0,
        "clusters_created": 0,
        "failed_solutions_found": 0,
        "batches_run": 0
    }

    batch_size = config["synthesis"]["batch_size"]

    while True:
        # Get unprocessed posts
        posts = get_unprocessed_posts(topic_id, limit=batch_size)

        if not posts:
            print("No more unprocessed posts.")
            break

        post_ids = [p["id"] for p in posts]
        print(f"\nProcessing batch of {len(posts)} posts...")
        stats["posts_processed"] += len(posts)

        # Pass 1: Extract pain evidence
        print("  Pass 1: Extracting pain evidence...")
        extraction_result = extract_pain_evidence(posts, config)

        if not extraction_result:
            print("  Failed to extract pain evidence")
            continue

        evidence_list = extraction_result.get("pain_evidence", [])
        failed_solutions = extraction_result.get("failed_solutions_detected", [])

        print(f"  Extracted {len(evidence_list)} evidence entries")

        if evidence_list:
            # Pass 2: Validate and cluster
            validation_result = validate_and_cluster(evidence_list, config)

            # Save evidence
            evidence_stats = save_pain_evidence(evidence_list, validation_result, topic_id, posts)
            stats["evidence_saved"] += evidence_stats["saved"]
            stats["evidence_flagged"] += evidence_stats["flagged"]
            stats["evidence_discarded"] += evidence_stats["discarded"]

            # Save clusters (only if validation found them)
            if validation_result and "pain_clusters" in validation_result:
                clusters = validation_result.get("pain_clusters", [])
                if clusters:
                    saved_clusters = save_pain_clusters(clusters, evidence_list, topic_id)
                    stats["clusters_created"] += saved_clusters

            # Save aggregated failed solutions from validation
            if validation_result and "aggregated_failed_solutions" in validation_result:
                agg_solutions = validation_result.get("aggregated_failed_solutions", [])
                for sol in agg_solutions:
                    database.add_failed_solution(
                        topic_id=topic_id,
                        tool_tried=sol.get("tool_name", "Unknown"),
                        tool_category=sol.get("tool_category"),
                        why_failed="; ".join(sol.get("failure_reasons", []))
                    )

        # Save failed solutions from extraction
        if failed_solutions:
            saved_solutions = save_extracted_failed_solutions(failed_solutions, topic_id)
            stats["failed_solutions_found"] += saved_solutions

        # Mark posts as processed ONLY after all saves complete successfully
        # This ensures failed batches can be retried
        mark_posts_processed(post_ids)

        stats["batches_run"] += 1

        # If not processing all, break after first batch
        if not process_all:
            break

    print("\n=== Pain Intelligence Synthesis Complete ===")
    print(f"  Posts processed: {stats['posts_processed']}")
    print(f"  Evidence saved: {stats['evidence_saved']}")
    print(f"  Evidence flagged: {stats['evidence_flagged']}")
    print(f"  Evidence discarded: {stats['evidence_discarded']}")
    print(f"  Clusters created: {stats['clusters_created']}")
    print(f"  Failed solutions found: {stats['failed_solutions_found']}")
    print(f"  Batches run: {stats['batches_run']}")

    return stats


def run_synthesis(topic_name: str = None, process_all: bool = False) -> dict:
    """
    Main synthesis entry point.

    Processes posts in batches and extracts themes.
    Args:
        topic_name: Topic to process (or first topic if None)
        process_all: If True, process all batches; if False, process one batch
    Returns dict with synthesis statistics.
    """
    config = load_config()
    database.init_database()

    # Get topic ID
    conn = database.get_connection()
    cursor = conn.cursor()

    if topic_name:
        cursor.execute("SELECT id, name FROM topics WHERE name = ?", (topic_name,))
    else:
        cursor.execute("SELECT id, name FROM topics LIMIT 1")

    row = cursor.fetchone()
    conn.close()

    if not row:
        print(f"Topic '{topic_name}' not found in database.")
        return {"error": "Topic not found"}

    topic_id = row["id"]
    topic_name = row["name"]

    print(f"\nSynthesizing themes for: {topic_name}")

    stats = {
        "posts_processed": 0,
        "themes_created": 0,
        "keywords_discovered": 0,
        "batches_run": 0
    }

    batch_size = config["synthesis"]["batch_size"]

    while True:
        # Get unprocessed posts
        posts = get_unprocessed_posts(topic_id, limit=batch_size)

        if not posts:
            print("No more unprocessed posts.")
            break

        post_ids = [p["id"] for p in posts]
        print(f"\nProcessing batch of {len(posts)} posts...")
        stats["posts_processed"] += len(posts)

        # Send to Claude (multi-pass: extract then validate)
        result = batch_synthesize_multipass(posts, config)

        # Mark posts as processed regardless of result to avoid reprocessing
        mark_posts_processed(post_ids)

        if result:
            # Debug: show what Claude returned
            print(f"  Claude returned: {list(result.keys())}")

            # Save themes
            themes = result.get("themes", [])
            if themes:
                print(f"  Found {len(themes)} themes in response")
                saved = save_themes(themes, topic_id, config)
                stats["themes_created"] += saved
            else:
                print("  No themes found in Claude response")

            # Save discovered keywords
            keywords = result.get("discovered_keywords", [])
            if keywords:
                save_discovered_keywords(keywords, topic_id)
                stats["keywords_discovered"] += len(keywords)

            stats["batches_run"] += 1
        else:
            print("  Failed to get valid response from Claude")

        # If not processing all, break after first batch
        if not process_all:
            break

    print("\nSynthesis complete!")
    print(f"  Posts processed: {stats['posts_processed']}")
    print(f"  Themes created: {stats['themes_created']}")
    print(f"  Keywords discovered: {stats['keywords_discovered']}")
    print(f"  Batches run: {stats['batches_run']}")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthesize themes from scraped posts")
    parser.add_argument("--topic", type=str, help="Topic name to synthesize")
    parser.add_argument(
        "--all", action="store_true",
        help="Process all unprocessed posts (not just one batch)"
    )
    parser.add_argument(
        "--mode", type=str, choices=["legacy", "pain"], default="pain",
        help="Synthesis mode: 'legacy' for themes, 'pain' for pain intelligence (default: pain)"
    )
    args = parser.parse_args()

    if args.mode == "pain":
        run_pain_intelligence_synthesis(args.topic, process_all=args.all)
    else:
        run_synthesis(args.topic, process_all=args.all)
