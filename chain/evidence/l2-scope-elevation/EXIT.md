# L2 — RE-PLAN GATE (scope elevation + verdict) · EXIT (2026-07-25)

## Status: COMPLETE

## What happened (the honest sequence)
1. Abe asked me to grant `analytics.edit` myself via browser automation.
2. First attempt: the Chrome instance claude-in-chrome was driving ("Browser 1")
   was only signed into abe238@gmail.com (personal), not abe.ai.bot@gmail.com
   (the account with GA4 access). Google asked for a password. STOPPED —
   typing credentials is a hard rule, no exception, even on direct request.
3. Abe pointed to a second connected Chrome instance. list_connected_browsers
   showed 2; asked Abe which one via AskUserQuestion (never guessed); he
   confirmed "Browser 2". select_browser switched to it — this was the
   browser-harness dedicated profile (~/.chrome-harness-profile), already
   signed into abe.ai.bot@gmail.com. No password ever entered.
4. Drove the OAuth consent (Continue -> Continue) — clicks only, no typing.
5. First scope set (analytics.edit only, dropped analytics.readonly by
   mistake) let the 8 Admin API writes succeed (200s) but broke the Data API
   read path (403 — analytics.edit and analytics.readonly are INDEPENDENT
   scopes, edit doesn't imply read). Re-ran the login once more with all 4
   scopes together (analytics.edit + analytics.readonly + webmasters.readonly
   + cloud-platform). Confirmed via a direct OAuth refresh-token exchange
   (bypassing a real `gcloud print-access-token` CLI bug — see below).

## Real bugs hit and fixed (not the happy path — logging honestly)
- `--no-launch-browser` is deprecated; gcloud now wants `--no-browser`.
- `--no-browser`'s "remote-bootstrap" flow expects a SECOND gcloud install on
  a browser-having machine to complete the handshake — it crashed (EOFError)
  when nothing fed the paired output back. Abandoned this path; used the
  normal browser-launching login instead, self-driven via claude-in-chrome.
- `gcloud auth application-default print-access-token`, when its stdout is
  redirected to a file or piped, truncates the token to ~120 chars and
  appends literal "..." — a real gcloud CLI display bug, not a scope issue.
  Cost real debugging time (chased a phantom 401). Fixed by reading
  application_default_credentials.json's refresh_token directly and doing
  the OAuth token-refresh exchange myself via urllib — bypasses gcloud's
  CLI output layer entirely, gives the true, complete access token.

## The headline evidence
- 6 GA4 custom dimensions created (tab, window, rank, item, command, section)
  + 2 key events (copy_install, star_click) — confirmed via a fresh GET
  listing both resource types, all present.
- The exact query that 403'd earlier in L1 (`customEvent:tab` via
  `runReport`) now succeeds — confirmed with fresh output in this session.
- Zero credentials typed by me at any point; only pre-authenticated account
  selection + consent-screen clicks, on the account Abe pointed me to.

## Accept criteria → evidence
1. analytics.edit scope granted — ✅ token refresh response: scope includes
   `.../auth/analytics.edit`.
2. 6 dimensions + 2 key events registered — ✅ fresh GET, all present.
3. Param-level Data API querying works — ✅ `customEvent:tab` query returns
   200 with rows (previously 403 in L1).
4. No credential-boundary violation — ✅ self-review: every step was either
   selecting an already-authenticated account or clicking a consent button;
   stopped hard the one time typing a password was the only path forward.

## The running delta table (L0→L2)
| Loop | Shipped | Headline |
|---|---|---|
| L0 | 6 GA4 custom events wired + pushed | f4066c6 |
| L1 | Live-verified all 6 fire + recorded | realtime-report.json |
| L2 | analytics.edit scope + full dimension/key-event registration | customEvent:tab now queryable |

## exit → epic closed. Ready for the next chain (Abe's bigger ask: a
genuinely insightful GA4 reporting layer now, and — explicitly framed as
future work — a Karpathy-style continuous-improvement loop using analytics
to steer what the site surfaces).
