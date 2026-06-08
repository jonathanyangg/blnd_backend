# TODO

- [ ] **Comments: real-DB integration tests for service logic.** The comments
  feature currently only has the older mock-based view tests. Add real-DB tests
  (using the `db`/`client` fixtures + factories) covering:
  - reply reparenting to the direct parent and read-time flatten to one level
  - `@mention` parsing + `comment_mentions` notifications (dedupe with reply
    target, skip self) on both top-level comments and replies
  - subtree soft-delete (tombstone comment + all descendants)
