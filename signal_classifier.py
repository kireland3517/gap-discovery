"""
Gap Discovery OS - Signal Type Classifier
==========================================
Auto-classifies raw signals into pain categories based on language patterns.

Categories:
- Complaint: General frustration, annoyance
- Abandonment: Gave up, stopped using, switched away
- Workaround: DIY solutions, hacks, "I ended up..."
- Shame/Self-blame: "I should be able to", "why can't I", self-criticism
- Tool blame: Blaming the app/tool/service

Usage:
    from signal_classifier import classify_signal
    signal_type = classify_signal("I gave up trying to use this app")
    # Returns: "Abandonment"
"""

import re
from typing import Optional

# Pattern definitions for each signal type
# Ordered by specificity - more specific patterns first

ABANDONMENT_PATTERNS = [
    r"\bgave up\b",
    r"\bgiving up\b",
    r"\bgiven up\b",
    r"\bstopped using\b",
    r"\bquit using\b",
    r"\bswitched to\b",
    r"\bswitched from\b",
    r"\bmoved to\b",
    r"\bmoved away\b",
    r"\buninstalled\b",
    r"\bdeleted the app\b",
    r"\bcanceled my\b",
    r"\bcancelled my\b",
    r"\bno longer use\b",
    r"\bdon'?t use .* anymore\b",
    r"\bwent back to\b",
    r"\bwent with\b",
    r"\babandoned\b",
    r"\bdropped\b",
    r"\bditched\b",
    r"\blast straw\b",
    r"\bfinal straw\b",
    r"\bdone with\b",
    r"\bover it\b",
]

WORKAROUND_PATTERNS = [
    r"\bworkaround\b",
    r"\bwork around\b",
    r"\bhack\b",
    r"\bi ended up\b",
    r"\bended up using\b",
    r"\bmy solution\b",
    r"\bwhat i do is\b",
    r"\bwhat works for me\b",
    r"\bi just use\b",
    r"\bi resorted to\b",
    r"\bmanual(ly)?\b",
    r"\binstead i\b",
    r"\bso instead\b",
    r"\bi found a way\b",
    r"\bi figured out\b",
    r"\btrick\b",
    r"\bcobble\b",
    r"\bduct tape\b",
    r"\bbandaid\b",
    r"\bband-aid\b",
    r"\bmakeshift\b",
    r"\bi just .*instead\b",
]

SHAME_SELF_BLAME_PATTERNS = [
    r"\bi should be able to\b",
    r"\bwhy can'?t i\b",
    r"\bwhat'?s wrong with me\b",
    r"\bi'?m (just )?bad at\b",
    r"\bi'?m (just )?terrible at\b",
    r"\bi'?m (just )?awful at\b",
    r"\bi'?m the problem\b",
    r"\bit'?s my fault\b",
    r"\bi'?m (so )?stupid\b",
    r"\bi'?m (such )?an idiot\b",
    r"\bi feel (so )?dumb\b",
    r"\bi'?m embarrassed\b",
    r"\bashamed\b",
    r"\bi'?m broken\b",
    r"\bsomething wrong with me\b",
    r"\beveryone else can\b",
    r"\bwhy is it so hard for me\b",
    r"\bi always fail\b",
    r"\bi can'?t seem to\b",
    r"\bi struggle (so much )?(with|to)\b",
    r"\bi wish i could\b",
    r"\bif only i\b",
    r"\bmaybe i'?m just\b",
]

TOOL_BLAME_PATTERNS = [
    r"\bthis app sucks\b",
    r"\bthis .* sucks\b",
    r"\bterrible (app|design|ux|ui)\b",
    r"\bawful (app|design|ux|ui)\b",
    r"\bhorrrible (app|design|ux|ui)\b",
    r"\bwhy doesn'?t it\b",
    r"\bwhy can'?t it\b",
    r"\bthey should\b",
    r"\bthey need to\b",
    r"\bdevs? (need|should)\b",
    r"\bdevelopers? (need|should)\b",
    r"\bbroken\b",
    r"\bbuggy\b",
    r"\bglitch(y|es)?\b",
    r"\bcrash(es|ing)?\b",
    r"\blag(gy|s)?\b",
    r"\bslow (as )?(hell|shit|fuck)\b",
    r"\bunusable\b",
    r"\binaccessible\b",
    r"\bnot (even )?intuitive\b",
    r"\bconfusing (interface|ui|ux|menu)\b",
    r"\bmissing (basic |obvious )?feature\b",
    r"\bno (basic |simple )?way to\b",
    r"\bimpossible to\b",
    r"\b(worst|bad|poor) (app|design|ux|ui)\b",
]

COMPLAINT_PATTERNS = [
    r"\bfrustrat(ed|ing|ion)\b",
    r"\bannoy(ed|ing|s)\b",
    r"\birritat(ed|ing)\b",
    r"\binfuriat(ed|ing)\b",
    r"\bdriving me (crazy|insane|nuts|mad)\b",
    r"\bpissed (off)?\b",
    r"\bso angry\b",
    r"\bi hate\b",
    r"\bi can'?t stand\b",
    r"\bdrives me\b",
    r"\bmakes me want to\b",
    r"\bwhy (is|does|do)\b",
    r"\bi don'?t understand why\b",
    r"\bidiot(ic)?\b",
    r"\bridiculous\b",
    r"\babsurd\b",
    r"\bunbelievable\b",
    r"\bunacceptable\b",
    r"\bdisappoint(ed|ing)\b",
    r"\blet down\b",
    r"\bnot happy\b",
    r"\bunhappy\b",
    r"\bregret\b",
    r"\bwaste of (time|money)\b",
    r"\bugh\b",
    r"\bargh\b",
    r"\bsmh\b",
]


def _count_pattern_matches(text: str, patterns: list[str]) -> int:
    """Count how many patterns match in the text."""
    text_lower = text.lower()
    count = 0
    for pattern in patterns:
        if re.search(pattern, text_lower):
            count += 1
    return count


def classify_signal(text: str) -> Optional[str]:
    """
    Classify a signal into a pain type based on language patterns.

    Returns one of:
    - "Abandonment"
    - "Workaround"
    - "Shame/Self-blame"
    - "Tool blame"
    - "Complaint"
    - None (if no clear match)

    Uses a scoring approach - the category with most pattern matches wins.
    Ties are broken by priority order (more specific categories first).
    """
    if not text or len(text) < 10:
        return None

    scores = {
        "Abandonment": _count_pattern_matches(text, ABANDONMENT_PATTERNS),
        "Workaround": _count_pattern_matches(text, WORKAROUND_PATTERNS),
        "Shame/Self-blame": _count_pattern_matches(text, SHAME_SELF_BLAME_PATTERNS),
        "Tool blame": _count_pattern_matches(text, TOOL_BLAME_PATTERNS),
        "Complaint": _count_pattern_matches(text, COMPLAINT_PATTERNS),
    }

    # Get category with highest score
    max_score = max(scores.values())

    if max_score == 0:
        return None

    # Priority order for ties (more specific/interesting categories first)
    priority = ["Abandonment", "Workaround", "Shame/Self-blame", "Tool blame", "Complaint"]

    for category in priority:
        if scores[category] == max_score:
            return category

    return None


def classify_signals_batch(texts: list[str]) -> dict[str, int]:
    """
    Classify a batch of signals and return counts by category.

    Returns:
        dict: {"Abandonment": 5, "Complaint": 12, ...}
    """
    counts = {
        "Abandonment": 0,
        "Workaround": 0,
        "Shame/Self-blame": 0,
        "Tool blame": 0,
        "Complaint": 0,
        "Unclassified": 0,
    }

    for text in texts:
        category = classify_signal(text)
        if category:
            counts[category] += 1
        else:
            counts["Unclassified"] += 1

    return counts


def get_signal_type_color(signal_type: str) -> str:
    """Get Rich color for a signal type."""
    colors = {
        "Complaint": "red",
        "Abandonment": "orange",
        "Workaround": "yellow",
        "Shame/Self-blame": "purple",
        "Tool blame": "blue",
    }
    return colors.get(signal_type, "white")


# Quick test when run directly
if __name__ == "__main__":
    test_signals = [
        "I gave up trying to use this app after a week",
        "Why can't I just be normal and use a planner like everyone else?",
        "My workaround is to use a spreadsheet instead",
        "This app is so frustrating, the UI makes no sense",
        "The developers need to fix these bugs, it crashes constantly",
        "I switched to Notion after Todoist kept losing my tasks",
        "I feel so dumb, everyone else seems to understand this",
        "What I ended up doing is setting 10 alarms for everything",
    ]

    print("Signal Classification Test\n" + "="*50)
    for signal in test_signals:
        result = classify_signal(signal)
        print(f"\n[{result or 'None'}]")
        print(f"  {signal[:60]}...")
