# ADR 0002: Demo Agent activity policy

- Status: Accepted for demo and LLM smoke modes
- Date: 2026-07-25
- Scope: `test_fixture` rule planners and `live_llm_smoke` no-op fallback

## Context

An empty directive list is a valid planning result: an Agent may decide to hold and protect capital. The previous fixture path, however, hard-coded an empty plan for every rule Agent. It did not invoke the local rule planner, and provider requests omitted the Agent's capabilities and role tags. The result was a technically valid but inert demo, regardless of Persona aggressiveness.

The demo must visibly exercise planning, communication, admission, reservation, matching, settlement, and observation without weakening the authoritative runtime contracts or silently changing `live` behavior.

## Decision

The local rule planner uses the saved observation, free balances, Persona, role tags, capabilities, and scenario seed to choose one bounded directive:

- information participants and eligible issuers publish a public market view;
- liquidity providers submit a two-sided quote;
- capital holders submit a protected market order, while ordinary market participants begin with a passive limit order and high-risk participants alternate into protected orders on later revisions.

Prices are aligned to the configured market tick and quantities are capped by free balances with a fee reserve. Every resulting action continues through the existing controller, capability checks, risk admission, reservations, latency queue, CLOB, ledger, receipts, and event log. Public information continues through publish, delivery, view, and observation events.

Public communication may carry a structured `signal_direction` and `signal_confidence_milli`. Delivery places these claims in the recipient observation and belief state. Trading Agents discount them by skepticism, use the resulting signal as a side input, and reopen planning on a new information observation. Plain text without a structured signal remains a normal observation.

The background market sector owns a maker account and a separate `background_order_flow` account. The maker maintains the multi-level book and consumes explicit Agent top-of-book orders. The flow account uses persisted named RNG streams to sample taker and directional-limit actions, with configurable probabilities and free-balance limits. `BackgroundOrderFlowSampled` records every sample. The two accounts share only the sector's initial asset budget and cannot self-match.

Each Intervention Stage also carries one signed `background_order_flow_impact_milli` assessment. The Scenario Director infers it from the complete user event: `-1000` is extremely bearish, `0` is neutral, and `+1000` is extremely bullish. A confirmed non-zero assessment becomes an auditable, 30-simulation-minute impact that decays linearly. Concurrent impacts add and clamp to the same range. The current net value biases buy versus sell probability between 10% and 90%, raises bounded activity and quantity with impact strength, and preserves the original named RNG consumption, ledger limits, CLOB matching, and 10% contrary-flow noise at the extremes. It never writes a price directly.

For `live_llm_smoke` only, an otherwise valid provider candidate with no directives is sampled against a deterministic 500/1000 fallback probability. If a whole planning batch remains inactive, the first capability-safe candidate is forced so the smoke demo has an activity floor. Each sample emits `AgentNoOpFallbackSampled` with the policy version, probability, sample, selection, forced flag, request ID, and effective directive types. The raw provider record remains unchanged.

The `live` mode has no fallback. A no-action result remains valid there. The CLOB also skips an Agent's own resting orders to prevent demo activity from creating self-trades.

## Consequences

- New fixture runs are active without an external LLM and remain reproducible for a given scenario seed.
- LLM smoke runs cannot be entirely inert solely because every provider returned an empty plan.
- Provider output and host intervention remain distinguishable in the audit trail.
- Background volume and price movement do not depend on a small Agent population being present.
- User interventions can shape the future background price path without bypassing orders, finite inventory, or settlement.
- Existing runs and stored plans are not rewritten; a new run is required to use the policy.
- The policy is intentionally simple and versioned. It is demo stimulus, not an alpha model or a production trading strategy.
