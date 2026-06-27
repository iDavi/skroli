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
}
```

Enhancers should write their outputs into `meta` rather than inventing new top-level fields, unless the field is universally meaningful.

---

## 5. Runtime Behavior

### 5.1 Poll Cycle

On each cycle (configurable interval, default: 15 minutes):

1. Call every registered ingestor's `fetch()` in parallel.
2. Merge all returned items into one list.
3. Deduplicate by `id` against the local store; discard already-seen items.
4. Discard items older than the configured TTL.
5. Pass surviving items through the enhancer chain sequentially.
6. Persist the final enhanced items.
7. Call the viewer's `render()` with all current items (not just new ones).

### 5.2 Deduplication

Items are deduplicated by `id`. Once an item is stored, it will not be passed to the enhancer pipeline again, even if a future ingestor returns it.

### 5.3 Storage

skroli maintains a local SQLite store of all items. This is an implementation detail of the runtime — ingestors, enhancers, and viewers do not interact with it directly.

---

## 6. Configuration

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
```

---

## 7. Data Storage

- Local SQLite database managed entirely by the skroli runtime.
- Stores all items (post-enhancement) for the duration of their TTL.
- Users can query it directly for advanced use cases, but the schema is considered internal.
- Optional JSON export for backup or portability.

---

## 8. Non-Goals

- skroli ships **no built-in ingestors, enhancers, or viewers**.
- No cloud sync, user accounts, or multi-user support.
- No opinion on how items are ranked, displayed, or filtered — that is the user's domain.

---

## 9. Tech Stack (Recommended)

| Layer     | Choice                             | Rationale                              |
|-----------|------------------------------------|----------------------------------------|
| Runtime   | Python 3.11+                       | Easy to write plugins in; rich stdlib  |
| Scheduler | APScheduler                        | Embedded, no external daemon needed    |
| Storage   | SQLite (via SQLModel)              | Zero-dependency local DB               |
| Config    | TOML                               | Human-readable, widely supported       |

---

## 10. Milestones

| # | Milestone                        | Scope                                                        |
|---|----------------------------------|--------------------------------------------------------------|
| 1 | **Plugin interfaces**            | Define `Ingestor`, `Enhancer`, `Viewer`, `Item` contracts    |
| 2 | **Runtime skeleton**             | Poll loop, dedup, SQLite storage, config loading             |
| 3 | **Plugin loading**               | Dynamically load user modules from config paths              |
| 4 | **CLI**                          | `skroli run`, `skroli status`, `skroli reset`                |
| 5 | **Error isolation**              | Ingestor/enhancer errors don't crash the pipeline            |
| 6 | **Dev experience**               | Hot reload for plugins, verbose logging mode, example plugins |
