# skroli — Project Specifications

> Your custom local internet algorithm. Simple, as it should be.

---

## 1. Overview

**skroli** is a self-hosted pipeline framework for building a personal content feed. It provides a structured runtime that orchestrates three stages — ingest, enhance, view — but supplies **no implementations** of those stages itself.

The user writes (or installs) their own:
- **ingestors** — fetch content from wherever they want
- **enhancers** — process, rank, enrich, or filter that content
- **viewer** — display the final feed however they like

skroli's job is to wire them together, run them on schedule, and pass data between them reliably.

skroli is **local-first, but not local-only**. The pipeline (ingest → enhance → view) runs locally, but two pieces of user-generated data live on a shared server — the **skroli federation**:

- **quotes** — short personal annotations on items, like a Twitter quote-tweet.
- **saves** — items the user has saved for keeping.

Storing these in the federation is what makes sharing possible: quotes and saves are private by default, but a user can share their ID and, by mutual consent, let others pull their shared quotes/saves into their own feeds. See [§6 Quotes, Saves & the Federation](#6-quotes-saves--the-federation).

---

## 2. Architecture

```
                    ┌─────────────────────────────┐
   local instance   │   [ingestors] → [enhancers] → [viewer]   │
                    │              │                            │
                    └──────────────┼────────────────────────────┘
                                   │  quotes & saves
                                   ▼
                       ╔══════════════════════╗
                       ║   skroli federation  ║   ← shared server
                       ║  (quotes + saves)    ║
                       ╚══════════════════════╝
```

- The **local instance** owns the pipeline: user-defined ingestors, enhancers, and viewer. skroli calls them in order, handles scheduling, deduplication, local item storage, and inter-stage data passing.
- The **skroli federation** is a server that stores users' quotes and saves and serves them — to their owner always, and to consenting peers on request.

---

## 3. Plugin Interfaces

### 3.1 Ingestor

An ingestor is any module that implements:

```ts
interface Ingestor {
  name: string
  fetch(): Promise<Item[]>
}
```

It is called by the skroli runtime on each poll cycle and must return a list of `Item` objects.

### 3.2 Enhancer

An enhancer is any module that implements:

```ts
interface Enhancer {
  name: string
  enhance(items: Item[]): Promise<Item[]>
}
```

Enhancers run in sequence. Each receives the full item list (as modified by all previous enhancers) and returns a new list. An enhancer may add fields, drop items, reorder, or mutate in any way.

### 3.3 Viewer

A viewer is any module that implements:

```ts
interface Viewer {
  name: string
  render(items: Item[]): void | Promise<void>
}
```

It is called once after the enhancer pipeline completes, receiving the final item list. What it does with them — serve a web UI, write to a file, send a notification — is entirely up to the user.

---

## 4. Item Schema

The `Item` is the common data contract passed between all stages. It has a required core and an open `meta` bag for user-defined fields.

```ts
interface Item {
  id: string           // unique, stable identifier (user-assigned)
  source: string       // ingestor name that produced this item
  url: string          // canonical link
  title: string
  body?: string        // content text, if available
  author?: string
  published_at: Date
  meta: Record<string, unknown>  // arbitrary fields added by enhancers
  quotes: Quote[]                // annotations on this item (own + peers')
  saved: boolean                 // whether the user has saved this item
}
```

Enhancers should write their outputs into `meta` rather than inventing new top-level fields, unless the field is universally meaningful.

The `quotes` array and `saved` flag are managed by the runtime (backed by the federation), not by enhancers. Enhancers may *read* them (e.g. boost an item's score because a trusted peer quoted it) but should not mutate them.

---

## 5. Runtime Behavior

### 5.1 Poll Cycle

On each cycle (configurable interval, default: 15 minutes):

1. Call every registered ingestor's `fetch()` in parallel.
2. Merge all returned items into one list.
3. Deduplicate by `id` against the local store; discard already-seen items.
4. Discard items older than the configured TTL.
5. Sync with the federation: pull the user's own quotes/saves and any shared quotes/saves from accepted peers, then attach them to matching items (see [§6.5](#65-syncing-quotes--saves)).
6. Pass surviving items through the enhancer chain sequentially.
7. Persist the final enhanced items locally.
8. Call the viewer's `render()` with all current items (not just new ones).

### 5.2 Deduplication

Items are deduplicated by `id`. Once an item is stored, it will not be passed to the enhancer pipeline again, even if a future ingestor returns it.

### 5.3 Storage

skroli maintains a local SQLite store of all items. This is an implementation detail of the runtime — ingestors, enhancers, and viewers do not interact with it directly. Quotes and saves are **not** stored here; they live in the federation (see [§6](#6-quotes-saves--the-federation)) and are synced into items at runtime.

---

## 6. Quotes, Saves & the Federation

While the pipeline runs locally, two kinds of user-generated data are stored on the **skroli federation** — a shared server:

- A **quote** is a short personal annotation on an item — a reaction, a note, a counterpoint (like a Twitter quote-tweet).
- A **save** is an item the user has marked to keep.

Putting these in the federation gives them a durable home independent of any single item's TTL, lets the user see them across devices, and — crucially — makes consent-based sharing possible.

### 6.1 Schemas

```ts
interface Quote {
  id: string           // unique quote identifier
  item_id: string      // the Item this quote is attached to
  item_url: string     // canonical link, so the quote is meaningful even if
                       //   a recipient hasn't ingested the original item
  author_id: string    // skroli ID of the quote's author
  text: string         // the annotation itself
  created_at: Date
  visibility: "private" | "shared"   // default: "private"
}

interface Save {
  id: string
  item_id: string
  item_url: string
  item_title: string   // snapshot, so a save is readable on its own
  author_id: string    // skroli ID of the user who saved it
  created_at: Date
  visibility: "private" | "shared"   // default: "private"
}
```

### 6.2 Identity

- Each user has a **skroli ID**: a stable account on the federation, plus a keypair held by their local instance.
- The skroli ID is what a user shares to let others request their quotes/saves.
- The local instance signs writes to the federation so authorship can be verified and quotes/saves can't be forged.

### 6.3 Visibility

- Quotes and saves are **private by default**. Private records are stored on the federation but served only to their owner.
- A user can mark individual records (or set a default) as **shared**. Only shared records are eligible to be served to accepted peers.

### 6.4 Sharing Handshake

Sharing is mutual and consent-based, mediated by the federation:

1. **A** shares their skroli ID with **B** (out of band — link, QR, message).
2. **B** sends a follow request to **A** through the federation.
3. **A** accepts (or rejects) the request. Acceptance is explicit.
4. Once accepted, the federation serves **A**'s *shared* quotes and saves to **B** on sync.

Either side can revoke at any time; revocation stops future sharing and is the user's to make.

### 6.5 Syncing Quotes & Saves

On each poll cycle the local runtime syncs with the federation:

- Pulls the user's **own** quotes and saves and applies them to matching items (sets `saved`, fills `quotes[]`).
- Pulls **shared** quotes and saves from accepted peers and attaches them to matching items by `item_id`/`item_url`. If the user hasn't ingested an item, the runtime may create a stub `Item` from the stored `item_url`/`item_title` so the record still surfaces.
- Pushes the user's newly created quotes/saves up to the federation.
- Peer records are shown to enhancers and the viewer just like the user's own, but are clearly attributed to their author.

### 6.6 Privacy & Trust

- A peer can only ever receive records explicitly marked `shared` by an author who has accepted them.
- The federation enforces visibility and follow relationships server-side; clients also verify signatures and reject forged or mis-signed records.
- Private quotes and saves are never served to anyone but their owner.

---

## 7. Configuration

All wiring lives in `skroli.config.toml`.

```toml
[runtime]
poll_interval_minutes = 15
ttl_hours = 48

[ingestors]
  # paths or module references to user-defined ingestors
  modules = [
    "./my_ingestors/reddit.py",
    "./my_ingestors/rss.py",
  ]

[enhancers]
  # run in order
  modules = [
    "./my_enhancers/ranker.py",
    "./my_enhancers/summarizer.py",
  ]

[viewer]
  module = "./my_viewer/web.py"

[federation]
  server = "https://federation.skroli.net"   # or a self-hosted instance
  id = "@me"                                  # this user's skroli ID
  default_visibility = "private"              # "private" | "shared"
  # accepted peers whose shared quotes/saves are synced into the feed
  peers = [
    "@alice",
    "@bob",
  ]
```

---

## 8. Data Storage

Storage is split across two tiers:

**Local (per instance):**
- SQLite database managed entirely by the skroli runtime.
- Stores all items (post-enhancement) for the duration of their TTL, plus the user's keypair and a cache of synced quotes/saves.
- Users can query it directly for advanced use cases, but the schema is considered internal.
- Optional JSON export for backup or portability.

**Federation (shared server):**
- Stores all quotes and saves, the user account/skroli ID, follow relationships, and visibility flags.
- Enforces visibility and follow rules server-side; serves records only to their owner or to accepted peers.
- Can be the public skroli federation or a self-hosted instance pointed at via config.

---

## 9. Non-Goals

- skroli ships **no built-in ingestors, enhancers, or viewers**.
- The pipeline and item storage stay local; only quotes and saves leave the machine, to the federation (see [§6](#6-quotes-saves--the-federation)).
- No opinion on how items are ranked, displayed, or filtered — that is the user's domain.
- The federation stores quotes and saves only — never the user's raw feed, ingestor credentials, or pipeline data.

---

## 10. Tech Stack (Recommended)

| Layer            | Choice                             | Rationale                              |
|------------------|------------------------------------|----------------------------------------|
| Local runtime    | Python 3.11+                       | Easy to write plugins in; rich stdlib  |
| Scheduler        | APScheduler                        | Embedded, no external daemon needed    |
| Local storage    | SQLite (via SQLModel)              | Zero-dependency local DB               |
| Identity         | ed25519 keypair (PyNaCl/cryptography) | Sign quotes/saves, prove authorship |
| Config           | TOML                               | Human-readable, widely supported       |
| Federation server| FastAPI + Postgres                 | Stores quotes/saves, follows, visibility; REST sync API |

---

## 11. Milestones

| # | Milestone                        | Scope                                                        |
|---|----------------------------------|--------------------------------------------------------------|
| 1 | **Plugin interfaces**            | Define `Ingestor`, `Enhancer`, `Viewer`, `Item`, `Quote`, `Save` contracts |
| 2 | **Runtime skeleton**             | Poll loop, dedup, SQLite storage, config loading             |
| 3 | **Plugin loading**               | Dynamically load user modules from config paths              |
| 4 | **Federation server (MVP)**      | Accounts/IDs, store private quotes & saves, signed REST sync API |
| 5 | **Quotes & saves (local)**       | Create quotes and save items; sync own records with federation |
| 6 | **Sharing**                      | Follow request/accept handshake, shared-record sync, revocation |
| 7 | **CLI**                          | `skroli run`, `skroli status`, `skroli peer add/accept/revoke` |
| 8 | **Error isolation**             | Ingestor/enhancer/sync errors don't crash the pipeline       |
| 9 | **Dev experience**               | Hot reload for plugins, verbose logging mode, example plugins, self-host docs |
