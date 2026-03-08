# EQ Research: Autonomous Emotional Intelligence Optimization for Product Bots

An autonomous research loop that evolves product bot prompts for emotional intelligence —
using the same keep/discard methodology as [karpathy/autoresearch](https://github.com/karpathy/autoresearch),
but applied to prompt engineering instead of model training.

## How It Works

```
┌─────────────────────────────────────────────────┐
│              EQ RESEARCH LOOP                   │
│                                                 │
│  1. Generate customer scenario (emotion + need) │
│  2. Bot responds using current prompt strategy  │
│  3. EQ Judge scores: empathy, tone, resolution  │
│  4. Mutate prompt → re-run → re-score           │
│  5. Keep if better, discard if worse             │
│  6. REPEAT FOREVER                              │
└─────────────────────────────────────────────────┘
```

## The Fun Part

The system simulates **emotionally complex customers**:
- Frustrated returns ("This is the THIRD time...")
- Confused first-timers ("I don't even know what I need")
- Angry escalations ("Let me speak to your manager")
- Anxious big-purchase buyers ("This is a lot of money for me...")
- Delighted repeat customers ("I LOVE your products!")

And evolves prompt strategies like a skilled human agent would use:
- Emotional mirroring
- De-escalation techniques
- Empathetic acknowledgment before problem-solving
- Matching energy (enthusiastic with enthusiastic, calm with anxious)

## Quick Start

```bash
# Set your Gemini API key
export GEMINI_API_KEY="your-key-here"

# Run the autonomous loop
python eq_research/run.py

# Or run a single evaluation
python eq_research/run.py --single
```

## Files

- `scenarios.py` — Customer emotion simulator (generates realistic scenarios)
- `judge.py` — EQ scoring engine (LLM-as-judge for empathy/tone/helpfulness)
- `evolve.py` — Prompt mutation engine (evolves strategies)
- `run.py` — Main autonomous loop
- `strategies/` — Evolved prompt strategies (kept/discarded)
- `results.tsv` — Experiment log
- `program.md` — Instructions for autonomous agents
