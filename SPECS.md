# skroli — Project Specifications

> Your custom local internet algorithm. Simple, as it should be.

---

## 1. Overview

**skroli** is a self-hosted, personal content feed aggregator. It pulls content from multiple internet sources (ingestors), runs it through an AI-powered enhancement pipeline (enhancers), and presents a ranked, enriched, summarized feed to the user (viewer).

The core promise: you own the algorithm. No engagement optimization, no ads, no opaque ranking. Just your sources, your rules, running locally.

---

## 2. Architecture

The system has three layers, as shown in the README diagram:

```
[ ingestors ]  →→→  [ enhancers ]  →→→  [ viewer ]
  Reddit               priority              feed UI
  Twitter/X            enrichment
  NYT / RSS            summarization
  (extensible)
```

---

## 3. Ingestors

Ingestors are adapters that pull raw content from external sources and normalize it into a common `Item` schema.

### 3.1 Built-in Ingestors

| Ingestor    | Source         | Protocol       |
|-------------|----------------|----------------|
| Reddit      | reddit.com     | Reddit API / RSS |
| Twitter/X   | x.com          | Twitter API v2 |
| NYT         | nytimes.com    | RSS / Article API |

### 3.2 Extensibility

Any source that can produce a list of `Item` objects qualifies as an ingestor. Users should be able to add custom ingestors via config (e.g., any RSS/Atom feed URL).

### 3.3 Item Schema

Every ingestor outputs items conforming to this shape:

```ts
interface Item {
  id: string           // unique, stable identifier
  source: string       // e.g. "reddit", "twitter", "nyt"
  url: string          // canonical link to the content
  title: string
  body?: string        // full text or excerpt if available
  author?: string
  published_at: Date
  raw: unknown         // original source payload, for debugging
}
```

### 3.4 Behavior

- Ingestors run on a configurable polling interval (default: 15 minutes).
- Deduplication is handled by `id` before items enter the enhancer pipeline.
- Items older than a configurable TTL (default: 48 hours) are discarded before enhancement.

---

## 4. Enhancers

Enhancers process a batch of new `Item` objects and produce enriched `EnhancedItem` objects. They answer three questions per item (or per batch):

1. **What is more important?** — prioritization / ranking
2. **What can we add?** — enrichment (related links, context, metadata)
3. **How can we summarize?** — condensed, readable summary

### 4.1 Enhancer Pipeline

Enhancers run sequentially in a defined pipeline. Each enhancer receives the output of the previous one.

```
items[]  →  [Ranker]  →  [Enricher]  →  [Summarizer]  →  enhanced_items[]
```

### 4.2 Ranker

- Assigns a numeric `score` (0–1) to each item.
- Default signal: recency × source weight × engagement (upvotes, retweets, etc.).
- User-defined source weights configurable in `skroli.config` (e.g., NYT weight: 0.8, Twitter weight: 0.5).
- Items below a configurable score threshold are dropped.

### 4.3 Enricher

- Optionally fetches the full article body if `body` is absent (via readability extraction).
- Adds `tags` derived from content (keyword extraction).
- Optionally links related items from the same session batch.

### 4.4 Summarizer

- Produces a short `summary` (2–4 sentences) for each item.
- Runs via a local LLM (e.g., Ollama + llama3) or a configured API (e.g., Claude).
- Summary is stored alongside the item; original `body` is preserved.
- Summarization is skipped if `body` is too short (< 200 chars).

### 4.5 EnhancedItem Schema

```ts
interface EnhancedItem extends Item {
  score: number          // 0–1 ranking score
  summary?: string       // AI-generated summary
  tags: string[]         // extracted topics/keywords
  related?: string[]     // IDs of related items in same batch
}
```

---

## 5. Viewer

The viewer is the user-facing interface that renders the enhanced feed.

### 5.1 Display

- Items displayed in descending score order.
- Each card shows: title, source badge, published time (relative), summary, tags, and a link to the original.
- Full body readable inline (collapsed by default).

### 5.2 Interactions

- **Star** an item to save it permanently (items otherwise expire by TTL).
- **Dismiss** an item to hide it and down-weight similar content in future runs.
- **Filter** by source, tag, or date range.
- **Search** across current items (local full-text).

### 5.3 Interface Type

The viewer should be a **local web UI** (served on `localhost`) for broad accessibility. A terminal UI (TUI) is a secondary option for power users.

---

## 6. Configuration

All user configuration lives in a single file: `skroli.config.toml` (or `.json`).

```toml
[ingestors]
  [[ingestors.feeds]]
    type = "rss"
    url = "https://example.com/feed.xml"
    weight = 0.7

  [[ingestors.reddit]]
    subreddits = ["programming", "science"]
    weight = 0.6

  [[ingestors.twitter]]
    lists = ["my-list-id"]
    weight = 0.5

[enhancers]
  score_threshold = 0.3
  ttl_hours = 48
  summarizer = "ollama"          # "ollama" | "claude" | "openai" | "none"
  summarizer_model = "llama3"

[viewer]
  port = 4242
  theme = "dark"
  items_per_page = 30
```

---

## 7. Data Storage

- Local SQLite database for items, enhanced metadata, starred items, and dismissals.
- No cloud sync by default; data stays on the user's machine.
- Optional export to JSON for backup or portability.

---

## 8. Tech Stack (Recommended)

| Layer        | Choice                              | Rationale                                  |
|--------------|-------------------------------------|--------------------------------------------|
| Runtime      | Python 3.11+                        | Rich ecosystem for scraping, NLP, LLMs     |
| Scheduler    | APScheduler or cron                 | Simple polling loop                        |
| Storage      | SQLite (via SQLModel / SQLAlchemy)  | Zero-dependency local DB                  |
| Web UI       | FastAPI + HTMX or a minimal React   | Simple, fast, avoids heavy SPA boilerplate |
| LLM          | Ollama (local) or Claude API        | User's choice; local-first                 |
| Config       | TOML                                | Human-readable, no surprises               |

---

## 9. Non-Goals

- No user accounts or multi-user support (single local user).
- No mobile app (responsive web UI covers mobile browsers).
- No social features (sharing, following, comments).
- No cloud hosting or SaaS offering.

---

## 10. Milestones

| # | Milestone                          | Scope                                              |
|---|------------------------------------|----------------------------------------------------|
| 1 | **Core pipeline (no UI)**          | Reddit ingestor + ranker + SQLite storage          |
| 2 | **Basic viewer**                   | Local web UI serving ranked feed                   |
| 3 | **More ingestors**                 | Twitter, NYT, generic RSS                          |
| 4 | **Summarizer**                     | Ollama integration, summary cards in UI            |
| 5 | **User interactions**              | Star, dismiss, filter, search                      |
| 6 | **Config-driven weights**          | Full `skroli.config.toml` support                  |
| 7 | **Polish**                         | TUI option, export, theme, onboarding              |
