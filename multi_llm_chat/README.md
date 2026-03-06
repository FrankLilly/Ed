# Multi-LLM Chatbox

A shared chatbox where 3 LLMs (GPT-4, Claude, and Gemini) collaborate in real-time. All models see the full conversation — your messages and each other's responses — so they can build on ideas, disagree, and work together.

## Setup

1. **Install dependencies:**
   ```bash
   cd multi_llm_chat
   pip install -r requirements.txt
   ```

2. **Configure API keys** — copy `.env.example` to `.env` and fill in your keys:
   ```bash
   cp .env.example .env
   ```
   You need keys for:
   - [OpenAI](https://platform.openai.com/api-keys) → `OPENAI_API_KEY`
   - [Anthropic](https://console.anthropic.com/) → `ANTHROPIC_API_KEY`
   - [Google AI Studio](https://aistudio.google.com/apikey) → `GOOGLE_API_KEY`

3. **Run:**
   ```bash
   python app.py
   ```
   Open http://localhost:5000 in your browser.

## How It Works

- You type a message → it's sent to all 3 LLMs **in parallel**
- Each LLM receives the **full conversation history** including messages from the other two AIs
- Responses stream back and appear in the chat with color-coded labels
- The models can reference, agree with, or challenge each other's responses

## Architecture

```
User Input
    │
    ├──→ OpenAI (GPT-4o)    ──→ ┐
    ├──→ Anthropic (Claude)  ──→ ├──→ Shared Chat History
    └──→ Google (Gemini)     ──→ ┘
                                    │
                              ┌─────┘
                              ▼
                         Web UI (SSE)
```

- **Backend**: Flask with Server-Sent Events for streaming
- **LLM calls**: Parallel via threading
- **State**: In-memory shared conversation history
