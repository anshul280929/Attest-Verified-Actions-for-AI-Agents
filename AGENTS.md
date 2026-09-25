<!-- GSD:project-start source:PROJECT.md -->

## Project

**Attest: Verified Actions for AI Agents**

Attest is a reliability layer for AI agents that take side-effecting actions such as issuing refunds, cancelling orders, or changing customer records. It records each action before execution, verifies the resulting system state independently of the tool response, reconciles ambiguous outcomes, and prevents an agent from claiming a task is complete without verified evidence.

The initial release is a weekend vertical slice: a Python service, a fault-injecting downstream orders/payments mock, and a reproducible benchmark that compares naive tool calling with Attest under realistic failure modes.

**Core Value:** An AI agent must never claim a real-world action is complete unless Attest has verified that outcome against the system of record.

### Constraints

- **Scope**: Weekend vertical slice — prioritize a demonstrable end-to-end safety property over breadth.
- **Technology**: Python 3.12, FastAPI, Pydantic v2, PostgreSQL 16, Docker Compose — fastest path to a typed, transactional local system.
- **Observability**: OpenTelemetry, Prometheus, Grafana, and Jaeger — make claimed-versus-verified behavior visible and measurable.
- **Testing**: pytest and Hypothesis, plus Docker-based integration tests — state-machine safety must be exercised beyond happy paths.
- **Benchmarking**: Seeded faults and a stubbed LLM in CI — results must be reproducible and avoid API cost in the pipeline.
- **Performance**: Target p95 verification overhead below 150 ms per action on the local Docker setup — verification must remain practical on the happy path.

<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->

## Technology Stack

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12 | Service and test language | The approved scope targets rapid implementation with strong typing and a mature async ecosystem. |
| FastAPI | Current compatible 0.x release, pinned in lockfile | Gateway and downstream mock APIs | Typed request validation, simple dependency injection, and HTTPX-compatible testing fit the thin-service vertical slice. |
| PostgreSQL | 16 | Ledger, event trail, fencing, and transactional outbox | A unique idempotency constraint and the action/outbox transition can share one transaction. `SKIP LOCKED` is intended for multiple queue consumers. |
| SQLAlchemy + Alembic | Current compatible releases, pinned | Persistence and migrations | Use explicit migrations; Alembic autogeneration is only a candidate and must be reviewed manually. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|
| Pydantic v2 | Current compatible release, pinned | Contract and API schemas | Parse YAML contracts and validate gateway payloads at the trust boundary. |
| HTTPX | Current compatible release, pinned | Async downstream client and API testing | Apply downstream timeout budgets and use FastAPI's test client support. |
| PyYAML or ruamel.yaml | Current compatible release, pinned | YAML contract loading | Load declarative contracts only; never execute contract-provided code. |
| pytest + Hypothesis | Current compatible releases, pinned | Unit, integration, and state-machine property tests | Model legal transitions, retry eligibility, and terminal-state immutability. |
| OpenTelemetry SDK | Current compatible release, pinned | Traces, logs correlation, metrics bridge | Emit one trace per task and spans for action, verification, and reconciliation. |
| prometheus-client | Current compatible release, pinned | `/metrics` endpoint | Expose counters, gauges, and latency histograms in seconds. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Docker Compose | Local multi-service environment | Compose must include real PostgreSQL for integration tests. |
| Ruff + mypy | Linting and static checks | Run in CI before test tiers. |
| GitHub Actions | Reproducible CI | Keep the LLM runner stubbed to avoid external API cost. |

## Installation

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| PostgreSQL outbox | Kafka | Add Kafka only when CDC/event fan-out or cross-service throughput becomes a real requirement. |
| PostgreSQL outbox | Temporal | Use Temporal when long-running human approvals and multi-step compensation sagas exceed the weekend slice. |
| FastAPI monolith | Separate gateway and worker repositories | Split only after independent deployment/scaling needs appear. |
| Contract AST/evaluator | Python `eval` | Never use `eval`; an untrusted contract must not execute arbitrary code. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Blind automatic retry on timeout or 5xx | The effect may already have committed. | Persist `UNKNOWN`, reconcile from authoritative state, then retry only after no-effect confirmation. |
| Response body as proof of outcome | Empty 200s, resets, and partial writes invalidate response-only reasoning. | An independent read-path postcondition. |
| Unreviewed Alembic autogeneration | It cannot reliably infer every constraint or expression change. | Review the generated migration and add explicit SQL/constraints. |
| High-cardinality metric labels (`action_id`, `task_id`) | They degrade Prometheus storage and queries. | Put IDs in traces/logs; retain only bounded labels such as tool and verdict in metrics. |

## Stack Patterns by Variant

- Forward Attest's deterministic key in the downstream header.
- Still verify state; downstream idempotency alone cannot prove that the intended postcondition holds.
- Return or retain `UNKNOWN`; do not infer success from a write response.
- Mark this as a deployment blocker for the production evolution, not a condition to bypass.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| FastAPI 0.x | Pydantic v2 | Pin a tested pair; FastAPI's 0.x versioning permits breaking changes. |
| SQLAlchemy async engine | asyncpg | Use an async driver end-to-end; do not call blocking database code in async request paths. |
| OpenTelemetry Python SDK | Collector | Keep instrumentation/exporter versions aligned and route telemetry through OTLP. |

## Sources

- [PostgreSQL locking clauses](https://www.postgresql.org/docs/16/sql-select.html) — `SKIP LOCKED` skips locked rows and is appropriate for queue-like consumers, while giving an inconsistent view unsuitable for general reads.
- [Alembic autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) — generated migrations require manual review.
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/) and [lifespan testing](https://fastapi.tiangolo.com/advanced/testing-events/) — HTTPX/TestClient and lifecycle testing guidance.
- [Prometheus client-library guidance](https://prometheus.io/docs/instrumenting/writing_clientlibs/) — metric types, units, labels, and histogram rules.
- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/) — manual instrumentation and semantic attributes.

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `$gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `$gsd-debug` for investigation and bug fixing
- `$gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `$gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
