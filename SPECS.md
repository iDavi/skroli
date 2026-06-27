# skroli — Project Specifications

> Your custom local internet algorithm. Simple, as it should be.

This document describes **what skroli does** — its features, behavior, and data
model. It deliberately avoids prescribing tech stack, frameworks, transport,
storage engines, or other architecture decisions; those are made during
development.

---

## 1. Overview

**skroli** is a personal content feed you control. Instead of an opaque
algorithm deciding what you see, you assemble your own from small parts:

- **ingestors** pull content from sources you choose,
- **enhancers** rank, enrich, and filter it,
- a **viewer** shows you the result.

These parts are **addons** — installable from the **skroli addon store**, or
written by the user. skroli's job is to run them in order, on a schedule, and
keep the data flowing between them.

On top of the local feed, skroli adds a light social layer: you can **quote**
and **save** items. These are stored in the **skroli federation** so they
persist, follow you across devices, and — with consent — can be shared with
other people, whose quotes and saves can then flow into your feed.

---

## 2. Core Concepts

| Concept        | What it is                                                        |
|----------------|------------------------------------------------------------------|
| **Item**       | A single piece of content in the feed (a post, article, tweet…). |
| **Ingestor**   | An addon that fetches items from a source.                       |
| **Enhancer**   | An addon that processes items (rank, enrich, summarize, filter). |
| **Viewer**     | An addon that displays the final feed.                           |
| **Addon**      | Any installable ingestor, enhancer, or viewer.                   |
| **Addon store**| Where addons are published, discovered, and installed.           |
| **Quote**      | A short personal annotation attached to an item.                 |
| **Save**       | An item the user has kept.                                       |
| **Federation** | The shared service that stores quotes, saves, and social links.  |
| **Peer**       | Another skroli user you've connected with.                       |

The feed pipeline runs locally. Quotes, saves, and social connections live in
the federation.

```
        sources                addons run locally               you
   ┌──────────────┐      ┌────────────────────────────┐
   │ reddit, x,    │ ──▶  │ ingestors → enhancers →     │ ──▶  viewer
   │ rss, …        │      │            ↑    feed         │
   └──────────────┘      └────────────┼───────────────┘
                                       │ quotes & saves
                                       ▼
                              ┌──────────────────┐
                              │  skroli federation │  ◀──▶ peers
                              └──────────────────┘
```

---

## 3. Addons

An addon is a unit of functionality the user installs into their skroli. There
are three kinds.

### 3.1 Ingestors

- Fetch content from a source and produce `Item`s.
- Run on every poll cycle.
- May require user-supplied settings (e.g. a subreddit list, an account handle,
  a feed URL, an API key).
- Examples: Reddit, Twitter/X, an RSS/Atom feed, a newsletter, a website.

### 3.2 Enhancers

- Receive the current batch of items and return a modified batch.
- Run **in a user-defined order**, each seeing the previous one's output.
- Can do anything: score/rank, deduplicate, summarize, tag, translate, filter
  out unwanted items, group related items, etc.
- May read an item's quotes and saves to inform their work (e.g. rank an item
  higher because a trusted peer quoted it) but must not modify them.

### 3.3 Viewers

The viewer is the **layout and design** of the feed, and it is meant to be
*extremely* customizable — a user should be able to make their feed look and
behave exactly like Twitter, Reddit, a magazine, a terminal, an email digest, or
anything else. To allow that without giving custom code free rein, viewers come
in two tiers:

**Tier 1 — Themes (safe by default).**
- A theme is **CSS-only** styling layered on a built-in viewer.
- No custom code runs; themes are safe to install and enable without warnings.
- Covers most "make it look like X" needs (colors, spacing, typography, card
  layout).

**Tier 2 — Full viewers (custom, sandboxed).**
- A full viewer ships its own HTML/CSS/JS and controls everything: layout,
  interactions (infinite scroll, hover cards, threaded comments), the lot.
- Because this is custom code, it runs **isolated** (see [§3.6](#36-custom-ui-the-sandbox--bridge)).
- Installing a full viewer requires an explicit permission prompt that makes
  clear it runs third-party code.

A viewer receives the final, enhanced feed once per cycle and presents it. It can
also drive user actions — save, quote, open a link, load more — but only through
the host bridge described in §3.6.

### 3.4 Addon Configuration Screens

Every addon has a **config screen** where the user supplies its settings. Like
viewers, config screens are customizable, with the same two tiers:

**Tier 1 — Declarative form (safe by default).**
- The addon declares a **settings schema** (fields, types, labels, defaults,
  validation, required/optional, secret/not).
- skroli renders a standard form from it. No custom code runs.
- Handles the common case: API keys, toggles, lists (subreddits, feed URLs),
  dropdowns, numbers.

**Tier 2 — Custom config UI (sandboxed).**
- For richer needs — a live preview, "test connection", an OAuth login flow,
  picking from a list fetched live from the source — an addon may ship a custom
  config screen.
- It runs in the same sandbox as full viewers (§3.6) and reads/writes its
  settings only through the bridge.

skroli surfaces required settings at install time and refuses to run an addon
that is missing required settings. Secret settings (keys, tokens) are stored
locally and never sent to the federation or the store.

### 3.5 Addon Capabilities

Every addon declares:

- a **type** (ingestor / enhancer / viewer),
- a **name** and **version**,
- the **settings** it accepts (the settings schema, with types, defaults, and
  whether each is required or secret),
- whether it ships a **custom UI** (full viewer and/or custom config screen),
- the **permissions** it needs — e.g. source network access (ingestors),
  federation access, filesystem access, and UI capabilities like
  `remote-images` or `open-external-links`.

skroli enforces declared permissions at runtime; an addon cannot exceed them.

### 3.6 Custom UI: the Sandbox & Bridge

Both full viewers (§3.3) and custom config screens (§3.4) run custom code. skroli
runs that code **isolated**, and lets it interact with the user's data and the
app **only** through a defined bridge. These are hard requirements:

- **Isolation.** Custom UI runs in a sandbox (e.g. a sandboxed, cross-origin
  frame) where it cannot access the host application, the user's secrets,
  federation credentials, the filesystem, or other addons' data.
- **No ambient network.** Network egress is **denied by default**, so custom UI
  cannot exfiltrate the feed, quotes, or saves. Loading remote images is the
  only network capability, and only when the `remote-images` permission is
  granted.
- **Data in, only via the bridge.** Viewers receive the feed; config screens
  receive their current settings. They get nothing else.
- **Actions out, only via the bridge, always mediated.** Custom UI can request
  actions — save/unsave, create a quote, open an external link, load more items,
  read/write its own settings, run a host-mediated flow like OAuth or "test
  connection" — and the host validates and performs each one against the addon's
  permissions. The UI never performs privileged actions itself.
- **Anti-spoofing.** skroli draws its own chrome around custom UI (a persistent
  "third-party: «addon name»" badge) so a malicious viewer can't convincingly
  impersonate skroli or a login screen.

This is a deliberate, bounded security tradeoff: addons get near-total visual and
interactive freedom, while isolation + a mediated bridge keep them away from
anything sensitive.

---

## 4. The Item

The item is the common data passed between every stage.

| Field          | Description                                              |
|----------------|----------------------------------------------------------|
| `id`           | Stable unique identifier (used for deduplication).       |
| `source`       | Which ingestor produced it.                              |
| `url`          | Canonical link to the original content.                  |
| `title`        | Headline / title.                                        |
| `body`         | Full text or excerpt, if available.                      |
| `author`       | Original author, if known.                               |
| `published_at` | When the content was originally published.               |
| `meta`         | Open key/value bag for fields added by enhancers.        |
| `quotes`       | Quotes attached to this item (the user's and peers').    |
| `saved`        | Whether the user has saved this item.                    |

Enhancers add their own data to `meta`. The `quotes` and `saved` fields are
populated by skroli from the federation and are read-only to addons.

---

## 5. The Feed Pipeline

### 5.1 Poll Cycle

skroli refreshes the feed on a configurable interval. Each cycle:

1. Runs every installed ingestor to fetch fresh items.
2. Merges results into one list.
3. Drops items already seen (by `id`) and items older than the configured
   retention window.
4. Syncs quotes and saves from the federation and attaches them to matching
   items (own records always; peers' shared records where connected).
5. Runs the enhancer chain in order.
6. Stores the resulting feed.
7. Hands the final feed to the viewer.

### 5.2 Deduplication & Retention

- An item is processed once; if an ingestor returns it again, it's ignored.
- Items older than the retention window are removed from the feed. Saving an item
  keeps it regardless of retention.

### 5.3 Resilience

- A failing ingestor, enhancer, or viewer must not crash the cycle. skroli logs
  the failure, skips that addon for the cycle, and continues with the rest.

---

## 6. Quotes & Saves

### 6.1 Quotes

- A quote is a short note the user attaches to an item — a reaction, comment, or
  counterpoint (like a quote-tweet).
- A user can quote any item in their feed.
- Quotes are **private by default** and can be marked **shared**.
- A quote stores enough about its item (link, title) to remain meaningful even to
  someone who hasn't ingested that item.

### 6.2 Saves

- Saving keeps an item permanently, independent of the retention window.
- Saves are **private by default** and can be marked **shared**.
- The user can browse, search, and unsave their saved items.

### 6.3 Where They Live

- Quotes and saves are stored in the federation, not just locally, so they
  persist and are available across the user's devices.
- The local feed reflects them: saved items show as saved, quoted items show
  their quotes.

---

## 7. Sharing & the Federation

### 7.1 Identity

- Each user has a **skroli ID** — their account/handle on the federation.
- The ID is what a user shares so others can connect with them.

### 7.2 Connecting with Peers

Connections are mutual and consent-based:

1. A user shares their skroli ID.
2. Another user sends a connection (follow) request.
3. The recipient explicitly **accepts or rejects** it.
4. Once accepted, the requester can receive the other user's **shared** quotes
   and saves.

Either side can disconnect at any time, which stops further sharing.

### 7.3 Sharing Into the Feed

- When connected, a peer's shared quotes and saves are synced into the user's
  feed each cycle and attached to the relevant items.
- If the user hasn't ingested an item a peer quoted/saved, skroli still surfaces
  the record using the stored link and title.
- Peer contributions are always clearly **attributed** to their author.

### 7.4 Visibility Rules

- **Private** records are visible only to their owner.
- **Shared** records are visible only to accepted, connected peers.
- A user can set a default visibility and override it per record.
- Changing a record to private, or disconnecting, stops it from being served.

### 7.5 Federation Scope (future)

The federation is intended to be **multi-server**: a user's account lives on one
server, and connections may span servers (e.g. a user on one server connecting
to a user on another). Cross-server connection and sharing follow the same
consent rules. The exact protocol is an implementation decision; the
**functional requirement** is that connecting and sharing work across servers
exactly as they do within one.

---

## 8. The Addon Store

The addon store is where addons are published, discovered, and installed. It is
what makes skroli extensible without users writing code.

### 8.1 For Users (Consumers)

- **Browse & search** addons by type (ingestor / enhancer / viewer), keyword,
  category, and popularity.
- **Addon detail page**: description, screenshots, author, version history,
  required settings, requested permissions, and ratings/reviews.
- **Install / update / remove** addons.
- **Manage settings** for each installed addon, including secrets (API keys),
  which are stored locally and never sent to the federation or the store.
- **Review permissions** before install; skroli enforces what an addon is
  allowed to do.
- **Rate & review** addons.

### 8.2 For Developers (Publishers)

- **Publish** an addon with a manifest declaring type, name, version, settings
  schema, permissions, and metadata.
- **Version** addons; users get update notifications.
- **Update or unpublish** their addons.
- Addons are **identified and signed** so users can trust that an update comes
  from the original author.

### 8.3 Trust & Safety

- Each addon declares the **permissions** it needs; skroli enforces them at
  runtime.
- Addons are sandboxed from each other's settings and secrets.
- The store can flag, rate, and (if needed) remove malicious addons.
- An addon never gains access to another addon's data, the user's secrets, or the
  federation unless it explicitly requests and is granted that permission.

---

## 9. Settings

The user configures their skroli through settings covering:

- **Pipeline**: poll interval, retention window, enhancer order.
- **Installed addons**: which are enabled, and each addon's own settings.
- **Federation**: the user's server and skroli ID, default visibility, and the
  list of connected peers.

Settings are persisted and editable. Secrets (API keys, tokens) are stored
locally and treated as sensitive.

---

## 10. Data Model

Logical entities skroli manages. Field lists are the essentials, not exhaustive.

### Local

- **Item** — `id`, `source`, `url`, `title`, `body`, `author`, `published_at`,
  `meta`, `saved`, plus references to its quotes. Lives for the retention window
  (or forever, if saved).
- **InstalledAddon** — `id`, `type`, `name`, `version`, `enabled`, `order`
  (for enhancers), `settings`, `permissions`, `has_custom_ui`.
- **Theme** — `id`, `name`, `target_viewer`, `css`, `enabled`. A CSS-only skin
  layered on a built-in viewer.
- **Secret** — addon settings marked sensitive; stored locally only.
- **UserKey / credentials** — the local identity used to authenticate to the
  federation.

### Federation

- **Account** — `skroli_id`, profile, the server it belongs to.
- **Quote** — `id`, `item_url`, `item_title`, `author_id`, `text`,
  `created_at`, `visibility`.
- **Save** — `id`, `item_url`, `item_title`, `author_id`, `created_at`,
  `visibility`.
- **Connection** — directed link between two accounts with a state
  (`requested` / `accepted` / `rejected` / `revoked`).

### Store

- **Addon** — `id`, `type`, `name`, `description`, `author`, `category`,
  `permissions`, `settings_schema`, `has_custom_ui`.
- **AddonVersion** — `addon_id`, `version`, `manifest`, `assets` (CSS/JS bundle
  for themes and custom UI), `published_at`, `signature`.
- **Review** — `addon_id`, `author_id`, `rating`, `text`, `created_at`.

---

## 11. Non-Goals

- skroli does not ship its own ranking or display opinion — that's the user's,
  expressed through the addons they choose.
- The federation stores only social data (quotes, saves, connections, accounts)
  — never the user's raw feed, ingestor credentials, or pipeline internals.
- Secrets and API keys never leave the user's machine.

---

## 12. Milestones

| #  | Milestone                | Delivers                                                        |
|----|--------------------------|----------------------------------------------------------------|
| 1  | **Pipeline core**        | Ingest → enhance → view loop with the `Item` model.            |
| 2  | **Addon model**          | Install, enable, order, and configure addons via declarative settings forms. |
| 3  | **First addons**         | A reference ingestor, enhancer, and viewer to prove the model. |
| 3b | **Themes**               | CSS-only skins on built-in viewers (safe, no code).            |
| 3c | **Custom UI sandbox**    | Isolated full viewers & custom config screens with the host bridge. |

---

## 13. Design Language

The app's own chrome (everything outside a custom viewer) must match the look of
the README artwork: calm, minimal, editorial.

### 13.1 Palette (sampled from the README artwork)

| Token        | Hex       | Use                                      |
|--------------|-----------|------------------------------------------|
| `olive`      | `#4f4b3b` | Primary background.                       |
| `parchment`  | `#ffffff` | Wordmark, primary text on olive.         |
| `stone`      | `#959389` | Stars, muted text, dividers, icons.      |
| `stone-dim`  | `#8c8a7f` | Secondary muted accents.                  |

(Exact values are taken from the source PNGs; treat them as the canonical
tokens.)

### 13.2 Typography

- The typeface is **Libertinus Math** (the wordmark and headings), giving the
  editorial, classical-serif feel of the README.
- Bundle the font with the app so rendering is consistent offline. Provide a
  graceful fallback stack (`"Libertinus Math","Libertinus Serif",Georgia,serif`)
  for environments where it isn't installed.
- Body/UI text may use the same family or a quiet companion; keep it editorial,
  not chrome-heavy.

### 13.3 Motifs

- The **star** is the recurring motif (it appears as bullets, source markers,
  and the rating row in the artwork). Reuse it as skroli's iconography.
- Generous spacing, flat surfaces, no heavy borders or shadows — let the olive
  field and serif type carry the identity.

### 13.4 Scope

This design language governs skroli's **built-in viewer, settings, store, and
window chrome**. Custom viewers (§3.3) are free to look like anything; only the
host chrome around them must stay on-brand (including the "third-party viewer"
badge from §3.6).
| 4  | **Saves**                | Save/unsave items; saved items persist past retention.         |
| 5  | **Quotes**               | Create and view quotes on items.                               |
| 6  | **Federation accounts**  | skroli IDs; quotes & saves stored and synced per user.         |
| 7  | **Connections & sharing**| Connect with peers; shared quotes/saves flow into the feed.    |
| 8  | **Addon store**          | Browse, install, update; publish, version, sign addons.        |
| 9  | **Trust & permissions**  | Permission enforcement, sandboxing, reviews/ratings.           |
| 10 | **Cross-server**         | Connections and sharing that span federation servers.          |
