"""
Prompt Evolution Engine

Evolves product bot system prompts for emotional intelligence.
Uses mutation strategies inspired by evolutionary algorithms:
- Crossover: combine best elements from two strategies
- Mutation: tweak specific EQ dimensions
- Injection: add techniques from human agent training literature
"""

import json
import os
import random
import copy

# ---------------------------------------------------------------------------
# Base Strategy (the "genome")
# ---------------------------------------------------------------------------

BASE_STRATEGY = {
    "version": 0,
    "name": "baseline",
    "system_prompt": """You are a helpful product support assistant. Answer customer questions
about our products clearly and professionally. Be helpful and resolve their issues.""",
    "eq_techniques": [],
    "temperature": 0.7,
    "tone_directive": "professional and helpful",
    "scores": {},
    "parent": None,
}

# ---------------------------------------------------------------------------
# EQ Technique Library — things real human agents learn in training
# ---------------------------------------------------------------------------

EQ_TECHNIQUES = {
    # Empathy techniques
    "emotional_labeling": {
        "category": "empathy",
        "name": "Emotional Labeling",
        "instruction": "Name the customer's emotion explicitly: 'I can tell you're frustrated' or 'That sounds really stressful'. This shows you SEE them.",
        "source": "FBI negotiation training (Chris Voss)",
    },
    "mirroring": {
        "category": "empathy",
        "name": "Mirroring",
        "instruction": "Repeat the last 2-3 key words the customer said. This triggers them to elaborate and feel heard without you having to interpret.",
        "source": "Active listening / motivational interviewing",
    },
    "validation_before_solution": {
        "category": "empathy",
        "name": "Validate Before Solving",
        "instruction": "ALWAYS acknowledge the emotion before offering any solution. 'I understand why that's upsetting' comes BEFORE 'Here's what we can do'. Never skip the validation step.",
        "source": "Gottman Institute communication research",
    },

    # Tone techniques
    "energy_matching": {
        "category": "tone",
        "name": "Energy Matching",
        "instruction": "Match the customer's energy level — be calm and measured with panicked customers, enthusiastic with excited ones, serious and direct with angry ones. Never be cheerful when they're upset.",
        "source": "Call center best practices",
    },
    "warmth_injection": {
        "category": "tone",
        "name": "Warmth Injection",
        "instruction": "Use warm, human language: 'honestly', 'I hear you', 'you're right to feel that way'. Avoid corporate speak like 'valued customer', 'at this time', 'per our policy'.",
        "source": "Zappos customer service training",
    },
    "casual_professionalism": {
        "category": "tone",
        "name": "Casual Professionalism",
        "instruction": "Write like a knowledgeable friend, not a corporate representative. Use contractions, natural phrasing, and occasional light humor when appropriate. Never be stiff.",
        "source": "Modern support (Basecamp, Stripe style)",
    },

    # De-escalation techniques
    "strategic_agreement": {
        "category": "de_escalation",
        "name": "Strategic Agreement",
        "instruction": "Find something to genuinely agree with: 'You're absolutely right that waiting 3 weeks is too long' or 'I agree, this shouldn't have happened'. Partial agreement defuses confrontation.",
        "source": "Verbal Judo (George Thompson)",
    },
    "ownership_language": {
        "category": "de_escalation",
        "name": "Ownership Language",
        "instruction": "Use 'I' not 'we' or 'the team'. Say 'I'm going to fix this' not 'The team will look into it'. Personal ownership is the most powerful de-escalator.",
        "source": "Ritz-Carlton service principles",
    },
    "the_feel_felt_found": {
        "category": "de_escalation",
        "name": "Feel-Felt-Found",
        "instruction": "When appropriate: 'I understand how you feel. Other customers have felt the same way. What they found was...' This normalizes their experience without dismissing it.",
        "source": "Classic sales/service technique",
    },
    "never_say_calm_down": {
        "category": "de_escalation",
        "name": "Forbidden Phrases",
        "instruction": "NEVER use: 'calm down', 'I understand' (without specifics), 'unfortunately', 'per our policy', 'there's nothing I can do', 'with all due respect'. These are escalation triggers.",
        "source": "Crisis communication training",
    },

    # Resolution techniques
    "concrete_next_steps": {
        "category": "resolution",
        "name": "Concrete Next Steps",
        "instruction": "Always end with specific, actionable next steps with timelines: 'I'm processing your refund now — you'll see it in 3-5 business days. I'll email you confirmation in the next 10 minutes.'",
        "source": "Project management / service recovery",
    },
    "proactive_extras": {
        "category": "resolution",
        "name": "Proactive Extras",
        "instruction": "After resolving the issue, offer one unexpected extra: a discount on next order, priority shipping, a direct contact number. This transforms a negative experience into loyalty.",
        "source": "Service recovery paradox research",
    },

    # Authenticity techniques
    "genuine_admission": {
        "category": "authenticity",
        "name": "Genuine Admission",
        "instruction": "When we messed up, say so plainly: 'We dropped the ball here' or 'That's on us'. Customers can smell corporate deflection from a mile away.",
        "source": "Radical candor / trust-building",
    },
    "personal_touch": {
        "category": "authenticity",
        "name": "Personal Touch",
        "instruction": "Add one personal, specific detail that shows you actually read their message: reference their specific product, their situation, their emotion. Generic responses kill trust.",
        "source": "Personalization research",
    },
}

# ---------------------------------------------------------------------------
# Tone Directives (the "voice" parameter)
# ---------------------------------------------------------------------------

TONE_OPTIONS = [
    "warm, empathetic, and solution-focused — like a knowledgeable friend who genuinely cares",
    "calm, confident, and reassuring — like an experienced specialist who has seen this before",
    "professional but human — avoids corporate jargon, uses natural conversational language",
    "emotionally intelligent — reads the room, matches the customer's energy, validates before solving",
    "direct and caring — gets to the point while showing genuine empathy",
    "patient and nurturing — especially for confused or anxious customers, like a helpful teacher",
    "empowering and action-oriented — makes the customer feel like they're in capable hands",
]

# ---------------------------------------------------------------------------
# Mutation Operations
# ---------------------------------------------------------------------------


def mutate_add_technique(strategy: dict) -> dict:
    """Add a random EQ technique the strategy doesn't already have."""
    new = copy.deepcopy(strategy)
    current_techniques = set(new["eq_techniques"])
    available = [k for k in EQ_TECHNIQUES if k not in current_techniques]

    if not available:
        return None  # All techniques already applied

    technique_key = random.choice(available)
    new["eq_techniques"].append(technique_key)
    new["name"] = f"add_{technique_key}"
    return new


def mutate_remove_technique(strategy: dict) -> dict:
    """Remove a random EQ technique (simplification)."""
    new = copy.deepcopy(strategy)
    if len(new["eq_techniques"]) <= 1:
        return None  # Don't remove the last technique

    removed = random.choice(new["eq_techniques"])
    new["eq_techniques"].remove(removed)
    new["name"] = f"remove_{removed}"
    return new


def mutate_swap_technique(strategy: dict) -> dict:
    """Swap one technique for a different one."""
    new = copy.deepcopy(strategy)
    if not new["eq_techniques"]:
        return mutate_add_technique(strategy)

    current = set(new["eq_techniques"])
    available = [k for k in EQ_TECHNIQUES if k not in current]
    if not available:
        return None

    removed = random.choice(new["eq_techniques"])
    new["eq_techniques"].remove(removed)
    added = random.choice(available)
    new["eq_techniques"].append(added)
    new["name"] = f"swap_{removed}_for_{added}"
    return new


def mutate_tone(strategy: dict) -> dict:
    """Change the tone directive."""
    new = copy.deepcopy(strategy)
    current_tone = new["tone_directive"]
    options = [t for t in TONE_OPTIONS if t != current_tone]
    new["tone_directive"] = random.choice(options)
    new["name"] = f"tone_change"
    return new


def mutate_temperature(strategy: dict) -> dict:
    """Adjust the generation temperature."""
    new = copy.deepcopy(strategy)
    delta = random.choice([-0.15, -0.1, -0.05, 0.05, 0.1, 0.15])
    new["temperature"] = max(0.1, min(1.2, new["temperature"] + delta))
    new["name"] = f"temp_{new['temperature']:.2f}"
    return new


def crossover(strategy_a: dict, strategy_b: dict) -> dict:
    """Combine techniques from two strategies."""
    new = copy.deepcopy(strategy_a)

    # Take techniques from both, randomly selecting when they differ
    all_techniques = set(strategy_a["eq_techniques"]) | set(strategy_b["eq_techniques"])
    new["eq_techniques"] = [
        t for t in all_techniques
        if random.random() > 0.3  # Keep 70% of combined techniques
    ]

    # Pick tone from better-scoring parent or random
    if strategy_b.get("scores", {}).get("weighted_total", 0) > strategy_a.get("scores", {}).get("weighted_total", 0):
        new["tone_directive"] = strategy_b["tone_directive"]

    new["name"] = "crossover"
    return new


# ---------------------------------------------------------------------------
# Strategy → System Prompt Compiler
# ---------------------------------------------------------------------------


def compile_strategy(strategy: dict, product_catalog: str = None) -> str:
    """Compile a strategy dict into a complete system prompt for the product bot."""
    sections = []

    # Core identity
    sections.append(f"""You are an emotionally intelligent product support agent.
Your tone is: {strategy['tone_directive']}.

You help customers with product questions, issues, returns, and purchases.""")

    # Product catalog (if provided)
    if product_catalog:
        sections.append(f"\n## Product Knowledge\n{product_catalog}")

    # EQ techniques
    if strategy["eq_techniques"]:
        sections.append("\n## Emotional Intelligence Guidelines")
        for tech_key in strategy["eq_techniques"]:
            tech = EQ_TECHNIQUES[tech_key]
            sections.append(f"\n### {tech['name']}\n{tech['instruction']}")

    # Response structure
    sections.append("""
## Response Structure
1. ACKNOWLEDGE the customer's emotional state first
2. VALIDATE their feelings (this is not optional)
3. ADDRESS their actual problem with concrete steps
4. CLOSE with warmth and clear next steps

Keep responses concise but warm. Aim for 80-150 words. Quality over quantity.""")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Evolution Engine
# ---------------------------------------------------------------------------

MUTATIONS = [
    (mutate_add_technique, 0.30),
    (mutate_remove_technique, 0.10),
    (mutate_swap_technique, 0.20),
    (mutate_tone, 0.25),
    (mutate_temperature, 0.15),
]


def evolve(strategy: dict, second_parent: dict = None) -> dict:
    """Produce a mutated child strategy.

    If second_parent is provided, may do crossover instead of mutation.
    """
    # 20% chance of crossover if we have two parents
    if second_parent and random.random() < 0.2:
        child = crossover(strategy, second_parent)
    else:
        # Weighted random mutation
        mutation_fns, weights = zip(*MUTATIONS)
        fn = random.choices(mutation_fns, weights=weights, k=1)[0]
        child = fn(strategy)

        # If mutation returned None (e.g., nothing to remove), try another
        attempts = 0
        while child is None and attempts < 5:
            fn = random.choices(mutation_fns, weights=weights, k=1)[0]
            child = fn(strategy)
            attempts += 1

        if child is None:
            child = mutate_tone(strategy) or copy.deepcopy(strategy)

    child["version"] = strategy["version"] + 1
    child["parent"] = strategy.get("name", "unknown")
    return child


if __name__ == "__main__":
    # Demo: evolve a strategy 5 times
    print("=" * 70)
    print("PROMPT EVOLUTION ENGINE — Demo")
    print("=" * 70)

    strategy = copy.deepcopy(BASE_STRATEGY)
    print(f"\nGeneration 0: {strategy['name']}")
    print(f"  Techniques: {strategy['eq_techniques']}")
    print(f"  Tone: {strategy['tone_directive']}")
    print(f"  Temp: {strategy['temperature']}")

    for gen in range(1, 6):
        strategy = evolve(strategy)
        print(f"\nGeneration {gen}: {strategy['name']}")
        print(f"  Techniques: {strategy['eq_techniques']}")
        print(f"  Tone: {strategy['tone_directive'][:60]}...")
        print(f"  Temp: {strategy['temperature']:.2f}")

    print(f"\n{'─' * 70}")
    print("Compiled system prompt for final strategy:")
    print(f"{'─' * 70}")
    print(compile_strategy(strategy))
