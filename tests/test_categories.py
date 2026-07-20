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
