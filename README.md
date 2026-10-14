Heirloom
A multi-agent oral-history interviewer. It remembers everything across sessions, never asks the
same question twice, notices contradictions, and probes gaps in a life story. Under the hood it is
a context-engineering system: summary memory, vector memory, and hybrid retrieval feed a
token-budgeted Context Assembler.

> **Status:** Phases 1–6 complete (backend, agents, API, frontend). Phase 7 (full README with architecture
> diagram, per-turn memory flow, backend switching guide, sample output) is next.

## Quick start

```bash
make up          # dynamodb-local + qdrant + backend + frontend; tables are created on boot
make seed        # narrator "frank": 30 seed memories + the 124-message interview replayed through the API
open http://localhost:5173
make demo        # all technique demos (real OpenAI if OPENAI_API_KEY is set in .env)
make test-local  # backend tests on the host, no Docker needed (moto + fakes)
make demo-local  # every demo fully offline: moto, embedded Qdrant, deterministic fake LLM/embeddings
```

Frontend development with hot reload: `make frontend-dev` (Vite on :5173, proxies `/api` to :8080).

## Frontend

React + TypeScript + Vite + Tailwind v4 + TanStack Query v5 (`frontend/`).

| Page | What it shows |
|---|---|
| Interview | Streaming chat (SSE) plus a side panel showing exactly what went into the next prompt: a budget bar across the 7 context slots, every included item, and contradictions to clarify |
| Summary tree | Collapsible chunk → section → session → life-archive tree; select a node for its summary, message range, compression and children |
| Memory explorer | Hybrid search with type/date/event-year filters and weight sliders; stacked score bars; rows animate on re-rank with ↑/↓ movement |
| Life timeline | Every dated memory plotted by year; years with no stories are hatched, with suggested questions from the Gap Finder |
| Chapters | Draft a chapter by period or theme; citation numbers open the source memory |

TanStack Query: central `queryKeys` factory (`src/api/queryKeys.ts`), typed client (`src/api/client.ts`),
optimistic user message on send, targeted invalidation after each turn (messages, session, summary tree,
context preview, memories, contradictions, gaps, agent runs), a second invalidation ~2.5s later because the
background agents finish after the SSE stream closes, `placeholderData: keepPreviousData` for search, and
Devtools in development. Screenshots: `docs/screenshots/` (captured in a sandbox without web fonts, so
they show fallback typefaces; Literata and Public Sans load normally).

## DynamoDB design (single table)

**Why one table.** Every access pattern is either a "get by id" or a "range within a parent"
(messages in a session, nodes at a level, children of a node, memories in a time range).
That maps cleanly onto `pk`/`sk` plus three GSIs. A session's messages, nodes, and agent runs
live in one item collection, so a session view is cheap. Per-session write volume is small
(one interview), so the shared partition is not a hot-key risk.

Table `heirloom`: `pk`/`sk`, plus `GSI1`, `GSI2`, `GSI3` (all `ALL` projection, on-demand billing).

| Entity | pk | sk | GSI keys |
|---|---|---|---|
| User | `USER#<uid>` | `PROFILE` | |
| Session | `SESSION#<sid>` | `META` | GSI1 `USER#<uid>#SESSIONS` / `<created_at>` |
| Message | `SESSION#<sid>` | `MSG#<seq:08d>` | |
| Summary node | `SESSION#<sid>` | `NODE#L<level>#<first_seq:08d>#<nid>` | GSI1 `NODE#<nid>` / `NODE` · GSI2 `CHILDREN#<parent>` / `<first_seq>#<nid>` |
| Memory | `MEMORY#<mid>` | `MEMORY` | GSI1 `USER#<uid>#MEMORIES` / `<created_at>#<mid>` · GSI3 (sparse) `VECTOR#pending` |
| Open question | `USER#<uid>` | `OPENQ#<status>#<created_at>#<qid>` | |
| Agent run | `SESSION#<sid>` | `RUN#<created_at>#<rid>` | |
| Embedding cache | `EMBCACHE#<model>` | `<sha256(text)>` | |

| Access pattern | Operation |
|---|---|
| Messages by session, in order | `Query pk=SESSION#sid, begins_with(sk, "MSG#")`. The zero-padded seq gives order and the pagination cursor. |
| Summary nodes by session and level | `Query pk=SESSION#sid, begins_with(sk, "NODE#L<n>#")` |
| Children of a node | `Query GSI2 gsi2pk=CHILDREN#<parent_id>` (`child_ids` is also denormalized on the parent) |
| Node by id | `Query GSI1 gsi1pk=NODE#<nid>` |
| Memories by user in a time range | `Query GSI1 gsi1pk=USER#uid#MEMORIES, gsi1sk BETWEEN t0 AND t1~` |
| Memory by id / hydration | `GetItem` / `BatchGetItem` on `MEMORY#<mid>` |
| Agent runs by session | `Query pk=SESSION#sid, begins_with(sk, "RUN#")` |
| Pending vector writes (reconciler) | `Query GSI3 gsi3pk=VECTOR#pending`. The index is sparse: only pending items carry `gsi3pk`, so the reconciler never scans healthy rows. |

Every pattern is exercised against the real table shape in `backend/tests/test_dynamo_design.py`.

`scripts/create_tables.py` is idempotent. It points at DynamoDB Local when `DYNAMODB_ENDPOINT_URL`
is set, and at real AWS (standard credential chain) when it is blank. `--recreate` refuses to drop
a real AWS table unless you also pass `--force`.


<img width="390" height="844" alt="9_mobile" src="https://github.com/user-attachments/assets/274b4513-d7db-4208-8697-62b26b1cc983" />
<img width="1440" height="1000" alt="8_chapter" src="https://github.com/user-attachments/assets/1a420407-88ad-40f9-ad8a-200a1c0ca957" />
<img width="1440" height="1000" alt="7_timeline" src="https://github.com/user-attachments/assets/d09f266a-ca38-4fe1-a09b-3501f397ce05" />
<img width="1440" height="1000" alt="6_explorer_recency" src="https://github.com/user-attachments/assets/6fcb41ab-74fb-45f4-871b-808a6e8be49d" />
<img width="1440" height="1000" alt="5_explorer_rerank_mid" src="https://github.com/user-attachments/assets/0f476681-ae4c-4de6-9ed6-dba442453f03" />
<img width="1440" height="1000" alt="4_explorer" src="https://github.com/user-attachments/assets/5eb6a48f-dbfa-4938-b02c-a82fa1d1b6d4" />
<img width="1440" height="1000" alt="3_tree" src="https://github.com/user-attachments/assets/03b26905-42fb-4759-994c-cb030bed5fbf" />
<img width="1440" height="1000" alt="2_interview_after_send" src="https://github.com/user-attachments/assets/4fc43b2d-2af2-465c-8250-f8194e16027c" />
<img width="1440" height="1000" alt="1_interview" src="https://github.com/user-attachments/assets/d5637d34-594f-429e-a99a-849604c721c6" />
