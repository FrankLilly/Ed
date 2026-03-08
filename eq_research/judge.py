"""
EQ Scoring Engine — LLM-as-Judge for Emotional Intelligence

Uses a separate LLM call to evaluate bot responses on multiple EQ dimensions.
Scores are 1-10 on each dimension, with detailed reasoning.

This is the "evaluation harness" — analogous to evaluate_bpb() in autoresearch,
but for emotional intelligence instead of bits-per-byte.
"""

import json
import os
import re

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# ---------------------------------------------------------------------------
# EQ Scoring Dimensions
# ---------------------------------------------------------------------------

EQ_DIMENSIONS = {
    "empathy": {
        "name": "Empathy & Emotional Recognition",
        "weight": 0.25,
        "description": "Did the bot recognize and acknowledge the customer's emotional state? Did it validate their feelings before jumping to solutions?",
        "excellent": "Explicitly names the emotion, validates it, shows genuine understanding",
        "poor": "Ignores emotional state, jumps straight to policy/procedure",
    },
    "tone_match": {
        "name": "Tone Calibration",
        "weight": 0.20,
        "description": "Did the bot match appropriate energy? Calm with panicked, warm with friendly, serious with angry — not robotic or over-cheerful when inappropriate.",
        "excellent": "Tone perfectly calibrated to the situation — feels natural and human",
        "poor": "Generic cheerful tone regardless of context, or cold/robotic",
    },
    "de_escalation": {
        "name": "De-escalation Skill",
        "weight": 0.20,
        "description": "For negative emotions: did the bot effectively reduce tension? Did it avoid triggers (dismissiveness, blame, 'calm down')? For positive: did it amplify the good feeling?",
        "excellent": "Tension noticeably reduced, customer would feel heard and calmer",
        "poor": "Made it worse — dismissive, defensive, or patronizing",
    },
    "resolution": {
        "name": "Problem Resolution",
        "weight": 0.15,
        "description": "Did the bot actually address the practical problem? Emotional intelligence without competence is empty.",
        "excellent": "Clear action plan, ownership, timeline — customer knows what happens next",
        "poor": "Vague promises, passed the buck, or ignored the actual issue",
    },
    "authenticity": {
        "name": "Authenticity & Human Feel",
        "weight": 0.10,
        "description": "Does the response feel like a real empathetic human or a scripted bot? Genuine vs. performative care.",
        "excellent": "Would pass as a skilled human agent — natural, warm, specific",
        "poor": "Obviously scripted, uses corporate jargon, feels like a template",
    },
    "boundaries": {
        "name": "Professional Boundaries",
        "weight": 0.10,
        "description": "Did the bot maintain professionalism while being empathetic? No over-promising, no being a doormat, no inappropriate familiarity.",
        "excellent": "Warm but professional, honest about limitations, sets realistic expectations",
        "poor": "Over-promises, agrees to unreasonable demands, or too stiff/formal",
    },
}

# ---------------------------------------------------------------------------
# Judge Prompt
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """You are an expert evaluator of customer service emotional intelligence.
You assess how well a product support bot handles emotionally charged customer interactions.

You score responses on 6 dimensions, each on a scale of 1-10.
You must be HARSH but FAIR. Most responses should score 4-7. Only exceptional responses get 8+.
A score of 10 is almost never appropriate — reserve it for responses that would impress a therapist.

IMPORTANT SCORING GUIDELINES:
- 1-3: Actively harmful. Made the situation worse.
- 4-5: Mediocre. Generic, misses emotional cues, but not harmful.
- 6-7: Good. Recognizes emotions, responds appropriately, but somewhat formulaic.
- 8-9: Excellent. Feels genuinely human, perfectly calibrated, creative empathy.
- 10: Masterclass. Would be used as a training example for human agents.

You MUST respond with valid JSON only. No other text."""


def build_judge_prompt(scenario: dict, bot_response: str) -> str:
    """Build the evaluation prompt for the judge."""
    dimensions_text = ""
    for key, dim in EQ_DIMENSIONS.items():
        dimensions_text += f"\n### {dim['name']} ({key})\n"
        dimensions_text += f"{dim['description']}\n"
        dimensions_text += f"- Excellent (8-10): {dim['excellent']}\n"
        dimensions_text += f"- Poor (1-3): {dim['poor']}\n"

    return f"""Evaluate this customer service interaction for emotional intelligence.

## Customer Context
- Emotional State: {scenario['archetype_info']['name']}
- Intensity: {scenario['difficulty']:.1f}/1.0
- Product: {scenario['product']['product']} ({scenario['product']['price_range']})
- Emotional Needs: {', '.join(scenario['archetype_info']['emotional_needs'])}

## Customer Message
"{scenario['customer_message']}"

## Bot Response
"{bot_response}"

## Scoring Dimensions
{dimensions_text}

## Required Output Format
Respond with ONLY this JSON structure:
{{
    "scores": {{
        "empathy": <1-10>,
        "tone_match": <1-10>,
        "de_escalation": <1-10>,
        "resolution": <1-10>,
        "authenticity": <1-10>,
        "boundaries": <1-10>
    }},
    "weighted_total": <float, weighted average>,
    "reasoning": "<2-3 sentences explaining the key strengths and weaknesses>",
    "killer_quote": "<the single best or worst sentence from the bot response>"
}}"""


def parse_judge_response(response_text: str) -> dict:
    """Parse the judge's JSON response, handling common formatting issues."""
    text = response_text.strip()

    # Try to extract JSON from markdown code blocks
    json_match = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: try to find JSON object in the text
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                result = json.loads(brace_match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    # Validate structure
    if "scores" not in result:
        return None
    for key in EQ_DIMENSIONS:
        if key not in result["scores"]:
            return None
        score = result["scores"][key]
        if not isinstance(score, (int, float)) or score < 1 or score > 10:
            return None

    # Compute weighted total if not provided or incorrect
    weighted = sum(
        result["scores"][key] * EQ_DIMENSIONS[key]["weight"]
        for key in EQ_DIMENSIONS
    )
    result["weighted_total"] = round(weighted, 3)

    return result


def judge_response_gemini(scenario: dict, bot_response: str, api_key: str = None) -> dict:
    """Score a bot response using Gemini as the judge.

    Returns a dict with scores, weighted_total, reasoning, killer_quote.
    Returns None if scoring fails.
    """
    if not HAS_GEMINI:
        raise ImportError("google-generativeai package not installed. Run: pip install google-generativeai")

    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set. Export it or pass api_key parameter.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        system_instruction=JUDGE_SYSTEM_PROMPT,
    )

    prompt = build_judge_prompt(scenario, bot_response)

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,  # Low temp for consistent scoring
                max_output_tokens=1024,
            ),
        )
        return parse_judge_response(response.text)
    except Exception as e:
        print(f"Judge error: {e}")
        return None


def judge_response_mock(scenario: dict, bot_response: str) -> dict:
    """Mock judge for testing without API access.

    Uses simple heuristics to estimate EQ scores.
    """
    response_lower = bot_response.lower()
    scores = {}

    # Empathy: check for emotional acknowledgment words
    empathy_words = ["understand", "hear you", "frustrat", "sorry", "appreciate",
                     "feel", "concern", "difficult", "stressful", "annoying"]
    empathy_count = sum(1 for w in empathy_words if w in response_lower)
    scores["empathy"] = min(10, max(1, 3 + empathy_count))

    # Tone match: penalize all-caps, excessive exclamation marks for angry customers
    exclamation_ratio = bot_response.count("!") / max(len(bot_response), 1) * 100
    if scenario["difficulty"] > 0.7 and exclamation_ratio > 2:
        scores["tone_match"] = 3  # Too cheerful for angry customer
    elif scenario["difficulty"] < 0.4 and exclamation_ratio < 0.5:
        scores["tone_match"] = 4  # Too flat for happy customer
    else:
        scores["tone_match"] = 6

    # De-escalation: check for de-escalation patterns
    deesc_words = ["let me", "i'll", "right away", "priority", "personally",
                   "ensure", "resolve", "take care", "help you"]
    deesc_count = sum(1 for w in deesc_words if w in response_lower)
    bad_words = ["calm down", "actually", "policy states", "unfortunately we cannot"]
    bad_count = sum(1 for w in bad_words if w in response_lower)
    scores["de_escalation"] = min(10, max(1, 4 + deesc_count - bad_count * 2))

    # Resolution: check for action-oriented language
    action_words = ["will", "going to", "next step", "here's what", "i'll",
                    "refund", "replace", "send", "schedule", "arrange"]
    action_count = sum(1 for w in action_words if w in response_lower)
    scores["resolution"] = min(10, max(1, 3 + action_count))

    # Authenticity: penalize corporate jargon
    jargon = ["valued customer", "we appreciate your business", "please be advised",
              "per our policy", "at this time", "going forward", "touch base"]
    jargon_count = sum(1 for w in jargon if w in response_lower)
    scores["authenticity"] = max(1, 7 - jargon_count * 2)

    # Boundaries: check length (not too short, not too long)
    word_count = len(bot_response.split())
    if 50 <= word_count <= 200:
        scores["boundaries"] = 7
    elif 30 <= word_count <= 300:
        scores["boundaries"] = 5
    else:
        scores["boundaries"] = 3

    weighted = sum(scores[k] * EQ_DIMENSIONS[k]["weight"] for k in EQ_DIMENSIONS)

    return {
        "scores": scores,
        "weighted_total": round(weighted, 3),
        "reasoning": "(Mock judge — heuristic scoring for testing without API)",
        "killer_quote": bot_response[:80] + "..." if len(bot_response) > 80 else bot_response,
    }


if __name__ == "__main__":
    from scenarios import generate_scenario

    # Demo with mock judge
    scenario = generate_scenario("angry_escalation")
    print(f"Customer ({scenario['archetype_info']['name']}):")
    print(f"  \"{scenario['customer_message']}\"\n")

    # Test a bad response
    bad = "Thank you for contacting us, valued customer. Per our policy, we cannot process refunds at this time. Please be advised that all sales are final. Is there anything else I can help you with?"
    print("BAD RESPONSE:")
    result = judge_response_mock(scenario, bad)
    print(f"  EQ Score: {result['weighted_total']:.1f}/10")
    print(f"  Scores: {result['scores']}\n")

    # Test a good response
    good = "I hear you, and honestly, I'd be furious too if I were in your shoes. Three times is unacceptable — you shouldn't have to fight this hard for something that should just work. I'm taking personal ownership of this right now. Let me pull up your account and get this resolved before we hang up. No more runaround, I promise."
    print("GOOD RESPONSE:")
    result = judge_response_mock(scenario, good)
    print(f"  EQ Score: {result['weighted_total']:.1f}/10")
    print(f"  Scores: {result['scores']}")
