# L3 tracer — embedding nearest-neighbor inspection

Per chain/LOOP_CHAIN_2026-07-26.md L3's first step: compute embeddings as a
READ-ONLY artifact, manually inspect whether the space clusters on the
*editorial* dimension, report to Abe BEFORE writing any propagation code.
This is that report. No propagation/matching logic exists yet.

Model: sentence-transformers/all-MiniLM-L6-v2 (local, free — Abe's explicit
choice over a paid API). 279 items embedded from the live corpus (repos +
rising + insiders deduped by entity_id, + models, papers, news).

## One hand-picked exemplar per confirmed category, top-5 nearest neighbors

**agents** (`vercel-labs/deepsec`) — all 5 nearest neighbors share the tag,
similarity 0.46–0.58. Strong, clean clustering.

**dev-tools** (`xai-org/grok-build`) — only 1/5 neighbors share the tag; the
other 4 are "agents" at LOWER similarity (0.32–0.36) than the agents
exemplar's own neighbors. Weak clustering — dev-tools is a smaller, more
diffuse category and gets pulled toward the much larger "agents" cluster.

**creative-media** (`hoainho/img2threejs`) — top match at 0.921 similarity
is `img2threejs/img2threejs`, an almost-certainly-duplicate entity (same
project, different owner-slug key) — see "data-quality finding" below.
Second-tier matches (0.32–0.40) are genuine same-category neighbors.

**app-building** (`baidu/unlimited-ocr`) — top match at 0.766 is
`baidu/Unlimited-OCR` — same repo, different casing in the entity_id. Same
duplicate-key issue as above.

**inference** (`antirez/ds4`) — mixed but semantically plausible neighbors
(other quantized/GGUF models, one training-tagged item that's genuinely
inference-adjacent). No near-duplicate inflation here.

**training** (`bottlecapai/ThinkingCap-Qwen3.6-27B`) — top match at 0.910 is
`bottlecapai/ThinkingCap-Qwen3.6-27B-GGUF`: the SAME model's GGUF-quantized
release, tagged "inference" instead of "training" by the keyword classifier
(because "GGUF" is a strong inference keyword). The embeddings correctly see
these as near-identical text — it's the keyword-based ground truth that's
inconsistent between a model and its own quantized variant.

## Honest findings, not just the good ones

1. **Well-populated categories cluster well.** "agents" (the largest
   category at 85/279 items) shows tight, high-confidence clustering. This
   is the strongest evidence the mechanism can work.
2. **Sparse/diffuse categories don't cluster as tightly** and get pulled
   toward larger neighboring clusters (dev-tools -> agents). Exemplar
   propagation for small categories will need a stricter similarity
   threshold than large ones, or accept a higher false-tag rate there.
3. **Real data-quality issue found, not an embedding-model issue:** the
   corpus contains near-duplicate entity_ids for the same underlying
   item — same repo/model under different owner-casing or a base-model vs
   its own GGUF-quantized release. These pairs score suspiciously high
   similarity (0.77–0.92) because they're nearly the same text, not because
   the embedding space is doing anything interesting. **This is a real risk
   for exemplar propagation:** a near-duplicate could get counted as
   independent corroborating evidence when it's really the same underlying
   thing counted twice. Multi-exemplar consensus and a near-duplicate guard
   (e.g. skip matches above ~0.85 similarity as likely-duplicate, not
   likely-same-category) should be added to the propagation design, not
   assumed away.
4. **Keyword-classifier ground truth itself is sometimes inconsistent**
   between near-identical releases (the ThinkingCap base/GGUF pair). Exemplar
   propagation could either fix this (a good argument for the mechanism) or
   propagate whichever tag got confirmed first (a real risk the chain doc's
   multi-exemplar-consensus guardrail exists to bound, not eliminate).

## Verdict
The embedding space clusters meaningfully on the editorial dimension for the
corpus's largest categories — real signal, not noise. It is weaker for small
categories and needs an explicit near-duplicate guard before propagation
logic is safe to write. Recommend: add a near-duplicate similarity ceiling
(skip candidate matches above ~0.85 as likely-duplicate) to the guardrail
list already planned (one-hop cap, multi-exemplar consensus, re-verification
loop) before writing any propagation code.
