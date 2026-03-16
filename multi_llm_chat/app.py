import os
import json
import threading
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from dotenv import load_dotenv
from openai import OpenAI
from google import genai

load_dotenv()

app = Flask(__name__)

# ── LLM clients (lazy-init so app starts even without keys) ─────────────────
_openai_client = None
_claude_client = None
_gemini_client = None


def get_openai():
    global _openai_client
    if _openai_client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set in .env")
        _openai_client = OpenAI(api_key=key)
    return _openai_client


def get_claude():
    global _claude_client
    if _claude_client is None:
        key = os.getenv("VENICE_API_KEY")
        if not key:
            raise RuntimeError("VENICE_API_KEY not set in .env")
        _claude_client = OpenAI(api_key=key, base_url="https://api.venice.ai/api/v1")
    return _claude_client


def get_gemini():
    global _gemini_client
    if _gemini_client is None:
        key = os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GOOGLE_API_KEY not set in .env")
        _gemini_client = genai.Client(api_key=key)
    return _gemini_client

# ── Shared conversation state ──────────────────────────────────────────────────
conversation_history: list[dict] = []
lock = threading.Lock()

SYSTEM_PROMPT = (
    "You are one of three AI assistants in a shared chatbox. "
    "You can see all messages from the user and from the other two AIs. "
    "Collaborate, build on each other's ideas, respectfully disagree when needed, "
    "and help the user by bringing your unique perspective. Keep responses concise."
)

LLM_CONFIG = {
    "gpt4": {
        "name": "GPT-4",
        "color": "#10a37f",
        "model": "gpt-4o",
    },
    "claude": {
        "name": "Claude",
        "color": "#d97706",
        "model": "claude-sonnet-4-6",
    },
    "gemini": {
        "name": "Gemini",
        "color": "#4285f4",
        "model": "gemini-2.0-flash",
    },
}


def _build_messages_for_openai(self_key: str) -> list[dict]:
    """Build message list in OpenAI chat format from shared history."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for entry in conversation_history:
        if entry["source"] == "user":
            msgs.append({"role": "user", "content": entry["content"]})
        else:
            label = LLM_CONFIG.get(entry["source"], {}).get("name", entry["source"])
            msgs.append({
                "role": "assistant" if entry["source"] == self_key else "user",
                "content": f"[{label}]: {entry['content']}",
            })
    return msgs


def _build_messages_for_gemini() -> list[dict]:
    """Build message list for Google Gemini from shared history."""
    msgs = [{"role": "user", "parts": [{"text": f"System instruction: {SYSTEM_PROMPT}"}]}]
    msgs.append({"role": "model", "parts": [{"text": "Understood. I'm Gemini, one of three AIs in this shared chat."}]})
    for entry in conversation_history:
        if entry["source"] == "user":
            msgs.append({"role": "user", "parts": [{"text": entry["content"]}]})
        else:
            label = LLM_CONFIG.get(entry["source"], {}).get("name", entry["source"])
            role = "model" if entry["source"] == "gemini" else "user"
            msgs.append({"role": role, "parts": [{"text": f"[{label}]: {entry['content']}"}]})
    # Merge consecutive same-role messages
    merged: list[dict] = []
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["parts"][0]["text"] += "\n" + m["parts"][0]["text"]
        else:
            merged.append(dict(m))
    return merged


# ── LLM call functions ─────────────────────────────────────────────────────────

def call_gpt4() -> str:
    msgs = _build_messages_for_openai("gpt4")
    resp = get_openai().chat.completions.create(
        model=LLM_CONFIG["gpt4"]["model"],
        messages=msgs,
        max_tokens=1024,
    )
    return resp.choices[0].message.content


def call_claude() -> str:
    msgs = _build_messages_for_openai("claude")
    resp = get_claude().chat.completions.create(
        model=LLM_CONFIG["claude"]["model"],
        messages=msgs,
        max_tokens=1024,
    )
    return resp.choices[0].message.content


def call_gemini() -> str:
    msgs = _build_messages_for_gemini()
    resp = get_gemini().models.generate_content(
        model=LLM_CONFIG["gemini"]["model"],
        contents=msgs,
    )
    return resp.text


LLM_CALLERS = {
    "gpt4": call_gpt4,
    "claude": call_claude,
    "gemini": call_gemini,
}


# ── Routes ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", llm_config=LLM_CONFIG)


@app.route("/chat", methods=["POST"])
def chat():
    """Accept user message, query all 3 LLMs, stream results back via SSE."""
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    with lock:
        conversation_history.append({"source": "user", "content": user_msg})

    def generate():
        results = {}
        errors = {}

        def _call(key):
            try:
                results[key] = LLM_CALLERS[key]()
            except Exception as e:
                errors[key] = str(e)

        threads = [threading.Thread(target=_call, args=(k,)) for k in LLM_CALLERS]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for key in ["gpt4", "claude", "gemini"]:
            if key in results:
                with lock:
                    conversation_history.append({"source": key, "content": results[key]})
                yield f"data: {json.dumps({'source': key, 'content': results[key]})}\n\n"
            elif key in errors:
                yield f"data: {json.dumps({'source': key, 'error': errors[key]})}\n\n"

        yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/history")
def history():
    with lock:
        return jsonify(conversation_history)


@app.route("/reset", methods=["POST"])
def reset():
    with lock:
        conversation_history.clear()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
