# Architecture Decision Records

Short records of decisions that are expensive to reverse or surprising to a newcomer.
Each states the context, the decision, and what it costs — so a future reader can judge
whether the reasoning still holds instead of guessing at intent.

Add one when a decision would otherwise be re-litigated every few months. Do not add one
for routine choices.

| # | Decision |
|---|---|
| [0001](0001-project-structure.md) | Vertical feature slices over a shared core |
| [0002](0002-error-model.md) | RFC 9457 problem details as the error contract |
| [0003](0003-transaction-boundary.md) | One request, one transaction |
| [0004](0004-storage-abstraction.md) | Storage behind a protocol, business layer holds keys |
| [0005](0005-auth-extension-point.md) | Auth primitives without an auth system |
| [0006](0006-no-task-queue-yet.md) | No task queue in the foundation |
| [0007](0007-review-findings.md) | What the architecture review changed, and why |
