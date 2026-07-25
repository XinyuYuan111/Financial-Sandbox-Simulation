# ADR 0003: Agent communication intent and market cognition

- Status: Accepted
- Date: 2026-07-25
- Scope: Agent communication, observation-driven cognition, directive scheduling, and analyst presentation

## Context

The runtime already delivered public and private information through the authoritative event, observation, memory, and belief pipeline. It did not let the local planner choose selective disclosure, explicit withholding, or a deceptive claim. It also wrote memories only from delivered information, so order-book and trade observations affected immediate planning without becoming durable cognition. Periodic directives depended on unrelated future observations and therefore were not actually periodic in a quiet market.

## Decision

Communication remains one typed directive. `PrivateChannel` expresses selective disclosure. `communication_mode=withhold` records a bounded decision not to release the Agent's private assessment. `claim_intent=strategic_deception` means the released directional claim contradicts the Agent's recorded private assessment. This is an Agent-relative intent, not an assertion that the kernel knows objective truth.

Recipients see only the released information item and its claimed direction and confidence. They never receive `claim_intent` or `private_assessment_direction`. The analyst event stream records the disclosure scope and private intent. A withheld directive creates an analyst-only `InformationWithheld` event and does not wake another Agent.

The demo policy may combine a communication directive with a market directive. Random Agents without an explicit archetype receive publish capability by default. When a non-replay planner returns an active market plan without communication, the host normalizes that same candidate by appending one bounded communication directive; this keeps communication independent of whether an LLM happened to include it. Communication runs every two simulation minutes with at most six emissions per plan. Existing directive cursors provide the next eligible time; that time now enters the branch event queue as a `directive_wakeup`, so no second scheduler or state owner is introduced.

Resolved scenarios and runs remain immutable. A scenario resolved before the publish-capability default changed keeps its saved Agent definitions, and its runs keep their plans for deterministic replay. The scenario must be resolved again before creating a communication-enabled run; the analyst UI identifies the legacy capability state instead of silently rewriting history.

Market-change and initial observations can create a bounded market-snapshot memory and an evidence-backed `observed_market_state` belief. Identical adjacent snapshots are not duplicated. Agent-authored messages may be remembered as statements, but they do not become that same Agent's market-signal belief. Other Agents continue to discount claims through their own skepticism.

## Consequences

- Agent communication can be public, selective, withheld, or strategically deceptive while remaining replayable and auditable.
- Deceptive intent is protected from recipients and cannot silently mutate World facts.
- Market observations and Agent communication both contribute to durable private cognition.
- Communication frequency is guaranteed by virtual-time scheduling rather than incidental market activity.
- Trust learning, conversation failure, multi-step forwarding transformations, and social protocols remain separate unresolved work.
