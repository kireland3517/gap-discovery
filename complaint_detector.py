"""
Complaint detection module for Research Pattern Discovery System.

Detects actual complaints vs casual mentions using:
- Emotional signals (frustration, resignation, seeking help)
- Problem-seeking patterns (regex-based)
- Topic relevance (derived from keywords)

Scoring: 0.4*emotional + 0.35*problem_pattern + 0.25*topic_relevance
Threshold: >= 0.5 to be considered a complaint
"""

import re

# Emotional complaint signals by intensity
EMOTIONAL_SIGNALS = {
    "high_frustration": [
        "hate", "frustrated", "furious", "infuriating", "nightmare",
        "impossible", "ridiculous", "absurd", "terrible", "worst",
        "awful", "horrible", "disaster", "pathetic", "unbearable"
    ],
    "moderate_frustration": [
        "annoying", "annoyed", "stuck", "struggling", "confusing",
        "confused", "disappointed", "broken", "useless", "waste",
        "difficult", "hard", "problem", "issue", "bug", "error"
    ],
    "resignation": [
        "gave up", "giving up", "quit", "abandoned", "stopped using",
        "switched to", "moved away", "never again", "done with",
        "can't anymore", "had enough", "fed up"
    ],
    "seeking_help": [
        "help me", "can anyone", "does anyone know", "am i the only one",
        "is it just me", "please help", "desperate", "need help",
        "any suggestions", "what should i do", "how do i"
    ]
}

# Problem-seeking regex patterns
PROBLEM_PATTERNS = [
    r"\bwhy\s+(does|doesn't|won't|can't|is|isn't)\b",
    r"\bhow\s+do\s+i\s+(fix|solve|get|stop|make)\b",
    r"\bhelp\s+with\b",
    r"\bproblem\s+with\b",
    r"\bissue\s+with\b",
    r"\bstruggling\s+(to|with)\b",
    r"\bcan't\s+(figure|understand|get|make|find)\b",
    r"\bdoesn't\s+work\b",
    r"\bnot\s+working\b",
    r"\bbroken\b",
    r"\bbug\b",
    r"\berror\b",
    r"\bfailing\b",
    r"\bfailed\b",
    r"\bwon't\s+(let|allow|work|load)\b",
    r"\bkeeps?\s+(crashing|failing|breaking)\b",
    r"\banyone\s+else\s+(having|experiencing|getting)\b"
]

# Stopwords for topic term extraction
# YouTube / Algolia HN / Quora hits are often questions or discussion without
# "frustrated" wording; they still match seed keywords. Scrape layer can use
# should_save_scraped_post() to retain keyword-grounded discovery posts.
OFFSITE_DISCOVERY_SOURCES = frozenset({"youtube", "hackernews", "quora"})

STOPWORDS = {
    'a', 'an', 'the', 'is', 'it', 'to', 'for', 'my', 'i', 'me',
    'vs', 'or', 'and', 'of', 'in', 'on', 'at', 'by', 'with', 'from',
    'that', 'this', 'be', 'are', 'was', 'were', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'can'
}


def extract_topic_terms(topic_keywords: list) -> set:
    """Extract unique meaningful words from all topic keywords."""
    terms = set()
    for kw in topic_keywords:
        for word in kw.lower().split():
            if len(word) > 3 and word not in STOPWORDS:
                terms.add(word)
    return terms


def calculate_emotional_score(content: str) -> float:
    """
    Calculate emotional complaint score (0.0-1.0).

    Higher scores for high frustration signals, weighted by intensity.
    """
    content_lower = content.lower()

    # Count matches by intensity level
    high_matches = sum(
        1 for signal in EMOTIONAL_SIGNALS["high_frustration"]
        if signal in content_lower
    )
    moderate_matches = sum(
        1 for signal in EMOTIONAL_SIGNALS["moderate_frustration"]
        if signal in content_lower
    )
    resignation_matches = sum(
        1 for signal in EMOTIONAL_SIGNALS["resignation"]
        if signal in content_lower
    )
    help_matches = sum(
        1 for signal in EMOTIONAL_SIGNALS["seeking_help"]
        if signal in content_lower
    )

    # Weighted scoring
    # High frustration = 1.0, Moderate = 0.6, Resignation = 0.8, Seeking help = 0.7
    weighted_score = (
        high_matches * 1.0 +
        moderate_matches * 0.6 +
        resignation_matches * 0.8 +
        help_matches * 0.7
    )

    # Normalize to 0-1 range (cap at 3 weighted matches = 1.0)
    return min(1.0, weighted_score / 3.0)


def calculate_problem_score(content: str) -> float:
    """
    Calculate problem-seeking pattern score (0.0-1.0).

    Counts regex pattern matches indicating user is seeking help with a problem.
    """
    content_lower = content.lower()

    matches = sum(
        1 for pattern in PROBLEM_PATTERNS
        if re.search(pattern, content_lower)
    )

    # Normalize to 0-1 range (cap at 4 pattern matches = 1.0)
    return min(1.0, matches / 4.0)


def calculate_topic_score(content: str, keyword: str, topic_keywords: list) -> float:
    """
    Calculate topic relevance score (0.0-1.0).

    Checks how many topic-derived terms appear in content.
    """
    content_lower = content.lower()

    # Extract terms from all topic keywords
    topic_terms = extract_topic_terms(topic_keywords)

    # Count keyword word matches (words > 3 chars from search keyword)
    keyword_words = keyword.lower().split()
    keyword_matches = sum(
        1 for word in keyword_words
        if len(word) > 3 and word in content_lower
    )

    # Count topic term matches
    topic_matches = sum(
        1 for term in topic_terms
        if term in content_lower
    )

    # Combined score: keyword matches are more important
    # 2 keyword words or 4 topic terms = 1.0
    keyword_score = min(1.0, keyword_matches / 2.0)
    topic_score = min(1.0, topic_matches / 4.0)

    # Weighted combination (keyword match more important)
    return keyword_score * 0.6 + topic_score * 0.4


def is_complaint(content: str, keyword: str, topic_keywords: list) -> tuple:
    """
    Determine if content is a complaint and calculate confidence score.

    Args:
        content: The post content to analyze
        keyword: The search keyword used to find this content
        topic_keywords: All keywords for the topic (for context)

    Returns:
        tuple: (is_complaint: bool, confidence_score: float 0.0-1.0)

    Scoring weights:
        - Emotional signals: 40%
        - Problem patterns: 35%
        - Topic relevance: 25%

    Threshold: score >= 0.5 to be considered a complaint
    """
    emotional_score = calculate_emotional_score(content)
    problem_score = calculate_problem_score(content)
    topic_score = calculate_topic_score(content, keyword, topic_keywords)

    # Weighted combination
    weighted_score = (
        emotional_score * 0.4 +
        problem_score * 0.35 +
        topic_score * 0.25
    )

    # Boost: If high emotional + problem pattern, almost certainly a complaint
    if emotional_score > 0.6 and problem_score > 0.5:
        weighted_score = min(1.0, weighted_score * 1.2)

    # Penalty: If no emotional or problem signals, likely not a complaint
    if emotional_score < 0.1 and problem_score < 0.1:
        weighted_score *= 0.5

    is_complaint_result = weighted_score >= 0.5

    return (is_complaint_result, round(weighted_score, 3))


def should_save_scraped_post(
    content: str,
    keyword: str,
    topic_keywords: list,
    source: str,
    *,
    use_offsite_discovery_gate: bool = True,
    discovery_topic_threshold: float = 0.28,
    discovery_min_chars: int = 20,
) -> tuple:
    """
    Whether to persist a scraped post. Uses complaint heuristics first; for
    YouTube / Hacker News / Quora optionally keeps keyword-relevant text even
    when it does not read like an explicit complaint (common for Q&A and titles).
    """
    is_comp, score = is_complaint(content, keyword, topic_keywords)
    if is_comp:
        return (True, score)
    if not use_offsite_discovery_gate:
        return (False, score)
    src = (source or "").strip().lower()
    if src not in OFFSITE_DISCOVERY_SOURCES:
        return (False, score)
    text = content.strip()
    if len(text) < discovery_min_chars:
        return (False, score)
    ts = calculate_topic_score(content, keyword, topic_keywords)
    if ts >= discovery_topic_threshold:
        return (True, max(score, 0.42))
    return (False, score)


# Convenience function for testing
def analyze_content(content: str, keyword: str, topic_keywords: list) -> dict:
    """
    Get detailed analysis breakdown for debugging/testing.

    Returns dict with all component scores.
    """
    emotional = calculate_emotional_score(content)
    problem = calculate_problem_score(content)
    topic = calculate_topic_score(content, keyword, topic_keywords)
    is_comp, score = is_complaint(content, keyword, topic_keywords)

    return {
        "is_complaint": is_comp,
        "confidence_score": score,
        "breakdown": {
            "emotional_score": round(emotional, 3),
            "problem_score": round(problem, 3),
            "topic_score": round(topic, 3)
        }
    }
