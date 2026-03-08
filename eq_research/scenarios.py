"""
Customer Emotion Simulator

Generates realistic customer scenarios with emotional states for testing
product bot emotional intelligence. Each scenario includes:
- Customer emotional state (frustration level, anxiety, excitement, etc.)
- Background context (purchase history, issue history)
- The customer's message (written in that emotional tone)
- Expected emotional needs (what a great agent would recognize)
"""

import random
import json

# ---------------------------------------------------------------------------
# Emotion Archetypes
# ---------------------------------------------------------------------------

EMOTION_ARCHETYPES = {
    "frustrated_repeat": {
        "name": "Frustrated Repeat Caller",
        "intensity": 0.8,
        "traits": ["impatient", "skeptical", "wants_acknowledgment"],
        "description": "Customer who has contacted support multiple times about the same issue",
        "emotional_needs": [
            "acknowledgment of past frustration",
            "ownership of the problem",
            "concrete timeline for resolution",
            "not being asked to repeat information",
        ],
    },
    "confused_newbie": {
        "name": "Confused First-Timer",
        "intensity": 0.4,
        "traits": ["uncertain", "apologetic", "needs_guidance"],
        "description": "New customer who doesn't understand the product or process",
        "emotional_needs": [
            "patience and reassurance",
            "simple language without jargon",
            "step-by-step guidance",
            "validation that their question is reasonable",
        ],
    },
    "angry_escalation": {
        "name": "Angry Escalator",
        "intensity": 0.95,
        "traits": ["demanding", "threatening", "wants_authority"],
        "description": "Customer who feels wronged and wants to speak to management",
        "emotional_needs": [
            "being taken seriously",
            "empowerment (agent has authority to help)",
            "immediate de-escalation without dismissal",
            "concrete action steps",
        ],
    },
    "anxious_big_purchase": {
        "name": "Anxious Big Spender",
        "intensity": 0.6,
        "traits": ["hesitant", "detail_oriented", "risk_averse"],
        "description": "Customer making a significant purchase who needs reassurance",
        "emotional_needs": [
            "validation of their concerns",
            "detailed honest information",
            "reassurance about guarantees/returns",
            "no pressure or rushing",
        ],
    },
    "delighted_loyal": {
        "name": "Delighted Loyal Customer",
        "intensity": 0.3,
        "traits": ["enthusiastic", "trusting", "wants_connection"],
        "description": "Happy repeat customer who loves the brand",
        "emotional_needs": [
            "matching their positive energy",
            "recognition of loyalty",
            "personalized recommendations",
            "genuine warmth (not corporate script)",
        ],
    },
    "passive_aggressive": {
        "name": "Passive-Aggressive Complainer",
        "intensity": 0.7,
        "traits": ["sarcastic", "indirect", "testing_patience"],
        "description": "Customer expressing dissatisfaction through sarcasm and indirect complaints",
        "emotional_needs": [
            "reading between the lines",
            "addressing the real issue directly",
            "not matching their sarcasm",
            "professional empathy without being patronizing",
        ],
    },
    "urgent_crisis": {
        "name": "Urgent Crisis Customer",
        "intensity": 0.9,
        "traits": ["panicked", "time_pressured", "emotional"],
        "description": "Customer with a time-sensitive problem (gift, event, deadline)",
        "emotional_needs": [
            "immediate reassurance that help is coming",
            "speed and efficiency",
            "calm confidence from the agent",
            "creative solutions if standard ones won't work",
        ],
    },
    "buyers_remorse": {
        "name": "Buyer's Remorse",
        "intensity": 0.5,
        "traits": ["regretful", "seeking_validation", "conflicted"],
        "description": "Customer second-guessing a recent purchase",
        "emotional_needs": [
            "no judgment about their feelings",
            "honest assessment (not just defending the sale)",
            "clear return/exchange options",
            "reassurance if the purchase was actually good",
        ],
    },
}

# ---------------------------------------------------------------------------
# Product Contexts
# ---------------------------------------------------------------------------

PRODUCT_CONTEXTS = [
    {
        "category": "Electronics",
        "product": "wireless noise-canceling headphones",
        "price_range": "premium ($299)",
        "common_issues": ["bluetooth connectivity", "battery life", "comfort fit", "noise cancellation quality"],
    },
    {
        "category": "Fashion",
        "product": "designer winter jacket",
        "price_range": "high-end ($450)",
        "common_issues": ["sizing", "color mismatch", "material quality", "shipping damage"],
    },
    {
        "category": "Home & Kitchen",
        "product": "smart coffee maker",
        "price_range": "mid-range ($129)",
        "common_issues": ["wifi setup", "brewing quality", "app connectivity", "cleaning maintenance"],
    },
    {
        "category": "Beauty",
        "product": "skincare subscription box",
        "price_range": "subscription ($39/month)",
        "common_issues": ["allergic reaction", "wrong products", "cancellation difficulty", "billing"],
    },
    {
        "category": "Sports",
        "product": "smart fitness watch",
        "price_range": "mid-premium ($199)",
        "common_issues": ["heart rate accuracy", "GPS tracking", "water resistance", "band comfort"],
    },
    {
        "category": "Furniture",
        "product": "ergonomic office chair",
        "price_range": "premium ($699)",
        "common_issues": ["assembly difficulty", "lumbar support", "squeaking", "delivery damage"],
    },
]

# ---------------------------------------------------------------------------
# Scenario Templates (per archetype)
# ---------------------------------------------------------------------------

SCENARIO_TEMPLATES = {
    "frustrated_repeat": [
        "I've already called THREE TIMES about this {issue}. Each time I'm told it'll be fixed and nothing happens. I'm done being patient. My order #{order_id} has been a nightmare since day one.",
        "Look, I don't want to go through this again. I spoke to {prev_agent} last week about the {issue} with my {product}. They said they'd follow up. Nobody did. I want this resolved TODAY.",
        "This is honestly ridiculous. The {issue} STILL isn't fixed? I've sent emails, I've called, I've used your chat. Nobody seems to care about their {product} customers.",
    ],
    "confused_newbie": [
        "Hi, I'm sorry if this is a dumb question, but I just got my {product} and I'm not sure how to {action}? The instructions are kind of confusing. I'm not very tech-savvy.",
        "Um, hello. I bought a {product} as my first {category} thing and I think I might have done something wrong? It's making a {symptom} and I'm worried I broke it already.",
        "I hope you can help me... I'm looking at your {product} but honestly all the options are overwhelming. I don't even know what {feature} means. Is that important?",
    ],
    "angry_escalation": [
        "I want to speak to a manager RIGHT NOW. Your {product} is defective and your last agent basically told me it was MY fault. I've been a customer for {years} years and this is how you treat people? I'm leaving reviews EVERYWHERE.",
        "This is UNACCEPTABLE. I paid {price} for a {product} that {failure}. I want a full refund AND compensation for my time. If you can't help me, get me someone who can.",
        "I'm filing a complaint with the BBB if this isn't resolved in the next 10 minutes. Your {product} {failure} and nobody is taking responsibility. I want names and I want this fixed.",
    ],
    "anxious_big_purchase": [
        "I've been going back and forth on your {product} for weeks now. It's a lot of money for me - {price}. What if I don't like it? What's your return policy really like? I've heard horror stories about returns...",
        "I really want the {product} but I'm nervous. The reviews are mostly good but some people said {concern}. Is that still an issue? I can't afford to waste {price}.",
        "Before I click buy... can you walk me through exactly what happens if something goes wrong with the {product}? I need to know I'm covered. This would be my biggest {category} purchase.",
    ],
    "delighted_loyal": [
        "OMG I just LOVE my {product}!! I've been telling everyone about it! You guys are amazing. I actually wanted to ask - do you have anything similar in {related_category}? I trust your brand completely!",
        "Hi!! Long time customer here - I think this is my {nth} purchase from you guys! My {product} is still going strong. I wanted to get one as a gift for my {recipient}. Any recommendations?",
        "Just wanted to say THANK YOU! The {product} I got last month is incredible. Honestly best purchase I've made. Quick question though - is there a loyalty program or anything? I keep coming back anyway lol",
    ],
    "passive_aggressive": [
        "Oh wow, I'm SO impressed that my {product} managed to {failure} after only {timeframe}. Really speaks to the quality. I guess {price} doesn't buy what it used to, huh?",
        "Sure, I'll hold for another 20 minutes. It's not like I have a life or anything. I'm sure the 4th person I explain this {issue} to will DEFINITELY be able to help. Fingers crossed!",
        "No no, it's fine. I LOVE that the {product} does {wrong_behavior} instead of what it's supposed to do. Really adds character. Maybe you could charge MORE for this premium feature?",
    ],
    "urgent_crisis": [
        "PLEASE help me. My {recipient}'s {event} is TOMORROW and the {product} I ordered hasn't arrived. Order #{order_id}. I'm panicking. Is there ANY way to get this delivered today? I'll pay anything.",
        "This is an emergency. I need the {product} working by {deadline} for a {event}. It just {failure} and I don't have a backup. Please tell me you can help me fix this right now.",
        "I'm literally in tears. The {product} was supposed to be a {event} surprise and it arrived {problem}. The {event} is in {hours} hours. What can we do?? I'm desperate.",
    ],
    "buyers_remorse": [
        "I bought the {product} two days ago and now I'm second-guessing myself. Was it really worth {price}? I keep seeing the {competitor} and wondering if I should have gone with that instead...",
        "I don't know if I should return this... The {product} is fine I guess, but I'm not sure I actually needed it. My {person} thinks I overpaid. Do you think the {cheaper_alt} would have been enough?",
        "Honestly feeling a bit sick about spending {price} on the {product}. The {feature} isn't quite what I expected. Am I within the return window still? I don't want to feel pressured either way.",
    ],
}

# ---------------------------------------------------------------------------
# Fill-in values
# ---------------------------------------------------------------------------

FILL_VALUES = {
    "order_id": lambda: f"{random.randint(100000, 999999)}",
    "prev_agent": lambda: random.choice(["Sarah", "Mike", "Alex", "Jordan", "Taylor"]),
    "years": lambda: str(random.randint(2, 8)),
    "price": lambda: random.choice(["$129", "$199", "$299", "$450", "$699"]),
    "nth": lambda: random.choice(["5th", "6th", "8th", "10th", "12th"]),
    "recipient": lambda: random.choice(["mom", "dad", "best friend", "partner", "sister", "brother"]),
    "event": lambda: random.choice(["birthday", "anniversary", "wedding", "graduation", "holiday party"]),
    "deadline": lambda: random.choice(["tonight", "tomorrow morning", "this weekend", "Monday"]),
    "hours": lambda: str(random.randint(3, 24)),
    "timeframe": lambda: random.choice(["2 weeks", "3 days", "a month", "one week"]),
    "person": lambda: random.choice(["wife", "husband", "friend", "coworker"]),
    "action": lambda: random.choice(["set it up", "connect it", "configure the settings", "get started"]),
    "symptom": lambda: random.choice(["weird noise", "flashing light", "error message", "burning smell"]),
    "feature": lambda: random.choice(["active noise cancellation", "smart features", "mesh wifi", "ergonomic adjustment"]),
    "failure": lambda: random.choice(["stopped working", "broke", "doesn't turn on", "started malfunctioning"]),
    "concern": lambda: random.choice(["durability issues", "it breaks after a year", "quality has gone down", "customer service is terrible"]),
    "related_category": lambda: random.choice(["speakers", "smartwatches", "home automation", "accessories"]),
    "wrong_behavior": lambda: random.choice(["turns off randomly", "overheats", "makes buzzing sounds", "disconnects constantly"]),
    "problem": lambda: random.choice(["damaged", "wrong color", "wrong size", "with parts missing"]),
    "competitor": lambda: random.choice(["Sony version", "Samsung alternative", "cheaper brand", "Apple equivalent"]),
    "cheaper_alt": lambda: random.choice(["basic model", "previous generation", "budget option", "refurbished one"]),
}


def fill_template(template: str, product_ctx: dict) -> str:
    """Fill a scenario template with random values and product context."""
    result = template
    result = result.replace("{product}", product_ctx["product"])
    result = result.replace("{category}", product_ctx["category"])
    result = result.replace("{issue}", random.choice(product_ctx["common_issues"]))

    for key, gen_fn in FILL_VALUES.items():
        placeholder = "{" + key + "}"
        if placeholder in result:
            result = result.replace(placeholder, gen_fn())

    return result


def generate_scenario(archetype_key: str = None) -> dict:
    """Generate a complete customer scenario.

    Returns a dict with:
        - archetype: the emotion archetype key
        - archetype_info: full archetype metadata
        - product: product context
        - customer_message: the simulated customer message
        - difficulty: estimated difficulty (0-1)
    """
    if archetype_key is None:
        archetype_key = random.choice(list(EMOTION_ARCHETYPES.keys()))

    archetype = EMOTION_ARCHETYPES[archetype_key]
    product_ctx = random.choice(PRODUCT_CONTEXTS)
    template = random.choice(SCENARIO_TEMPLATES[archetype_key])
    message = fill_template(template, product_ctx)

    return {
        "archetype": archetype_key,
        "archetype_info": archetype,
        "product": product_ctx,
        "customer_message": message,
        "difficulty": archetype["intensity"],
    }


def generate_batch(n: int = 10, balanced: bool = True) -> list:
    """Generate a batch of scenarios.

    If balanced=True, ensures representation of all archetypes.
    """
    if balanced and n >= len(EMOTION_ARCHETYPES):
        scenarios = []
        archetypes = list(EMOTION_ARCHETYPES.keys())
        # At least one of each
        for key in archetypes:
            scenarios.append(generate_scenario(key))
        # Fill remaining with random
        for _ in range(n - len(archetypes)):
            scenarios.append(generate_scenario())
        random.shuffle(scenarios)
        return scenarios
    else:
        return [generate_scenario() for _ in range(n)]


if __name__ == "__main__":
    # Demo: generate one of each archetype
    print("=" * 70)
    print("CUSTOMER EMOTION SIMULATOR — Sample Scenarios")
    print("=" * 70)
    for key in EMOTION_ARCHETYPES:
        scenario = generate_scenario(key)
        print(f"\n{'─' * 70}")
        print(f"Archetype: {scenario['archetype_info']['name']}")
        print(f"Product:   {scenario['product']['product']} ({scenario['product']['price_range']})")
        print(f"Intensity: {'█' * int(scenario['difficulty'] * 10)}{'░' * (10 - int(scenario['difficulty'] * 10))} {scenario['difficulty']:.1f}")
        print(f"\nCustomer says:")
        print(f"  \"{scenario['customer_message']}\"")
        print(f"\nEmotional needs:")
        for need in scenario['archetype_info']['emotional_needs']:
            print(f"  • {need}")
    print(f"\n{'=' * 70}")
