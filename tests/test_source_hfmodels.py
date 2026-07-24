import json

from hotin.sources import hfmodels


CARD = """---
license: mit
pipeline_tag: image-text-to-text
---

# Unlimited OCR

![banner](assets/banner.png)

```python
tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
model = AutoModel.from_pretrained(model_name)
```

| a | b |
|---|---|

Unlimited OCR is a vision-language model for one-shot long-horizon
document parsing across images and multi-page PDFs.

More detail below.
"""


def test_card_first_paragraph_skips_frontmatter_fences_and_code():
    para = hfmodels.card_first_paragraph(CARD)
    assert para is not None
    assert para.startswith("Unlimited OCR is a vision-language model")
    assert "AutoTokenizer" not in para
    assert "More detail" not in para  # only the first paragraph


def test_card_first_paragraph_skips_bullets_and_normalizes_dashes():
    card = """# Release notes

- [2026/07/21] Thanks to the community for their support
* another bullet
1. numbered item

Bonsai runs full 27B-class reasoning — in binary transformer weights — for llama.cpp everywhere.
"""
    para = hfmodels.card_first_paragraph(card)
    assert para == ("Bonsai runs full 27B-class reasoning, in binary transformer "
                    "weights, for llama.cpp everywhere.")


def test_card_first_paragraph_hostile_inputs():
    assert hfmodels.card_first_paragraph(None) is None
    assert hfmodels.card_first_paragraph("") is None
    assert hfmodels.card_first_paragraph("# only a heading\n\n![badge](x)") is None
    assert hfmodels.card_first_paragraph("too short") is None


def test_parse_models_captures_gated_flag():
    payload = [
        {"id": "a/open", "downloads": 1, "likes": 1, "gated": False},
        {"id": "b/gated", "downloads": 1, "likes": 1, "gated": "manual"},
    ]
    records = hfmodels.parse_models(payload)
    metas = {r["entity_id"]: r["meta"] for r in records}
    assert "model_gated" not in metas["a/open"]
    assert metas["b/gated"]["model_gated"] is True


class FakeCache:
    def __init__(self, rows):
        self.rows = rows
        self.upserts = []

    def get_all(self):
        return list(self.rows)

    def upsert(self, record):
        self.upserts.append(record)


def _model_row(mid, meta):
    return {"entity_type": "model", "entity_id": mid, "source": "hfmodels",
            "fetched_at": 9.0,
            "signal_json": json.dumps({"signal": {"model_likes": 1}, "meta": meta})}


def test_backfill_descriptions_heals_and_remembers_empty(monkeypatch):
    cache = FakeCache([
        _model_row("a/one", {"model_task": "x"}),                       # healed
        _model_row("b/two", {"model_description": "already"}),          # skipped
        _model_row("c/three", {"model_description": ""}),               # "" = known-empty, skipped
        _model_row("d/four", {"model_task": "y"}),                      # no prose -> "" cached
    ])
    monkeypatch.setattr(hfmodels, "fetch_description",
                        lambda mid: {"a/one": "A fine model for things."}.get(mid))
    healed = hfmodels.backfill_descriptions(cache)
    assert healed == 2  # a/one healed with prose, d/four cached as ""
    metas = {u["entity_id"]: u["signal_json"]["meta"] for u in cache.upserts}
    assert metas["a/one"]["model_description"] == "A fine model for things."
    assert metas["d/four"]["model_description"] == ""
    assert cache.upserts[0]["fetched_at"] == 9.0
