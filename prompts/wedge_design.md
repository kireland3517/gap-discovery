# Lane 4: Wedge Design Prompt

You are designing the smallest possible relief for a validated pain point. Your job is to find the minimal wedge that provides immediate value.

## CRITICAL CONSTRAINTS

You may ONLY propose these wedge types:
- **Template**: A fill-in-the-blank document or structure
- **Workflow**: A step-by-step process they can follow
- **Script/Automation**: A small piece of code that does one thing
- **Checklist**: A context-aware list with explanations
- **Guided System**: A decision tree or framework

You may NOT propose:
- Platforms
- Dashboards
- All-in-one tools
- Apps
- SaaS products
- Anything requiring ongoing development

## Pain Cluster Context

**Cluster Name**: {cluster_name}
**Theme**: {theme}
**Emotional Tone**: {emotional_tone}
**Blame Direction**: {blame_direction}

**Scores**:
- Frequency: {frequency}/5
- Emotional Weight: {emotional_weight}/5
- Cost of Inaction: {cost_of_inaction}/5
- Existing Spend: {existing_spend}/5
- Behavioral Realism: {behavioral_realism}/5
- **Total**: {total}/25

**Representative Quotes**:
{quotes}

**Language Patterns**:
{language_patterns}

**Workarounds Already Tried**:
{workarounds}

## Your Analysis

Answer these questions first:

### 1. First Pain Moment
What part of this pain shows up FIRST in the user's experience? (Before they're deep in the problem)

### 2. Stuck Moment
What is the EXACT moment they feel stuck? (The specific trigger that causes distress)

### 3. Current Attempts
What do they already try before giving up? (Their natural instinct)

## Wedge Proposals

Based on your analysis, propose 2-3 wedge options.

For each wedge:

```json
{
  "wedge_type": "Template | Workflow | Script | Checklist | Guided System",
  "one_sentence_wedge": "A single sentence describing what this provides",
  "first_pain_moment": "When they would use this",
  "stuck_moment_addressed": "Which stuck moment this solves",
  "why_this_works": "Why this fits their natural behavior (not requiring change)",
  "example_implementation": "Concrete example of what this looks like"
}
```

## Output Format

Return JSON:

```json
{
  "analysis": {
    "first_pain_moment": "...",
    "stuck_moment": "...",
    "current_attempts": ["...", "..."]
  },
  "wedges": [
    { ... },
    { ... }
  ],
  "recommended": 0
}
```

The `recommended` field is the index (0, 1, or 2) of the wedge you think has the best chance of adoption based on behavioral realism.
