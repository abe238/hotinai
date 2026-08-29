from hotin.categories import classify


def test_topic_agent_classifies_as_agents():
    assert classify("Crew", "agent framework", ["agent"]) == "agents"


def test_category_ties_use_declared_priority_order():
    assert classify("Coder", "", ["agent", "coding-agent"]) == "agents"


def test_tts_classifies_as_creative_media():
    assert classify("Voice Box", "text-to-speech model", []) == "creative-media"


def test_word_boundary_does_not_match_rag_inside_storage():
    assert classify("Store", "A storage service", None) == "uncategorized"


def test_unrelated_repository_is_uncategorized():
    assert classify("Calendar", "Personal appointments", "not-a-list") == "uncategorized"


# Pins existing repo classifications against the L1 vocabulary widening (adding
# paper/model/news-oriented terms must never re-score a repo that already
# classified before those terms existed — a real flip was caught by review).
def test_generic_english_words_never_became_keywords():
    assert classify("x", "audio transcription with efficient on-device models", []) == "creative-media"
    assert classify("Project planning app", "", []) == "uncategorized"
    assert classify("x", "reasoning over resumes", []) == "uncategorized"


def test_compound_keyword_matches_space_as_well_as_hyphen():
    # repo topics hyphenate ("multi-agent"); paper/model/news prose doesn't.
    assert classify("", "a multi-agent orchestration framework", []) == "agents"
    assert classify("", "a multi agent orchestration framework", []) == "agents"


def test_classify_generalizes_to_paper_and_model_and_news_text():
    assert classify("DocReason", "an OCR pipeline for document understanding", None) == "app-building"
    assert classify("Mini-8B", "an open weights small model for on-device inference", None) == "inference"
    assert classify("New agentic reasoning model ships", "", None) == "agents"


def test_writing_content_category_covers_the_measured_gap():
    # These are the click-proven items that sat in "uncategorized" for weeks:
    # visitors opened them, but no category matched, so they were invisible to
    # every tag-based surface (measured 2026-08-29).
    assert classify("no-ai-slop", "Removes 20+ patterns of AI slop from any piece of writing.", []) == "writing-content"
    assert classify("ai-copywriter", "An AI copywriting assistant", []) == "writing-content"
    assert classify("anydoc", "Convert Word, PowerPoint and PDF to clean Markdown.", []) == "writing-content"


def test_skills_is_its_own_artifact_class():
    assert classify("scroll-craft", "Claude Code skill for scroll-driven websites", []) == "skills"
    assert classify("some-pack", "", ["agent-skills"]) == "skills"


def test_new_categories_do_not_steal_the_existing_ones():
    # ties resolve by CATEGORIES order, so the older categories keep their own
    assert classify("crewai", "multi-agent orchestration framework", ["agent"]) == "agents"
    assert classify("llamacpp", "GGUF quantized local inference", ["inference"]) == "inference"
    assert classify("cursor", "code-editor with completion", ["ide"]) == "dev-tools"
    assert classify("sd-webui", "stable-diffusion image-generation", ["diffusion"]) == "creative-media"
