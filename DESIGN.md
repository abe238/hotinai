---
name: hotin
description: What's hot in AI, from your terminal.
colors:
  terminal-void: "#0a0e14"
  console-panel: "#111722"
  wire-border: "#1e2733"
  phosphor-white: "#e6edf3"
  muted-slate: "#8b98a9"
  faint-slate: "#7a8696"
  signal-green: "#3fdd8a"
  signal-green-soft: "#7ee9ae"
  prompt-amber: "#f2b45c"
  status-violet: "#a98bf5"
  panel-raise: "#0e141d"
  terminal-inner: "#080c12"
  receipt-cyan: "#48c9d6"
  src-npm: "#e06c5f"
  src-hn: "#ff922b"
  src-reddit: "#ff6b4a"
  src-stars: "#f2c65c"
  edge-amber: "#5c4728"
  edge-green: "#1f5a3f"
  edge-cyan: "#2b5a61"
  edge-violet: "#3c3556"
  trend-dim: "#9a8fc4"
typography:
  display:
    fontFamily: "Iowan Old Style, Palatino Linotype, Palatino, Georgia, serif"
    fontSize: "clamp(34px, 7.5vw, 60px)"
    fontWeight: 600
    lineHeight: 1.08
    letterSpacing: "-0.02em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    letterSpacing: "0.06em"
  ui-label:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "14px"
    fontWeight: 400
    letterSpacing: "normal"
  mono-row:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.9
  caption:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "11px"
    fontWeight: 400
    letterSpacing: "0.02em"
rounded:
  chip: "5px"
  sm: "8px"
  md: "10px"
  lg: "12px"
  pill: "20px"
spacing:
  sm: "14px"
  md: "20px"
  lg: "36px"
components:
  button-primary:
    backgroundColor: "{colors.console-panel}"
    textColor: "{colors.signal-green}"
    rounded: "{rounded.sm}"
    padding: "11px 20px"
  button-secondary:
    backgroundColor: "{colors.console-panel}"
    textColor: "{colors.phosphor-white}"
    rounded: "{rounded.sm}"
    padding: "11px 20px"
  prompt-chip:
    backgroundColor: "{colors.console-panel}"
    textColor: "{colors.prompt-amber}"
    rounded: "{rounded.md}"
    padding: "14px 20px"
---

# Design System: hotin

## 1. Overview

**Creative North Star: "The Terminal That Talks Back"**

hotin.ai is a single dark hero built around one idea: don't describe the tool, run it. The centerpiece is a windowed terminal panel that live-types `$ hotin` and stages a ranked result list into view on load — the actual product experience, staged as the page's own hero image, not a stock screenshot or an icon grid. Everything else is quiet by comparison: a near-black, blue-tinted void lit by a single green signal color, a serif headline as the one warm human voice against otherwise all-monospace chrome, and copy that's honest and a little wry rather than corporate ("still cooking · install anyway" instead of a construction-cone cliché). Two soft radial gradients keep the flat black from feeling empty without ever reaching for a gradient-fill hero.

**Key Characteristics:**
- A live-staged terminal demo as the hero image — show, don't tell, taken literally
- Near-black terminal void, lit by a single green signal color, not a neutral dark gray
- Serif display against all-monospace UI chrome: one deliberate contrast axis, not a font family per element
- Flat by construction: no shadows anywhere; depth comes from hairline borders and radial color glow
- Honest, wry copy over corporate polish: no fake proof, no "under construction" cliché, no eyebrow-kicker scaffolding
- Every accent color has a single, literal job: green = the "hot" signal, amber = terminal prompt output, violet = system status

## 2. Colors

A near-black terminal palette where accent colors are assigned literal roles (signal, output, status), not decorative rotation.

### Primary
- **Signal Green** (#3fdd8a): the "hot" in the headline, the primary button's border and text, the blinking terminal cursor, and every hover state. This is the brand's one recognizable color: the "hot right now" signal itself.

### Secondary
- **Prompt Amber** (#f2b45c): reserved for the `$ hotin` line inside the terminal panel. Never used elsewhere; its rarity is what makes that line read as literal terminal output rather than another UI element.

### Tertiary
- **Status Violet** (#a98bf5): the status pill and the ranked rows' source tags (`↑ npm · HN #1`) inside the terminal demo. A third accent kept this narrow avoids the full-palette drift into decorative color.

### Neutral
- **Terminal Void** (#0a0e14): page background. Not a neutral gray; carries a cold blue undertone consistent with a CRT/terminal glow.
- **Console Panel** (#111722): the fill behind every bordered surface (the terminal panel, buttons) — one step lighter than the void, never used as a full-bleed background.
- **Wire Border** (#1e2733): the hairline border on every panel surface, including the terminal window's title-bar divider; the sole source of structure in a shadow-free system.
- **Phosphor White** (#e6edf3): primary text, the secondary button's label, and the terminal demo's repo names. Cool white, not a warm off-white.
- **Muted Slate** (#8b98a9): the subhead paragraph and the footer. Passes AA contrast at normal body size (6.6:1).
- **Faint Slate** (#7a8696): the `$` prefix and the terminal window's title-bar label only — the quietest tone in the system, reserved for things meant to recede. Lightened from an earlier value that failed AA contrast (3.3:1) for real body text; kept only where the text is decorative, not load-bearing.

### Named Rules
**The One Job Rule.** Every accent color (signal, amber, violet) has exactly one assigned use across the page. None are reused decoratively elsewhere; that restraint is what keeps three saturated colors on a near-black field from feeling loud.

## 3. Typography

**Display Font:** Iowan Old Style (with Palatino Linotype, Palatino, Georgia fallback)
**Body Font:** -apple-system / system sans stack
**Label/Mono Font:** ui-monospace (SF Mono, JetBrains Mono, Menlo, Consolas fallback)

**Character:** A humanist serif headline dropped into an otherwise all-monospace terminal interface. The pairing itself is the contrast axis (serif + mono, per the "don't pair similar families" rule) — the serif line is the one human, editorial voice in a page built from console chrome.

### Hierarchy
- **Display** (600, clamp(34px, 7.5vw, 60px), line-height 1.08): the single H1, serif, negative letter-spacing (-0.02em). Sized down slightly from the pre-redesign hero to leave visual room for the terminal panel below it.
- **Body** (400, 17px, line-height 1.6): the subhead paragraph, muted-slate, max-width 480px (well under the 65-75ch line-length ceiling).
- **Label** (400, 12px, letter-spacing 0.06em, mono): the status pill only. Tracking pulled back from the old eyebrow's 0.28em now that no all-caps kicker exists to justify that width.
- **UI Label** (400, 14px, mono, no tracking): button labels, both the primary CTA and the copy-to-clipboard install button.
- **Mono Row** (400, 13.5px, line-height 1.9, mono): the ranked rows inside the terminal demo panel; the generous line-height keeps a dense list breathable.
- **Caption** (400, 11px, mono): the terminal window's title-bar label and the footer's smallest text.

### Named Rules
**The Serif-Is-Singular Rule.** The serif face appears in exactly one place: the H1. Every other piece of type on the page, including body copy, is either system sans or mono. A second serif element would dilute the one moment it's meant to own.

## 4. Elevation

Flat by construction: there is no `box-shadow` anywhere in the stylesheet, including on the new terminal panel. Depth is conveyed two ways instead — hairline borders (`1px solid` wire-border) delineate every panel surface, and two large, soft radial gradients (signal-green at 9% opacity top-right, violet at 6% opacity lower-left) give the flat black body an atmospheric glow rather than a hard, empty void.

### Named Rules
**The No-Shadow Rule.** Depth comes from border + glow, never from `box-shadow`. Introducing a *decorative* drop shadow (elevation, a floating panel) anywhere would contradict the flat terminal-panel language the whole page is built from.

**The One Functional-Glow Exception.** There is exactly one sanctioned `box-shadow` in the system, and it is not depth: the **viral-`trending` badge** carries a soft violet glow as a *signal* (the rare "on multiple trending lists AND accelerating" state). It is the single most-important row-level verdict, and the glow is how it earns prominence without a filled background. This is a functional-color glow, categorically distinct from a decorative elevation shadow, and it is the only exception the No-Shadow Rule permits.

## Output color system (CLI result rows)

Distinct from the page's restrained accent palette (green/amber/violet, one job each), the ranked-result rows use a **functional data-encoding** color layer: each *source* has a fixed hue so the eye learns it once and reads it everywhere. Receipts (numbers) are source-colored; badges (verdicts) are colored outlines.

- **Receipts** (numbers, source-colored): `src-npm` (#e06c5f), `src-hn` (#ff922b), `src-reddit` (#ff6b4a), `src-stars` (#f2c65c).
- **Badges** (outline chips, one hue each): `fresh` → signal-green + edge-green border; `smart-money` → prompt-amber + edge-amber border; `paper-backed` → receipt-cyan + edge-cyan border; `trending` → trend-dim + edge-violet border, escalating to status-violet + glow at viral level.
- **The receipts-vs-badges split is the product's core reading model** and must stay consistent across all three output surfaces (console, markdown, HTML): receipts answer *who points at it* (a number), badges answer *what it means* (a verdict). Terminals can't draw outlines or glow, so the console renders badges as colored/bold text and shows viral intensity via brightness; HTML and markdown use the outline chips.

## 5. Components

### Terminal demo panel (signature component)
The page's hero image, full stop. A console-panel window with a 10px-radius frame: a title bar (three neutral dots, no traffic-light colors — this isn't skeuomorphic macOS chrome, just rhythm — plus a faint-slate "zsh — hotin" label) above a body that live-types `$ hotin`, blinks a signal-green block cursor, then stages three ranked rows into view with a staggered 0.5s fade-and-rise (`0.5s`/`0.75s`/`1s` delays). Rows use mono-row type: a right-aligned rank number (signal-green for the top two, faint-slate below), the repo name in phosphor-white, and a violet source tag. This is the literal product experience staged as marketing imagery — not a screenshot, not an icon, the actual thing.

### Buttons
- **Shape:** 8px radius, monospace UI-label type, no uppercase transform.
- **Primary:** "⭐ Star it on GitHub" — signal-green border and text on a console-panel fill; 11px/18px padding.
- **Secondary:** "$ pipx install hotin" — a real copy-to-clipboard button (not a link), phosphor-white text on the same console-panel fill, wire-border border. On click, swaps its label to "copied ✓" in signal-green for 1.6s.
- **Hover:** border-color transitions to signal-green (soft-green on the already-green primary) over 0.15s, regardless of variant — the hover state is shared, not per-variant.

### Status pill
Mono, sentence case (not uppercase — dropped with the eyebrow), 0.06em tracking, violet text on a violet-tinted (7% opacity) background with a violet border at 35% opacity; 20px radius (full pill). Currently reads "still cooking · install anyway" — honest about pre-launch status without the "🚧 under construction" cliché, and written in the confirmed playful/irreverent voice rather than a corporate placeholder tone.

### Navigation
None; this is a single-hero page with no nav bar. The only navigational elements are the primary CTA (GitHub) and the secondary copy-command button.

## 6. Do's and Don'ts

### Do:
- **Do** keep every accent color (signal-green, prompt-amber, status-violet) to its one assigned job; that restraint is what makes three saturated hues on black read as designed, not decorative.
- **Do** keep depth border-and-glow based; introducing shadows would break the flat terminal-panel language, including on the terminal demo panel itself.
- **Do** keep the serif face confined to the H1; it's a contrast accent, not a family to spread around.
- **Do** keep the terminal demo panel's data honest — it is clearly staged/simulated (illustrative repo names), never dressed up as a live API call, and never implies real usage numbers the project doesn't have yet.
- **Do** respect `prefers-reduced-motion`: the terminal rows' reveal animation and the cursor blink both have a reduced-motion fallback (rows show instantly, cursor stops blinking) already implemented; any new motion needs the same guard.

### Don't:
- **Don't** add a second serif or a second display face; the whole point is one deliberate contrast moment, not a type system.
- **Don't** introduce `box-shadow` anywhere; this system conveys depth through borders and gradient glow only.
- **Don't** reuse prompt-amber or status-violet outside their current single roles; doing so would blur the "each color has one job" rule that keeps the palette legible.
- **Don't** reintroduce a small-caps, wide-tracked eyebrow kicker above the headline; PRODUCT.md's anti-references flag this pattern as the "AI-landing-page scaffold" the playful/irreverent personality explicitly moved away from.
- **Don't** add fake social proof (star counts, testimonials, "used by" logos) — PRODUCT.md is explicit that there's no proof on hand yet, and the honest "still cooking" framing is the deliberate alternative to faking it.
