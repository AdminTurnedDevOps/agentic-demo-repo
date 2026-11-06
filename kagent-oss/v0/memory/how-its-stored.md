Long-term memory → Postgres (pgvector)

Stored in a memories table with this schema:

```

  ┌──────────────┬─────────────┬──────────────────────────────────────────────────┐
  │    Column    │    Type     │                     Purpose                      │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ id           │ UUID        │ Primary key                                      │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ agent_name   │ string      │ Scoped per agent                                 │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ user_id      │ string      │ Scoped per user                                  │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ content      │ text        │ The actual memory text                           │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ embedding    │ vector(768) │ pgvector 768-dim embedding for similarity search │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ metadata     │ text (JSON) │ Extra context                                    │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ expires_at   │ timestamp   │ TTL expiry                                       │
  ├──────────────┼─────────────┼──────────────────────────────────────────────────┤
  │ access_count │ int         │ Tracks popularity (≥10 = TTL gets extended)      │
```

The `context.compaction` feature is purely in-memory, within the agent runtime process. It manages the conversation event history during a single session by summarizing/dropping older events to stay under token limits. Nothing is written to a database, it's handled by the ADK runtime (Python or Go) as it builds the LLM prompt.

```
  ┌────────────────────┬────────────────────────────┬───────────────────────────┐
  │      Feature       │        Stored where        │ Persists across sessions? │
  ├────────────────────┼────────────────────────────┼───────────────────────────┤
  │ memory             │ Postgres with pgvector     │ Yes — until TTL expires   │
  ├────────────────────┼────────────────────────────┼───────────────────────────┤
  │ context.compaction │ Agent runtime (in-process) │ No — session-scoped only  │
  └────────────────────┴────────────────────────────┴───────────────────────────┘
```