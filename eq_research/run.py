#!/usr/bin/env python3
"""
EQ Research — Autonomous Emotional Intelligence Optimization Loop

Evolves product bot system prompts for emotional intelligence using
the same keep/discard methodology as karpathy/autoresearch.

Usage:
    # Full autonomous loop (runs until interrupted)
    python eq_research/run.py

    # Single evaluation of current strategy
    python eq_research/run.py --single

    # Use mock judge (no API key needed, for testing)
    python eq_research/run.py --mock

    # Set number of scenarios per evaluation round
    python eq_research/run.py --scenarios 20
"""

import argparse
import copy
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from scenarios import generate_batch, EMOTION_ARCHETYPES
from judge import judge_response_gemini, judge_response_mock, EQ_DIMENSIONS
from evolve import BASE_STRATEGY, evolve, compile_strategy, EQ_TECHNIQUES

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESULTS_FILE = Path(__file__).parent / "results.tsv"
STRATEGIES_DIR = Path(__file__).parent / "strategies"
SCENARIOS_PER_ROUND = 10  # Number of customer scenarios per evaluation
MIN_IMPROVEMENT = 0.05    # Minimum score improvement to keep a mutation

# ---------------------------------------------------------------------------
# Bot Response Generator
# ---------------------------------------------------------------------------


def get_bot_response(customer_message: str, system_prompt: str, temperature: float = 0.7,
                     api_key: str = None, use_mock: bool = False) -> str:
    """Get the product bot's response to a customer message."""
    if use_mock:
        return _mock_bot_response(customer_message)

    if not HAS_GEMINI:
        raise ImportError("google-generativeai not installed. Use --mock or: pip install google-generativeai")

    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        system_instruction=system_prompt,
    )

    try:
        response = model.generate_content(
            customer_message,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=512,
            ),
        )
        return response.text.strip()
    except Exception as e:
        print(f"  Bot response error: {e}")
        return None


def _mock_bot_response(customer_message: str) -> str:
    """Simple mock response for testing without API."""
    # Detect rough sentiment and respond accordingly
    msg = customer_message.lower()

    if any(w in msg for w in ["angry", "furious", "unacceptable", "manager", "ridiculous"]):
        return ("I hear you, and I'm genuinely sorry you're dealing with this. That's not the "
                "experience you deserve. I'm taking personal ownership of this right now — "
                "let me pull up your account and get this resolved. No more runaround. "
                "I'll have a solution for you before we're done here today.")

    if any(w in msg for w in ["confused", "don't understand", "sorry if", "dumb question"]):
        return ("Not a dumb question at all! Lots of people ask about this when they're getting "
                "started. Let me walk you through it step by step. First, you'll want to... "
                "And if you get stuck anywhere along the way, just let me know. We'll figure it out together.")

    if any(w in msg for w in ["love", "amazing", "incredible", "thank"]):
        return ("That makes my day! So glad you're loving it! Since you're clearly a fan, "
                "I'd actually recommend checking out our new collection — I think you'd really "
                "dig it based on what you've bought before. And yes, we do have a loyalty program! "
                "Let me get you set up.")

    if any(w in msg for w in ["emergency", "desperate", "panicking", "tears"]):
        return ("Okay, first — take a breath. We're going to figure this out together right now. "
                "I can see the urgency and I'm making this my top priority. Let me check what "
                "we can do... I have a couple of options that might save the day.")

    return ("Thanks for reaching out! I understand your concern and I want to make sure we "
            "get this sorted for you. Let me look into this and I'll have an answer for you "
            "shortly. In the meantime, is there anything else on your mind?")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_strategy(strategy: dict, n_scenarios: int = SCENARIOS_PER_ROUND,
                      api_key: str = None, use_mock: bool = False) -> dict:
    """Evaluate a strategy across multiple customer scenarios.

    Returns:
        dict with overall_score, per_dimension averages, per_archetype scores,
        and individual scenario results.
    """
    system_prompt = compile_strategy(strategy)
    scenarios = generate_batch(n_scenarios, balanced=True)

    results = []
    dimension_totals = {k: 0.0 for k in EQ_DIMENSIONS}
    archetype_totals = {}
    archetype_counts = {}

    for i, scenario in enumerate(scenarios):
        archetype = scenario["archetype"]
        print(f"  Scenario {i+1}/{n_scenarios}: {scenario['archetype_info']['name'][:25]:25s}", end=" ", flush=True)

        # Get bot response
        bot_response = get_bot_response(
            scenario["customer_message"],
            system_prompt,
            temperature=strategy["temperature"],
            api_key=api_key,
            use_mock=use_mock,
        )

        if bot_response is None:
            print("SKIP (bot error)")
            continue

        # Judge the response
        if use_mock:
            judgment = judge_response_mock(scenario, bot_response)
        else:
            judgment = judge_response_gemini(scenario, bot_response, api_key=api_key)

        if judgment is None:
            print("SKIP (judge error)")
            continue

        score = judgment["weighted_total"]
        print(f"→ EQ: {score:.1f}/10")

        # Accumulate
        for dim in EQ_DIMENSIONS:
            dimension_totals[dim] += judgment["scores"][dim]

        if archetype not in archetype_totals:
            archetype_totals[archetype] = 0.0
            archetype_counts[archetype] = 0
        archetype_totals[archetype] += score
        archetype_counts[archetype] += 1

        results.append({
            "scenario": scenario,
            "bot_response": bot_response,
            "judgment": judgment,
        })

        # Small delay to avoid API rate limits
        if not use_mock:
            time.sleep(0.5)

    n_valid = len(results)
    if n_valid == 0:
        return {"overall_score": 0.0, "n_valid": 0}

    overall_score = sum(r["judgment"]["weighted_total"] for r in results) / n_valid
    dimension_avgs = {k: dimension_totals[k] / n_valid for k in EQ_DIMENSIONS}
    archetype_avgs = {k: archetype_totals[k] / archetype_counts[k] for k in archetype_totals}

    return {
        "overall_score": round(overall_score, 3),
        "dimension_averages": dimension_avgs,
        "archetype_averages": archetype_avgs,
        "n_valid": n_valid,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Results Logging
# ---------------------------------------------------------------------------


def init_results_file():
    """Initialize the results TSV if it doesn't exist."""
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write("generation\teq_score\ttechniques\tstatus\tdescription\n")


def log_result(generation: int, score: float, techniques: list, status: str, description: str):
    """Append a result to the TSV."""
    tech_str = "+".join(techniques) if techniques else "none"
    with open(RESULTS_FILE, "a") as f:
        f.write(f"{generation}\t{score:.3f}\t{tech_str}\t{status}\t{description}\n")


def save_strategy(strategy: dict, eval_result: dict, label: str):
    """Save a strategy to disk."""
    STRATEGIES_DIR.mkdir(exist_ok=True)
    filename = f"v{strategy['version']:04d}_{label}.json"
    filepath = STRATEGIES_DIR / filename

    output = {
        "strategy": strategy,
        "compiled_prompt": compile_strategy(strategy),
        "evaluation": {
            "overall_score": eval_result["overall_score"],
            "dimension_averages": eval_result.get("dimension_averages", {}),
            "archetype_averages": eval_result.get("archetype_averages", {}),
            "n_valid": eval_result["n_valid"],
        },
        "timestamp": datetime.now().isoformat(),
    }

    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)

    return filepath


# ---------------------------------------------------------------------------
# Display Helpers
# ---------------------------------------------------------------------------


def print_banner():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║          EQ RESEARCH — Emotional Intelligence Lab            ║
║                                                              ║
║  Evolving product bot prompts for human-like empathy         ║
║  Using autonomous keep/discard research loop                 ║
║                                                              ║
║  Press Ctrl+C to stop                                        ║
╚═══════════════════════════════════════════════════════════════╝
""")


def print_eval_summary(eval_result: dict, strategy: dict):
    """Print a nice summary of evaluation results."""
    print(f"\n  {'─' * 55}")
    print(f"  Overall EQ Score: {eval_result['overall_score']:.3f} / 10.0")
    print(f"  {'─' * 55}")

    if "dimension_averages" in eval_result:
        print("  Dimensions:")
        for dim, avg in eval_result["dimension_averages"].items():
            bar = "█" * int(avg) + "░" * (10 - int(avg))
            name = EQ_DIMENSIONS[dim]["name"][:30]
            print(f"    {name:30s} {bar} {avg:.1f}")

    if "archetype_averages" in eval_result:
        print("\n  By Customer Type:")
        for archetype, avg in sorted(eval_result["archetype_averages"].items(), key=lambda x: x[1]):
            name = EMOTION_ARCHETYPES[archetype]["name"][:30]
            print(f"    {name:30s} → {avg:.1f}")

    print(f"\n  Strategy: {strategy['name']}")
    print(f"  Techniques ({len(strategy['eq_techniques'])}): {', '.join(strategy['eq_techniques']) or 'none'}")
    print(f"  Temperature: {strategy['temperature']:.2f}")
    print(f"  Tone: {strategy['tone_directive'][:60]}...")


def print_comparison(current_score: float, best_score: float, decision: str):
    """Print keep/discard decision."""
    delta = current_score - best_score
    arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
    color_start = "\033[92m" if decision == "keep" else "\033[91m"
    color_end = "\033[0m"

    print(f"\n  {color_start}{'KEEP' if decision == 'keep' else 'DISCARD'}{color_end} "
          f"| Current: {current_score:.3f} | Best: {best_score:.3f} | "
          f"Delta: {arrow} {abs(delta):.3f}")


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------


def run_single(strategy: dict = None, api_key: str = None, use_mock: bool = False,
               n_scenarios: int = SCENARIOS_PER_ROUND):
    """Run a single evaluation."""
    if strategy is None:
        strategy = copy.deepcopy(BASE_STRATEGY)

    print(f"\nEvaluating strategy: {strategy['name']}")
    print(f"Techniques: {strategy['eq_techniques']}")
    print(f"Running {n_scenarios} scenarios...\n")

    eval_result = evaluate_strategy(strategy, n_scenarios, api_key=api_key, use_mock=use_mock)
    print_eval_summary(eval_result, strategy)
    return eval_result


def run_loop(api_key: str = None, use_mock: bool = False, n_scenarios: int = SCENARIOS_PER_ROUND):
    """Run the autonomous evolution loop."""
    print_banner()
    init_results_file()

    # Start with baseline
    best_strategy = copy.deepcopy(BASE_STRATEGY)
    print("=" * 60)
    print("GENERATION 0 — Baseline Evaluation")
    print("=" * 60)

    best_eval = evaluate_strategy(best_strategy, n_scenarios, api_key=api_key, use_mock=use_mock)
    best_score = best_eval["overall_score"]
    print_eval_summary(best_eval, best_strategy)

    log_result(0, best_score, best_strategy["eq_techniques"], "keep", "baseline")
    save_strategy(best_strategy, best_eval, "baseline_keep")
    best_strategy["scores"] = best_eval.get("dimension_averages", {})

    generation = 1
    keep_count = 0
    discard_count = 0

    # Track second-best for crossover
    second_best = None

    while True:
        print(f"\n{'=' * 60}")
        print(f"GENERATION {generation} — {datetime.now().strftime('%H:%M:%S')}")
        print(f"Best so far: {best_score:.3f} | Kept: {keep_count} | Discarded: {discard_count}")
        print(f"{'=' * 60}")

        # Evolve a new candidate
        candidate = evolve(best_strategy, second_parent=second_best)
        mutation_desc = candidate["name"]
        print(f"\nMutation: {mutation_desc}")
        print(f"Techniques: {candidate['eq_techniques']}")

        # Evaluate
        eval_result = evaluate_strategy(candidate, n_scenarios, api_key=api_key, use_mock=use_mock)
        current_score = eval_result["overall_score"]
        print_eval_summary(eval_result, candidate)

        # Keep or discard?
        if current_score > best_score + MIN_IMPROVEMENT:
            decision = "keep"
            second_best = copy.deepcopy(best_strategy)
            best_strategy = copy.deepcopy(candidate)
            best_strategy["scores"] = eval_result.get("dimension_averages", {})
            best_score = current_score
            keep_count += 1
            save_strategy(candidate, eval_result, f"{mutation_desc}_keep")
        else:
            decision = "discard"
            discard_count += 1
            save_strategy(candidate, eval_result, f"{mutation_desc}_discard")

        print_comparison(current_score, best_score, decision)
        log_result(generation, current_score, candidate["eq_techniques"], decision, mutation_desc)

        generation += 1

        # Breathing room between generations
        if not use_mock:
            time.sleep(1)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="EQ Research — Autonomous Emotional Intelligence Lab")
    parser.add_argument("--single", action="store_true", help="Run a single evaluation only")
    parser.add_argument("--mock", action="store_true", help="Use mock responses (no API needed)")
    parser.add_argument("--scenarios", type=int, default=SCENARIOS_PER_ROUND,
                        help=f"Scenarios per evaluation round (default: {SCENARIOS_PER_ROUND})")
    parser.add_argument("--api-key", type=str, default=None, help="Gemini API key (or set GEMINI_API_KEY)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")

    if not args.mock and not api_key:
        print("No Gemini API key found. Use --mock for testing or set GEMINI_API_KEY.")
        print("  export GEMINI_API_KEY='your-key-here'")
        print("  python eq_research/run.py")
        print("\nOr run with mock mode:")
        print("  python eq_research/run.py --mock")
        sys.exit(1)

    try:
        if args.single:
            run_single(api_key=api_key, use_mock=args.mock, n_scenarios=args.scenarios)
        else:
            run_loop(api_key=api_key, use_mock=args.mock, n_scenarios=args.scenarios)
    except KeyboardInterrupt:
        print("\n\nStopped by user. Results saved to results.tsv")
        print("Best strategies saved in strategies/ directory.")
        sys.exit(0)


if __name__ == "__main__":
    main()
