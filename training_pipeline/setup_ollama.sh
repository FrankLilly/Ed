#!/bin/bash
# =============================================================
# Local Ollama Setup for MacBook Air M2
#
# Run this script after downloading your fine-tuned GGUF model
# from Google Colab.
#
# Usage:
#   chmod +x setup_ollama.sh
#   ./setup_ollama.sh <path-to-your-gguf-file>
#
# Example:
#   ./setup_ollama.sh ~/Downloads/my-product-expert-Q4_K_M.gguf
# =============================================================

set -e

GGUF_PATH="${1:-}"
MODEL_NAME="my-product-expert"

if [ -z "$GGUF_PATH" ]; then
    echo "Usage: ./setup_ollama.sh <path-to-gguf-file>"
    echo "Example: ./setup_ollama.sh ~/Downloads/my-product-expert-Q4_K_M.gguf"
    exit 1
fi

if [ ! -f "$GGUF_PATH" ]; then
    echo "Error: File not found: $GGUF_PATH"
    exit 1
fi

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "Ollama not found. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install ollama
    else
        curl -fsSL https://ollama.com/install.sh | sh
    fi
fi

# Create Modelfile
MODELFILE_PATH="$(dirname "$0")/Modelfile"
cat > "$MODELFILE_PATH" << EOF
FROM $GGUF_PATH

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 2048
PARAMETER stop <|im_end|>

SYSTEM """You are a helpful product expert. Answer questions accurately and concisely based on your training. If you don't know something, say so honestly."""

TEMPLATE """<|im_start|>system
{{ .System }}<|im_end|>
<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
{{ .Response }}<|im_end|>"""
EOF

echo "Created Modelfile at: $MODELFILE_PATH"

# Import into Ollama
echo "Importing model into Ollama..."
ollama create "$MODEL_NAME" -f "$MODELFILE_PATH"

echo ""
echo "=============================="
echo "Setup complete!"
echo "=============================="
echo ""
echo "Run your model:"
echo "  ollama run $MODEL_NAME"
echo ""
echo "Or use the API:"
echo "  curl http://localhost:11434/api/generate -d '{"
echo "    \"model\": \"$MODEL_NAME\","
echo "    \"prompt\": \"What does your product do?\""
echo "  }'"
