# skroli — Roadmap to 0.0.1

The full vision lives in [SPECS.md](./SPECS.md). This roadmap scopes the **first
runnable release (0.0.1)**: the smallest thing that proves skroli's core idea and
nails its look.

---

## Goal of 0.0.1

> Pull items from one source, run them through a minimal pipeline, and show them
> in a viewer that looks like the README.

0.0.1 proves three things:

1. The **addon pipeline** works: ingest → enhance → view.
2. Addons are **pluggable** (loaded from config, configured via a form).
3. The app carries the **skroli visual identity** (olive `#4f4b3b`, serif type,
   stars — see [SPECS §13](./SPECS.md#13-design-language)).

Everything social and remote is **out of scope** for 0.0.1.

---

## UI technology decision

Viewers are HTML/CSS/JS in a sandbox (SPECS §3.3, §3.6), so an embedded web view
is required regardless of host framework. To avoid maintaining two rendering
models — and because the README's serif/olive design is far easier in CSS than in
native widgets — **0.0.1 uses a web-rendered UI in a native window via
`pywebview`**.

- ✅ One rendering model everywhere (chrome and viewers are both web).
- ✅ Exact design fidelity with a bundled web font.
- ✅ Native app window, no Chromium bloat (uses the system webview).
- ✅ Sets up the future iframe-based viewer sandbox for free.

**PyQt** stays a documented alternative (via `QWebEngineView`) if deep OS
integration is needed later, but pure-PyQt-widget rendering is rejected: it would
duplicate the layout engine viewers already need and is harder to style to brand.

---

## In scope for 0.0.1

| Phase | Deliverable | Notes |
|-------|-------------|-------|
| **P0 — Foundations** | Python project scaffold, config loading, logging, the `Item` model. | Config file (format TBD by dev); SPECS §4. |
| **P1 — Pipeline core** | Poll loop with dedup + retention; runs ingestor → enhancer → viewer once per cycle. | SPECS §5. Single-process, local only. |
| **P2 — Addon loading** | Load ingestor/enhancer/viewer addons declared in config; render their **declarative settings form**. | SPECS §3.1–3.5, Tier-1 only. No store, no sandbox. |
| **P3 — Reference addons** | One RSS/Atom **ingestor**, one recency-sort **enhancer**, the built-in **viewer**. | RSS chosen first: no auth, easy to test. |
| **P4 — UI shell + identity** | `pywebview` window rendering the feed in the skroli look (olive, serif, stars). | SPECS §13. This is the built-in default viewer. |
| **P5 — Settings screen** | Edit pipeline settings and each addon's settings via the declarative form. | SPECS §9, Tier-1. |
| **P6 — Run & package** | `skroli run` entrypoint, basic error isolation (a failing addon doesn't crash the cycle), packaging + run docs. | SPECS §5.3. |

---

## Explicitly out of scope for 0.0.1

Deferred to later releases (already specced):

- Federation, accounts, skroli IDs.
- Quotes and saves.
- Peer connections and sharing.
- The addon store (browse / install / publish / sign / review).
- Custom **sandboxed** viewers and custom config UIs (Tier 2). 0.0.1 ships only
  the built-in viewer and declarative forms.
- Themes marketplace (CSS skinning can come once the built-in viewer is stable).
- Cross-server federation.

---

## Definition of done for 0.0.1

- A user can point skroli at an RSS feed in config, run `skroli run`, and see a
  recency-sorted feed in a native window that visibly matches the README design.
- A failing addon is logged and skipped; the app keeps running.
- Adding a second RSS feed works without code changes (proves the addon model).
- No network egress beyond the configured ingestor sources.

---

## After 0.0.1 (direction, not commitment)

Rough order, following the SPECS milestones: themes → custom viewer/config
sandbox → saves → quotes → federation accounts → connections & sharing → addon
store → cross-server.
