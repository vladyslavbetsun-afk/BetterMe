Specs live in docs/specs/. Always read 00-shared-reference.md before coding.
Legacy artifacts in legacy/ are reference implementations — port logic, not UI.
Never message, comment, or transition anything without going through core/outbound.py.
No per-person speed/ranking/performance metrics (Legal gate, spec 05 §4).

Record every Phase 0 answer and every judgement call in docs/decisions.md.
Before pushing: `ruff check src tests scripts`, `pytest -q` (needs a local Postgres, see README), `bandit -q -r src -ll`.
