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

skroli is **local-first, not local-only**. One built-in capability is federated: users can attach **quotes** to items — short, personal annotations, like a Twitter quote-tweet. Quotes are private by default, but a user can share their peer ID and, by mutual consent, allow others to ingest their quotes into their own feeds. See [§6 Quotes & Peer Sharing](#6-quotes--peer-sharing).

---

## 2. Architecture

```
[ ingestors ]  →→→  [ enhancers ]  →→→  [ viewer ]
  user-defined        user-defined        user-defined
```

Each stage is a defined interface. skroli calls them in order, handles scheduling, deduplication, storage, and inter-stage data passing.

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
  quotes: Quote[]                // annotations on this item (own + ingested from peers)
}
```

Enhancers should write their outputs into `meta` rather than inventing new top-level fields, unless the field is universally meaningful.

The `quotes` array is managed by the runtime, not by enhancers. Enhancers may *read* quotes (e.g. to boost an item's score because a trusted peer quoted it) but should not mutate them.

---

## 5. Runtime Behavior

### 5.1 Poll Cycle

On each cycle (configurable interval, default: 15 minutes):

1. Call every registered ingestor's `fetch()` in parallel.
2. Merge all returned items into one list.
3. Deduplicate by `id` against the local store; discard already-seen items.
4. Discard items older than the configured TTL.
5. Pull new shared quotes from accepted peers and attach them to matching items (see [§6.5](#65-ingesting-peer-quotes)).
6. Pass surviving items through the enhancer chain sequentially.
7. Persist the final enhanced items and their quotes.
8. Call the viewer's `render()` with all current items (not just new ones).

### 5.2 Deduplication

Items are deduplicated by `id`. Once an item is stored, it will not be passed to the enhancer pipeline again, even if a future ingestor returns it.

### 5.3 Storage

skroli maintains a local SQLite store of all items. This is an implementation detail of the runtime — ingestors, enhancers, and viewers do not interact with it directly.

---

## 6. Quotes & Peer Sharing

A **quote** is a short personal annotation a user attaches to an item — a reaction, a note, a counterpoint. This is the one place skroli reaches beyond the local machine: quotes can be selectively shared with consenting peers and ingested into their feeds.

### 6.1 Quote Schema

```ts
interface Quote {
  id: string           // unique quote identifier
  item_id: string      // the Item this quote is attached to
  item_url: string     // canonical link, so the quote is meaningful even if
                       //   the recipient hasn't ingested the original item
  author_id: string    // peer ID of the quote's author
  text: string         // the annotation itself
  created_at: Date
  visibility: "private" | "shared"   // default: "private"
}
```

### 6.2 Peer Identity

- Each skroli instance has a **peer ID**: a stable, self-generated public identifier (e.g. a public-key fingerprint).
- The peer ID is what a user shares to let others request their quotes.
- The corresponding private key signs outgoing quotes so recipients can verify authorship.

### 6.3 Visibility

- Quotes are **private by default**. A private quote never leaves the local machine.
- A user can mark individual quotes (or set a default) as **shared**. Only shared quotes are eligible to be served to peers.

### 6.4 Sharing Handshake

Sharing is mutual and consent-based:

1. **A** shares their peer ID with **B** (out of band — link, QR, message).
2. **B** sends a follow request to **A** using that peer ID.
3. **A** accepts (or rejects) the request. Acceptance is explicit.
4. Once accepted, **B**'s instance may pull **A**'s *shared* quotes.

Either side can revoke at any time; revocation stops future syncs and is the user's to make.

### 6.5 Ingesting Peer Quotes

- Following a peer effectively registers a built-in **quote ingestor** for that peer.
- On each poll cycle, the runtime fetches new shared quotes from accepted peers.
- An incoming quote is verified against the author's peer ID, then attached to the matching local `Item` (by `item_id`/`item_url`). If the user hasn't ingested that item, the runtime may create a stub `Item` from the quote's `item_url` so the quote still surfaces.
- Peer quotes are visible to enhancers and the viewer just like own quotes, but are clearly attributed to their author.

### 6.6 Privacy Guarantees

- No central server. Quote exchange is peer-to-peer between instances that have accepted each other.
- A peer can only ever receive quotes explicitly marked `shared` by an author who has accepted them.
- Quotes are signed; recipients reject unsigned or mis-signed quotes.

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

[quotes]
  default_visibility = "private"   # "private" | "shared"
  # accepted peers whose shared quotes are ingested
  peers = [
    "ed25519:ab12…",
    "ed25519:cd34…",
  ]
```

---

## 8. Data Storage

- Local SQLite database managed entirely by the skroli runtime.
- Stores all items (post-enhancement) and their quotes for the duration of their TTL.
- Quotes — own and ingested — and the peer keyring (own keypair + accepted peers) are persisted locally. Own private quotes never leave this store.
- Users can query it directly for advanced use cases, but the schema is considered internal.
- Optional JSON export for backup or portability.

---

## 9. Non-Goals

- skroli ships **no built-in ingestors, enhancers, or viewers**.
- No cloud sync and no central server. The only network reach is peer-to-peer quote exchange between mutually accepted peers (see [§6](#6-quotes--peer-sharing)).
- No accounts; peer identity is a self-generated keypair, not a hosted login.
- No opinion on how items are ranked, displayed, or filtered — that is the user's domain.

---

## 10. Tech Stack (Recommended)

| Layer     | Choice                             | Rationale                              |
|-----------|------------------------------------|----------------------------------------|
| Runtime   | Python 3.11+                       | Easy to write plugins in; rich stdlib  |
| Scheduler | APScheduler                        | Embedded, no external daemon needed    |
| Storage   | SQLite (via SQLModel)              | Zero-dependency local DB               |
| Identity  | ed25519 keypair (PyNaCl/cryptography) | Sign quotes, derive peer IDs        |
| Config    | TOML                               | Human-readable, widely supported       |

---

## 11. Milestones

| # | Milestone                        | Scope                                                        |
|---|----------------------------------|--------------------------------------------------------------|
| 1 | **Plugin interfaces**            | Define `Ingestor`, `Enhancer`, `Viewer`, `Item`, `Quote` contracts |
| 2 | **Runtime skeleton**             | Poll loop, dedup, SQLite storage, config loading             |
| 3 | **Plugin loading**               | Dynamically load user modules from config paths              |
| 4 | **Quotes (local)**               | Attach private quotes to items; peer keypair generation      |
| 5 | **Peer sharing**                 | Follow request/accept handshake, signed quote sync, revocation |
| 6 | **CLI**                          | `skroli run`, `skroli status`, `skroli peer add/accept/revoke` |
| 7 | **Error isolation**              | Ingestor/enhancer/peer-sync errors don't crash the pipeline  |
| 8 | **Dev experience**               | Hot reload for plugins, verbose logging mode, example plugins |
