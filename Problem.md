# Financial Sandbox Product v0.1 - Problem Register

Last verified: 2026-07-24  
Baseline commit: `52d76eccbdf17a4c68d401b79dd3fb29327d20ed`  
Overall resolution status: **OPEN / 未解决（关键垂直切片已修复，仍有 Product v0.1 高优先级缺口）**

## 1. Purpose

This register records the gaps between the current repository and the Product v0.1 goal:

> Build a financial simulation sandbox that advances autonomously, lets users pause at deterministic boundaries, inject external information or state events, observe heterogeneous Agents responding from local information, stop at any time, and save, replay, compare, or fork the resulting history.

Status meanings:

- `RESOLVED / 已解决`: implementation, automated tests, and user-visible workflow all satisfy the acceptance criteria.
- `PARTIAL / 部分解决`: a contract or vertical slice exists, but the end-to-end behavior is incomplete.
- `OPEN / 未解决`: the required product behavior is absent or the main execution path bypasses it.
- `DEFERRED / 暂缓`: explicitly excluded from Product v0.1 and not required for completion.

## 2. Current Resolution Summary

| ID | Problem | Severity | Status |
| --- | --- | --- | --- |
| P-001 | Running does not autonomously advance the simulation | Blocker | PARTIAL / 部分解决 |
| P-002 | Normal observations do not trigger the next Agent decision | Blocker | RESOLVED / 已解决 |
| P-003 | Public and private information bypass delivery and attention semantics | Blocker | PARTIAL / 部分解决 |
| P-004 | Persona and initial private knowledge are not user-configurable end to end | High | PARTIAL / 部分解决 |
| P-005 | Memory, belief, budget, replan, and directive wakeup contracts are disconnected | High | PARTIAL / 部分解决 |
| P-006 | Agent-to-Agent interaction lacks a behavioral response and derivation loop | Blocker | PARTIAL / 部分解决 |
| P-007 | Pending Action and Action Reservation are not used by the execution path | High | RESOLVED / 已解决 |
| P-008 | Background Market Sector is a fixed fixture script, not an autonomous bounded environment | High | RESOLVED / 已解决 |
| P-009 | There is no user Stop command or `user_stopped` terminal boundary | Blocker | RESOLVED / 已解决 |
| P-010 | Save/checkpoint cannot resume the same branch | High | PARTIAL / 部分解决 |
| P-011 | Event log, Kernel, and replay are not one authoritative execution path | High | PARTIAL / 部分解决 |
| P-012 | Normal live initialization has no configured HolderDataProvider | High | PARTIAL / 部分解决 |
| P-013 | Intervention breadth and manual UI do not yet cover the Product v0.1 scenario catalog | Medium | PARTIAL / 部分解决 |
| P-014 | API, UI, Kernel, isolation, and end-to-end acceptance coverage is incomplete | High | PARTIAL / 部分解决 |
| P-015 | Agent audit UI reads obsolete Persona field names | Medium | PARTIAL / 部分解决 |

## 3. Detailed Problems and Closure Criteria

### P-001 - Running does not autonomously advance the simulation

Status: **PARTIAL / 部分解决**  
Implemented 2026-07-24: starting a branch launches an autonomous deterministic runner that consumes pending actions, information deliveries, future interventions, planning requests, and a finite Background Market policy. Pause/Stop freeze future consumption.  
Remaining: pacing modes are absent, persisted scheduler recovery is incomplete, and `sandbox/kernel/engine.py` is still not the sole commit path.

Required resolution:

- One authoritative branch event loop consumes scheduled World, Agent, intervention, background, and control boundaries.
- `Running` advances without repeated manual step commands.
- Max-speed, run-to-boundary, and paced modes change wall-clock pacing only, not virtual event order.
- `Paused`, `Completed`, and `Failed` branches consume no autonomous events.

Acceptance:

- Starting a deterministic scenario advances `sim_time_us`, produces at least two independent Agent decisions, and creates market events without another user command.
- Repeating the same fixture and seed produces the same authoritative event content and ordering.

### P-002 - Normal observations do not trigger the next Agent decision

Status: **RESOLVED / 已解决**  
Implemented 2026-07-24: eligible saved observations pass through `_evaluate_observations`, `AgentRuntime` deduplicates by Observation id, and resulting decisions/planning/action admissions are committed atomically. Private-isolation tests prove the target receives exactly one linked Decision while an invisible Agent receives neither the information Observation nor Decision.

Required resolution:

- Every persisted eligible ObservationPacket creates exactly one deduplicated Decision Opportunity.
- Observation barriers freeze a common World version before Agent decisions begin.
- Invisible or irrelevant events must not create an Observation or wakeup.

Acceptance:

- A private message to Agent B increases B's revision and records a Decision linked to that exact ObservationPacket.
- Agent C, which cannot see the message, receives neither an Observation nor a Decision Opportunity.

### P-003 - Information bypasses delivery and attention semantics

Status: **PARTIAL / 部分解决**  
Implemented 2026-07-24: immutable information ids, deterministic public subsets, private targets, per-Agent delivery timestamps, a durable pending-delivery queue, expiry, salience/capacity selection, Viewed provenance, remembered evidence, and separate Published/Delivered/Viewed boundaries. Agent-authored and Scenario Director information now share this same delivery path.
Remaining: subscription/relationship routing, modeled delivery failure, richer unread state, and archive/replay acceptance for attention provenance are incomplete.

Required resolution:

- Model `Published/Sent`, `Delivered`, `Viewed`, `Remembered`, `Believed`, and `ActedUpon` as distinct boundaries.
- Apply permission, subscription/relationship, channel delay, expiry, AttentionProfile, and cognitive capacity in that order.
- Public publication must not mean universal immediate exposure.
- Private delivery must support delay, failure, unread state, and expiry.

Acceptance:

- A seeded test proves that only a stable subset of Agents views a PublicFeed item.
- Delivery and view timestamps differ when channel latency is configured.
- Attention limits and provenance are saved in the ObservationPacket and survive archive replay.

### P-004 - Persona and initial knowledge are not configurable end to end

Status: **PARTIAL / 部分解决**  
Implemented: `BasePersona`, generated Persona distributions, advanced Scenario/API input for complete `AgentDefinition` plus private initial runtime state, validation, resolved preview fields, and Agent audit display exist.  
Missing: Quick Start/Customize UI editors for explicit Persona, initial Memory/Belief, information access, latency, and cognition profiles.

Required resolution:

- Quick Start offers versioned defaults; Customize exposes common Persona and knowledge controls; Advanced accepts the complete typed AgentDefinition.
- Initial private knowledge has provenance and must not become World truth.
- Role tags remain analytical labels; Capability remains the hard permission boundary.

Acceptance:

- Two Agents with equal assets but materially different risk, skepticism, time horizon, and initial knowledge can be configured and audited.
- The resolved preview displays all sampled and user-specified Agent parameters before start.

### P-005 - Cognition and planning lifecycle contracts are disconnected

Status: **PARTIAL / 部分解决**  
Implemented: planning request states, declarative plans, directive cursors, bounded memory writes/forget, evidence-backed belief proposals, attention/cognitive budget consumption, and budget-window reset exist.  
Missing: memory merge/search services, competing-belief policies, trigger accumulation, tool loop, planning timeout/expiry, and scheduled directive wakeups.

Required resolution:

- Memory and Belief changes are proposal-driven, revisioned, evented, capacity-bound, and Agent-private.
- Planning budget reservation, consumption, release, timeout, and reset semantics are enforced.
- Periodic and cooldown directives schedule one future wakeup rather than pre-generating actions.

Acceptance:

- Tests cover memory write, merge/forget, search budget, competing beliefs, planning timeout, replan accumulation, and periodic directive wakeup across save/fork/replay.

### P-006 - Agent-to-Agent interaction lacks a complete response loop

Status: **PARTIAL / 部分解决**  
Implemented: typed communication directives, public publication, private targeting, immutable information items, and communication capability checks.  
Missing: autonomous recipient response, forwarding/summary/misquotation derivation, subjective trust inputs, conversation delay/failure, and social protocol events.

Required resolution:

- Agent-authored information records the true author and optional source references.
- Forward, summarize, comment, rewrite, and leak operations create derived items without mutating the source.
- Relationships affect candidate delivery and subjective belief formation without becoming an authoritative global trust score.

Acceptance:

- A three-Agent test demonstrates private disclosure, selective forwarding, changed wording, preserved derivation, divergent beliefs, and a downstream market action.

### P-007 - Pending Action and Action Reservation are not active

Status: **RESOLVED / 已解决**  
Implemented 2026-07-24: every future action is admitted into durable Pending Action and Action Reservation state; the runner orders it against interventions and deliveries, execution consumes the reservation, and rejection/expiry/Stop release it. The future-halt and expired-action acceptance tests prove that invalidated actions do not execute or leak reservations.

Required resolution:

- World admission validates capability and resources, creates a reservation, and schedules a Pending Action.
- Execution consumes the reservation; cancellation, expiry, rejection, failure, or Stop releases it.
- A future intervention or risk event can occur before the Pending Action without being skipped.

Acceptance:

- A scheduled market halt before an Agent order causes a deterministic rejection or cancellation and leaves no leaked reservation.

### P-008 - Background Market Sector is not autonomous

Status: **RESOLVED / 已解决**
Implemented 2026-07-24: an autonomous seeded Background Market policy establishes a five-level, asset-backed opening book before the first Observation, then uses finite balances and the normal Action/CLOB/Ledger pipeline for bounded quote refresh, cancellation, replacement, and protected taking of external top-of-book liquidity. Background balances are derived as initial total supply minus all visible Agent allocations; they are not preset inputs. Spread, outer-depth impact, level count, refresh interval, and quote-size fraction are typed scenario parameters. Autonomous flow begins after Start; the deterministic Fixture step remains an explicit test control only.

Required resolution:

- A seeded ParticipationPolicy generates bounded orders, cancellations, and activation events through the same Action/CLOB/Ledger pipeline.
- Background capital is finite, conserved, auditable, and unable to dominate explicit Agents by hidden replenishment.
- Background flow begins only after the opening Observation Barrier.

Acceptance:

- The market remains active for a bounded test horizon, eventually reflects finite inventory constraints, and preserves both Token and USDx totals.

### P-009 - No user Stop boundary

Status: **RESOLVED / 已解决**  
Implemented 2026-07-24: Stop is available through API/UI, works from Ready/Running/Paused/Checkpointed, records `Completed(reason=user_stopped)`, cancels pending actions and deliveries, releases reservations, is idempotent, and prevents restart or later autonomous events.

Required resolution:

- An idempotent Stop request completes the current atomic event and Observation Barrier, cancels/reconciles queued work according to contract, then enters `Completed(reason=user_stopped)`.
- Completed history is immutable but can be replayed, archived, or forked from a checkpoint.

Acceptance:

- Stop succeeds from Running and Paused, is idempotent, records the terminal reason, and prevents later events on that branch.

### P-010 - Checkpoint does not support same-branch continuation

Status: **PARTIAL / 部分解决**  
Implemented 2026-07-24: save retains the current branch status, serializes pending deliveries/actions/reservations/runtime state, and the same Ready/Paused/Checkpointed branch can resume. Completed save does not mutate history.  
Remaining: explicit quiescing and terminal accounting for in-flight provider calls still need recovery tests.

Required resolution:

- User save creates a durable checkpoint without making an otherwise active branch permanently non-runnable.
- Quiescing waits for or terminally records in-flight provider work; it does not silently cancel it.

Acceptance:

- A branch can pause, save, resume, advance, stop, reload in the same runtime version, and continue from the saved state.

### P-011 - Kernel, event log, state, and replay are not one path

Status: **PARTIAL / 部分解决**  
Implemented: append-only events, branch sequence, hashes, current world snapshots, checkpoints, archive import/export, historical ObservationPackets, exact manifest-to-member archive validation, and rejection of duplicate or unhashed archive members.
Missing: the Kernel as the sole commit path, persisted scheduler state, replay from checkpoint plus events, and recovery tests after an interrupted run.

Required resolution:

- All authoritative changes pass through the same single-writer scheduler and atomic commit path.
- Checkpoints include queues, reservations, RNG streams, runtime states, and control state needed for continuation.
- Historical views use saved observations; recovery uses checkpoint plus committed events.

Acceptance:

- Crash-recovery and fork tests produce valid hash chains, isolated mutable state, and no duplicate decisions/actions.

### P-012 - Normal live initialization has no HolderDataProvider

Status: **PARTIAL / 部分解决**  
Implemented 2026-07-24: a configured finalized-snapshot file adapter provides chain/token matching, finalized block provenance, content hashing, a 16 MiB bound, cache invalidation, preflight, and fail-closed behavior via `SANDBOX_HOLDER_SNAPSHOT_PATH`.  
Remaining: no direct supported-chain network adapter or guided Quick Start provider setup exists.

Required resolution:

- Product v0.1 includes at least one supported chain/token holder adapter with finalized-block semantics, bounded cache, provenance, and preflight.
- Provider failure does not silently use Fixture, stale data, another chain, or mixed-provider output.

Acceptance:

- Normal Quick Start resolves a supported chain/token into a complete preview and clearly rejects unsupported or unavailable providers.

### P-013 - Product intervention catalog is incomplete

Status: **PARTIAL / 部分解决**  
Implemented: paused command-scoped Director, draft/confirm, typed state and information effects, atomic current stages, future stages, causal-state checks, audit records, a versioned seven-entry template catalog, and manual UI fields for entity/relationship effects.  
Missing: executable compound template bodies and per-template archive/fork/replay acceptance coverage.

Required resolution:

- Ship versioned templates for venue halt/outage, custody freeze, wallet-access leak, selective rumor, public announcement, bounded asset shock, and new institution/relationship creation.
- Natural-language interpretation remains non-authoritative and requires preview plus confirmation.

Acceptance:

- Every template passes preview, causal-state validation, atomic commit, local observation, archive, fork, and replay tests.

### P-014 - Acceptance coverage is incomplete

Status: **PARTIAL / 部分解决**  
Current verification: 53 Python tests pass, including product acceptance, API workflow, Stop, reservation/intervention ordering, private Agent isolation, advanced Agent configuration, holder snapshot tests, dynamic Background Market residual allocation, bounded Background Market behavior, delayed Director information delivery, completed-branch export, forked pending actions, and archive tamper rejection; TypeScript check and production frontend build pass.
Gaps: Kernel/recovery/property/SSE coverage remains incomplete. Browser QA was attempted on 2026-07-24 but the active browser policy blocked access to the local app, so no rendered workflow or component evidence is claimed.

Required resolution:

- Add contract, property, scenario, recovery, isolation, API, SSE reconnect, and browser end-to-end suites.
- Treat Product v0.1 workflow tests as release gates rather than relying on unit coverage percentage.

Acceptance:

- The Product v0.1 acceptance scenarios in `docs/完整产品v0.1.docx` all pass in Fixture/Replay mode; supported live preflight and a bounded real-LLM smoke test also pass.

### P-015 - Persona fields are displayed incorrectly in the Agent UI

Status: **PARTIAL / 部分解决**  
Implemented 2026-07-24: the Agent UI now binds `risk_tolerance_milli` and `time_horizon`, and TypeScript contract checking passes.  
Remaining: the required rendered component/browser assertion could not be completed because local browser access was policy-blocked.

Required resolution:

- Bind UI fields to the versioned AgentDefinition contract and add a component/API test.

Acceptance:

- Agent View displays the configured risk tolerance and time horizon for Fixture and generated Agents.

## 4. Resolved Foundations

These foundations are not sufficient for product completion, but are currently considered implemented and should be preserved:

- Integer Ledger and local spot CLOB with fees, protected market orders, and conservation checks.
- Append-only branch event sequence and event hash verification.
- Checkpoint, branch isolation, full-tree archive export/import, and persisted Agent audit records.
- Typed Observation, Decision, Planning Request, Strategy Plan, Action Receipt, and intervention contracts.
- Paused, previewed, confirmed, typed Intervention Plans with atomic current-time stages.
- Command-scoped Scenario Director that cannot directly write arbitrary World state.
- OpenAI provider boundary with server-side credentials, structured output validation, and stored audit records.
- Analyst and Agent audit surfaces for balances, observations, decisions, plans, and receipts.

## 5. Product v0.1 Exit Rule

The overall status may change to **RESOLVED / 已解决** only when all Blocker and High items above are resolved, the complete acceptance suite passes, normal Quick Start works with a supported live initialization path, and a user can complete this workflow without internal/debug APIs:

1. Configure heterogeneous Agents and inspect the resolved preview.
2. Start an autonomously advancing branch.
3. Observe local-information-driven Agent behavior and Agent-to-Agent communication.
4. Pause at a deterministic boundary.
5. Draft, preview, confirm, and apply an external event.
6. Resume and observe divergent responses.
7. Stop at a user-selected boundary.
8. Save, replay, fork, inject a different event, and compare branches.
