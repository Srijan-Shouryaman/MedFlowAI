# services (placeholder)

Reserved for the domain services the backend will need later: extraction,
confidence scoring, verification, clinical NLP, and memory.

Nothing lives here yet. The current task is document storage only, and the
storage path is thin enough that a service layer between the router and
`app/storage/` would add indirection without adding behaviour.
