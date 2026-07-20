"""Deterministic, explainable categories for AI repositories."""

from __future__ import annotations

import re
from typing import Optional


CATEGORIES = [
    ("agents", ["agent", "agents", "agentic", "multi-agent", "autonomous", "mcp",
                "model-context-protocol", "orchestration", "crewai", "langgraph", "autogen",
                "tool-use", "ai-agent", "llm-agent"]),
    ("creative-media", ["text-to-image", "text-to-video", "image-generation", "video-generation",
                "stable-diffusion", "diffusion", "text-to-speech", "speech-to-text", "tts", "stt",
                "voice", "avatar", "animation", "comfyui", "lip-sync", "music-generation",
                "image-editing", "audio", "video"]),
    ("inference", ["inference", "llamacpp", "llama-cpp", "gguf", "quantization", "quantized",
                "vllm", "ollama", "serving", "local-llm", "on-device", "tensorrt", "llm-serving",
                "edge-ai"]),
    ("training", ["fine-tuning", "finetuning", "fine-tune", "lora", "qlora", "peft", "rlhf",
                "dpo", "sft", "pretraining", "pre-training", "distillation", "training"]),
    ("app-building", ["rag", "retrieval", "retrieval-augmented", "vector-database",
                "vector-search", "vector-store", "embeddings", "embedding", "semantic-search",
                "chatbot", "langchain", "llamaindex", "knowledge-base", "prompt-engineering",
                "chat-ui", "llm-app"]),
    ("dev-tools", ["cli", "command-line", "developer-tools", "devtools", "ide", "vscode",
                "neovim", "jetbrains", "copilot", "code-review", "code-completion",
                "coding-assistant", "coding-agent", "code-editor", "code-generation", "terminal",
                "tui", "linter", "formatter", "debugger", "sdk"]),
]

_PATTERNS = {
    keyword: re.compile(r"(?<!\w){}(?!\w)".format(re.escape(keyword)), re.IGNORECASE)
    for _, keywords in CATEGORIES for keyword in keywords
}


def classify(name: str, description: Optional[str], topics: Optional[list]) -> str:
    """Classify a repository, resolving equal scores by category list order."""
    text = "{} {}".format(name if isinstance(name, str) else "", description if isinstance(description, str) else "")
    topic_set = {
        topic.casefold() for topic in topics
        if isinstance(topic, str)
    } if isinstance(topics, list) else set()
    best_category = "uncategorized"
    best_score = 0
    for category, keywords in CATEGORIES:
        score = sum(
            (2 if keyword.casefold() in topic_set else 0)
            + (1 if _PATTERNS[keyword].search(text) else 0)
            for keyword in keywords
        )
        if score > best_score:
            best_category, best_score = category, score
    return best_category


def selftest() -> None:
    """Small executable smoke test for the category contract."""
    assert classify("Crew", "", ["agent"]) == "agents"
    assert classify("Coder", "", ["agent", "coding-agent"]) == "agents"
    assert classify("Voice maker", "text-to-speech", []) == "creative-media"
    assert classify("Storage", "A storage layer", []) == "uncategorized"
    assert classify("Calendar", "Personal appointments", None) == "uncategorized"
