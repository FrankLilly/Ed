"""
Training Data Preparation Script

Converts your product knowledge into training-ready format
for fine-tuning with Unsloth + QLoRA.

Usage:
    python prepare_data.py --input raw_data.jsonl --output training_data.jsonl

Input format (raw_data.jsonl) - one JSON per line:
    {"question": "What is X?", "answer": "X is ..."}

Output format (training_data.jsonl) - chat format for Qwen:
    {"conversations": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
"""

import json
import argparse
import random
from pathlib import Path


SYSTEM_PROMPT = (
    "You are a helpful product expert. Answer questions accurately and concisely "
    "based on your training. If you don't know something, say so honestly."
)


def load_raw_data(input_path: str) -> list[dict]:
    """Load raw Q&A pairs from JSONL file."""
    data = []
    path = Path(input_path)

    if path.suffix == ".jsonl":
        with open(path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    data.append(item)
                except json.JSONDecodeError:
                    print(f"Warning: Skipping invalid JSON on line {line_num}")

    elif path.suffix == ".json":
        with open(path) as f:
            loaded = json.load(f)
            if isinstance(loaded, list):
                data = loaded
            else:
                data = [loaded]

    elif path.suffix == ".csv":
        import csv
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(dict(row))

    else:
        raise ValueError(f"Unsupported file format: {path.suffix}. Use .jsonl, .json, or .csv")

    print(f"Loaded {len(data)} examples from {input_path}")
    return data


def validate_item(item: dict, index: int) -> bool:
    """Check that an item has required fields."""
    if "question" not in item or "answer" not in item:
        print(f"Warning: Skipping item {index} - missing 'question' or 'answer' field")
        return False
    if not item["question"].strip() or not item["answer"].strip():
        print(f"Warning: Skipping item {index} - empty question or answer")
        return False
    return True


def format_for_training(item: dict, include_system: bool = True) -> dict:
    """Convert a Q&A pair to chat format for Qwen fine-tuning."""
    conversations = []

    if include_system:
        conversations.append({
            "role": "system",
            "content": SYSTEM_PROMPT,
        })

    conversations.append({
        "role": "user",
        "content": item["question"].strip(),
    })

    conversations.append({
        "role": "assistant",
        "content": item["answer"].strip(),
    })

    return {"conversations": conversations}


def split_data(data: list[dict], val_ratio: float = 0.1) -> tuple[list[dict], list[dict]]:
    """Split data into train and validation sets."""
    random.shuffle(data)
    split_idx = max(1, int(len(data) * (1 - val_ratio)))
    return data[:split_idx], data[split_idx:]


def save_jsonl(data: list[dict], output_path: str):
    """Save data as JSONL file."""
    with open(output_path, "w") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Saved {len(data)} examples to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Prepare training data for LLM fine-tuning")
    parser.add_argument("--input", required=True, help="Path to raw data file (.jsonl, .json, or .csv)")
    parser.add_argument("--output", default="training_data.jsonl", help="Output path for training data")
    parser.add_argument("--val-output", default=None, help="Output path for validation data")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio (default: 0.1)")
    parser.add_argument("--no-system", action="store_true", help="Don't include system prompt")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    random.seed(args.seed)

    # Load and validate
    raw_data = load_raw_data(args.input)
    valid_data = [item for i, item in enumerate(raw_data) if validate_item(item, i)]
    print(f"Valid examples: {len(valid_data)}/{len(raw_data)}")

    if not valid_data:
        print("Error: No valid training examples found!")
        return

    # Format for training
    formatted = [format_for_training(item, include_system=not args.no_system) for item in valid_data]

    # Split and save
    if args.val_output or args.val_ratio > 0:
        train_data, val_data = split_data(formatted, args.val_ratio)
        save_jsonl(train_data, args.output)
        val_path = args.val_output or args.output.replace(".jsonl", "_val.jsonl")
        save_jsonl(val_data, val_path)
    else:
        save_jsonl(formatted, args.output)

    print("\nDone! Your data is ready for fine-tuning.")
    print(f"Next step: Upload {args.output} to Google Colab and run the training notebook.")


if __name__ == "__main__":
    main()
