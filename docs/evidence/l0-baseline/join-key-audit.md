# L0 — click→item join-key audit

Re-verified at HEAD c4a6964 (2026-07-26).

`docs/index.html`, the `select_result` click handler:
```js
var item=(firstNode&&firstNode.nodeType===3)?firstNode.textContent.trim():a.textContent.trim();
ga('select_result',{tab:entity,rank:rank,item:item});
```

**Gap confirmed:** `item` is the row's rendered display text, not a stable id.
`render_board.py`'s row markup carries no `data-id` (or any) attribute today —
grepped for `data-` and found none on `.row` divs. `tags.json`/`clicks.json` will
be keyed by `entity_id`/`canonical_repo` (a stable slug), so a display-text join
would silently mis-join (HN/Reddit-sourced titles differ from their slug) or
collide (two items with the same visible name). L1 (T1a) fixes this by adding
`data-id` to the row markup and a new `id` param to the click event, then
registering `id` as a GA4 custom dimension immediately — starting the ~24-48h
processing-lag clock as early as possible, ahead of L2's first real pull.
