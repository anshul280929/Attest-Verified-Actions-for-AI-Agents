# Attest: Verified Actions for AI Agents

## What This Is

Attest is a reliability layer for AI agents that take side-effecting actions such as issuing refunds, cancelling orders, or changing customer records. It records each action before execution, verifies the resulting system state independently of the tool response, reconciles ambiguous outcomes, and prevents an agent from claiming a task is complete without verified evidence.

The initial release is a weekend vertical slice: a Python service, a fault-injecting downstream orders/payments mock, and a reproducible benchmark that compares naive tool calling with Attest under realistic failure modes.

## Core Value

An AI agent must never claim a real-world action is complete unless Attest has verified that outcome against the system of record.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Record every side-effecting action in a durable ledger before execution and use deterministic idempotency keys to prevent duplicate effects.
- [ ] Classify action outcomes as `VERIFIED`, `FAILED`, or `UNKNOWN` by checking contractual postconditions against downstream state.
- [ ] Reconcile ambiguous actions safely and permit retry only after a confirmed no-effect outcome.
- [ ] Reject completed task claims that lack citations to required, verified action IDs.
- [ ] Demonstrate the reliability benefit with a seeded, reproducible fault-injection benchmark against a naive baseline.

### Out of Scope

- Multi-tenancy — excluded from the weekend vertical slice.
- UI — the first release is API, CLI, and benchmark focused.
- Authentication and authorization — deferred to production hardening.
- Multi-agent orchestration — Attest initially protects a single agent runner.
- Verifying the verifier's own read path — the verifier is treated as a trusted boundary for this slice.
- LLM-judged prose quality — Attest verifies actions and completion claims, not writing quality.

## Context

Production agents can report success after timeouts, silent empty 200 responses, partial writes, or retries that duplicate a side effect. Existing retries, idempotency keys, guardrails, and observability do not establish whether the real system state matches the agent's claim.

Attest applies payments-engineering patterns: a PostgreSQL action ledger and transactional outbox, idempotent downstream calls, contract-defined postconditions and compensation, a reconciler using independent read paths, resource fencing for ambiguous actions, and a completion guard. Its delivery model is at-least-once with idempotent effects and independently checked, effectively-once outcomes — not exactly-once delivery.

The benchmark will run refund, cancellation, and multi-step scenarios across normal operation, timeout-after-commit, empty-200, duplicate-delivery, and partial-write fault profiles. It will report false-success rate, duplicate side effects, task completion, honest-pending rate, and added latency using downstream database state as ground truth.

## Constraints

- **Scope**: Weekend vertical slice — prioritize a demonstrable end-to-end safety property over breadth.
- **Technology**: Python 3.12, FastAPI, Pydantic v2, PostgreSQL 16, Docker Compose — fastest path to a typed, transactional local system.
- **Observability**: OpenTelemetry, Prometheus, Grafana, and Jaeger — make claimed-versus-verified behavior visible and measurable.
- **Testing**: pytest and Hypothesis, plus Docker-based integration tests — state-machine safety must be exercised beyond happy paths.
- **Benchmarking**: Seeded faults and a stubbed LLM in CI — results must be reproducible and avoid API cost in the pipeline.
- **Performance**: Target p95 verification overhead below 150 ms per action on the local Docker setup — verification must remain practical on the happy path.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use three-valued outcomes (`VERIFIED`, `FAILED`, `UNKNOWN`) | Ambiguous tool results must not be mistaken for success or safely retried. | — Pending |
| Retry only after confirmed no effect | Prevent duplicate side effects after timeouts, resets, 5xx responses, or silent failures. | — Pending |
| Store ledger transitions and outbox writes in one PostgreSQL transaction | The durable action record and reconciliation work must not disagree. | — Pending |
| Verify via an independent downstream read path | Tool responses are claims; system state is the authority. | — Pending |
| Build A0 vs A2 benchmark first; A1 is stretch | The core evidence is Attest versus naive direct tool calling within a weekend. | — Pending |
| Cut compensation, A1, and Grafana first if time is constrained | Preserve the essential ledger, verifier, reconciler, completion guard, and benchmark. | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `$gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. “What This Is” still accurate? → Update if drifted

**After each milestone** (via `$gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-20 after initialization*
