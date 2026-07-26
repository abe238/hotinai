"""Deterministic, explainable categories for AI items — repos, papers, models,
and news headlines alike. One shared vocabulary across entity types, on
purpose: pattern-mining needs "agent-orchestration" to mean the same thing
whether it tags a repo, a paper, or a model release, so the topic list is
NOT split per entity type — only the description text fed into ``classify``
changes per caller (see cli.py:_export)."""

from __future__ import annotations

import re
from typing import Optional


CATEGORIES = [
    ("agents", ["agent", "agents", "agentic", "multi-agent", "autonomous", "mcp",
                "model-context-protocol", "orchestration", "crewai", "langgraph", "autogen",
                "tool-use", "ai-agent", "llm-agent", "agentic-workflow", "agentic-reasoning"]),
    ("creative-media", ["text-to-image", "text-to-video", "image-generation", "video-generation",
                "stable-diffusion", "diffusion", "text-to-speech", "speech-to-text", "tts", "stt",
                "voice", "avatar", "animation", "comfyui", "lip-sync", "music-generation",
                "image-editing", "audio", "video"]),
    ("inference", ["inference", "llamacpp", "llama-cpp", "gguf", "quantization", "quantized",
                "vllm", "ollama", "serving", "local-llm", "on-device", "tensorrt", "llm-serving",
                "edge-ai", "open-weights", "distilled-model", "small-model"]),
    ("training", ["fine-tuning", "finetuning", "fine-tune", "lora", "qlora", "peft", "rlhf",
                "dpo", "sft", "pretraining", "pre-training", "distillation", "training"]),
    ("app-building", ["rag", "retrieval", "retrieval-augmented", "vector-database",
                "vector-search", "vector-store", "embeddings", "embedding", "semantic-search",
                "chatbot", "langchain", "llamaindex", "knowledge-base", "prompt-engineering",
                "chat-ui", "llm-app", "ocr", "document-understanding", "multimodal"]),
    ("dev-tools", ["cli", "command-line", "developer-tools", "devtools", "ide", "vscode",
                "neovim", "jetbrains", "copilot", "code-review", "code-completion",
                "coding-assistant", "coding-agent", "code-editor", "code-generation", "terminal",
                "tui", "linter", "formatter", "debugger", "sdk"]),
]

def _pattern_for(keyword: str) -> "re.Pattern":
    # Repo topics write compound terms hyphenated ("multi-agent"); free-text
    # prose (paper abstracts, news headlines) writes the same phrase with a
    # space ("multi agent"). Match either so classify() generalizes past
    # repo topic tags — a single-word keyword is unaffected (nothing to split).
    body = r"[-\s]".join(re.escape(part) for part in keyword.split("-"))
    return re.compile(r"(?<!\w){}(?!\w)".format(body), re.IGNORECASE)


_PATTERNS = {
    keyword: _pattern_for(keyword)
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
    # classify() is entity-type-agnostic by design — a paper abstract, a model
    # card blurb, and a news headline all classify through the same path.
    # Natural prose writes compound terms with a SPACE ("multi agent"), not
    # the hyphen a repo topic tag would use ("multi-agent") — both must match.
    assert classify(
        "DocReason", "An OCR pipeline for document understanding that agents can call as a tool", None
    ) == "app-building"
    assert classify(
        "Mini-8B", "An open weights small model distilled for on-device inference", None
    ) == "inference"
    assert classify("New agentic reasoning model ships", "", None) == "agents"
    assert classify("", "a multi agent orchestration framework", None) == "agents"  # space, not hyphen
