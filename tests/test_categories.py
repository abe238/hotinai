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
