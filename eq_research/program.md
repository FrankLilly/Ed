# EQ Research — Autonomous Emotional Intelligence Optimization

This is an experiment to have an LLM autonomously research and optimize
emotional intelligence in product bot system prompts.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) —
same keep/discard loop, but evolving prompts instead of model weights.

## Concept

Instead of training a neural network, we evolve **system prompt strategies**.
Each strategy is a combination of:
- Tone directives (how to sound)
- EQ techniques (emotional intelligence skills from real human agent training)
- Temperature settings

The "fitness function" is an LLM-as-judge that scores bot responses across
6 emotional intelligence dimensions (empathy, tone matching, de-escalation,
resolution, authenticity, professional boundaries).

## Setup

1. **Set Gemini API key**: `export GEMINI_API_KEY="your-key-here"`
2. **Read the files** for full context:
   - `scenarios.py` — Customer emotion simulator (8 archetypes, 6 product categories)
   - `judge.py` — EQ scoring engine (6 dimensions, weighted scoring)
   - `evolve.py` — Prompt mutation engine (add/remove/swap techniques, tone changes)
   - `run.py` — The main loop you'll be modifying and running
3. **Test with mock mode**: `python eq_research/run.py --mock --single`
4. **Run the real thing**: `python eq_research/run.py --scenarios 15`

## What You CAN Modify

- `evolve.py` — Add new EQ techniques, change mutation weights, add new mutation types
- `run.py` — Adjust evaluation logic, add new features to the loop
- `scenarios.py` — Add new customer archetypes, products, or scenario templates

## What You Should NOT Modify

- `judge.py` — The scoring dimensions and judge prompt are the ground truth metric.
  Changing the judge to get better scores is cheating.

## The Research Loop

LOOP FOREVER:

1. Look at the current best strategy (or start with baseline)
2. Mutate it: add/remove/swap EQ techniques, change tone, adjust temperature
3. Evaluate: run the mutated strategy against a batch of customer scenarios
4. Score: LLM-as-judge scores each response on 6 EQ dimensions
5. Compare: is the weighted average score better than the current best?
6. If improved by ≥0.05: **KEEP** the mutation, advance
7. If equal or worse: **DISCARD**, revert to best
8. Log results to `results.tsv`
9. Repeat

## What Makes This Fun

- You're essentially doing **natural selection for empathy**
- The scenarios are wild — angry escalations, panicked crisis customers, passive-aggressive sarcasm
- The EQ techniques come from real human training: FBI negotiation (Chris Voss), Ritz-Carlton service principles, Verbal Judo, Zappos customer training
- You can watch the bot get measurably better at handling difficult humans
- The results reveal which EQ techniques actually work and which are noise

## Interesting Research Directions

- Which EQ techniques compose well together?
- Does higher temperature = more authentic responses?
- Which customer archetype is hardest to handle? (Spoiler: passive-aggressive)
- Can you find a strategy that scores 8+ on angry escalations?
- What's the minimal set of techniques that gets you to 90% of max score?
- Does adding more techniques always help, or is there a point of diminishing returns?

## NEVER STOP

Once the experiment loop has begun, do NOT pause to ask the human if you should continue.
The human might be asleep. You are autonomous. If you run out of ideas:
- Try combining techniques that scored well individually
- Explore the tone space more aggressively
- Add new EQ techniques to `evolve.py` from your knowledge of psychology
- Try radical approaches (very high/low temperature, minimal techniques, etc.)
- Read the scenario outputs and craft techniques that address specific failure modes

The loop runs until the human interrupts you, period.
