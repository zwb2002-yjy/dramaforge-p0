# V1-D6-DIRECTOR-TOOLS-DECISIONS-UI-20260910

Status: IN_PROGRESS, local implementation and verification only.

Authority: Owner implementation §10, Owner design §§8–10, the registered V1.1
amendment, and the original Professional product interaction rules. D1–D5
stable production/runtime contracts and locally verified engine migration are
inputs. Canonical Proposal, Story/Scene/Shot, Review/Repair, EditSession/
Timeline, Export, NodeRun, ProviderOperation and Artifact records remain the
only product facts.

Current evidence: Story, Shot and Editing expose typed, audited text proposal
services and explicit apply/save APIs. Newly created Story and Editing Proposal
Turns bind to the configured LangGraph engine; Shot suggestions and proactive
recommendations bind as draft-only runtime facts without inventing a Proposal
row or changing the saved Shot. The Scene operation sheet reads persisted
runtime fields, uses versioned stop/decision endpoints for bound Turns and
restores suggestions from server snapshots. Its explicit AUTO actions create a
bounded one-shot authorization and durable Director wakeup through the product
API; the ordinary production buttons remain the independent manual path. The
locked frontend dependency tree has been restored and TypeScript, lint, unit
and production build checks pass. Formal candidate, Review/Repair, Editing and
Export remain their existing business services.

Outcome: reconnect the new Director runtime to existing Story/Shot/Review/
Repair/Editing Proposal and production services without giving it direct domain
write access. A user can start or ignore the optional Assistant, inspect its
server snapshot after reconnect, apply/reject only selected typed operations,
save explicitly, authorize a bounded production action, confirm Formal through
the existing endpoint, and request Export through the existing editing path.
AUTO advances only within a persisted grant to the next confirmation point;
ASSIST exposes proposals and waits for the user; MANUAL creates no proactive
turn or production command. Closing the panel changes only visibility and does
not cancel accepted work or remove manual tools.

Owned paths: Director runtime domain adapters and event mapping, existing
Story/Shot/Editing API integration, versioned runtime client types, the current
Director status/panel components, focused backend/frontend tests, generated
OpenAPI types, and this contract. New production graph types, direct Provider/
FFmpeg tools, SDK memory as product truth, component-library redesign, paid
calls, shared database migration, deployment and release evidence are outside
this task.

Acceptance:

1. A persisted Story Proposal can be partially accepted/rejected; only selected
   commands change canonical Story facts and the runtime reaches the matching
   decision checkpoint once.
2. Shot suggestions preserve explicit user intent and frozen versions. Applying
   a suggestion remains a draft operation; Save, Execute and Formal stay
   separate APIs.
3. An AUTO media action requires the exact persisted authorization and creates
   one canonical NodeRun. ASSIST and MANUAL never use that autonomous grant
   path; switching to MANUAL invalidates an unaccepted grant.
4. Production completion/failure and Formal selection resume the bound engine
   from the independent Inbox/wakeup path. Director lag never changes the
   production receipt or hides an in-flight result.
5. Editing applies only selected allowlisted operations to its draft/session;
   timeline-capable repair and material regeneration remain distinct routes.
6. The side panel shows user-facing processing/wait/failed/stopped state, uses
   the graph revision for bound Turns, stops polling at terminal state, and
   restores from the server after navigation/reconnect. Queue/checkpoint IDs
   stay out of the ordinary creative UI.
7. Closing or never opening the panel leaves all manual Story, keyframe, video,
   Formal, Review, Repair, Editing and Export controls available. D7/D8 own the
   full real-artifact MP4/SRT recovery matrix and release candidate evidence.
8. Cross-shot/session navigation and background refresh never copy A's draft,
   Proposal or runtime action into B. A stale version, rejected context, revoked
   authorization or changed autonomy fails before a new production command.

Local tests do not constitute formal completion without reviewed commit and
the repository lifecycle evidence.

Local implementation and evidence (2026-09-10):

- `DirectorRuntimeStartService` accepts only newly created/replayed-bound Turns.
  Persisted Story/Editing Proposals and detached Shot draft suggestions share
  the same immutable engine binding; existing blank legacy Turns are never
  guessed into a graph checkpoint.
- `DirectorDomainRuntimeTools` reads canonical Proposal decisions, detached
  Turn decision facts, production receipts and Formal events. Its only media
  write path submits an exact persisted one-shot authorization through
  `ProductionAuthorizations`; the graph has no Provider, FFmpeg, SQL or direct
  Artifact tool.
- The versioned detached decision endpoint stores the accepted/rejected
  operation indices and output hash before enqueueing a durable resume. The
  graph completes the draft-only branch with zero NodeRuns; the UI applies the
  selected result to local draft state and still requires Save.
- The product-facing AUTO delegation endpoint freezes the exact Shot execution
  plan, persists a short-lived one-shot `ProductionAuthorization`, records the
  accepted typed decision and starts one bound Turn. A retry of the same
  decision reuses that Turn and wakeup; the independent Director worker creates
  exactly one canonical NodeRun. New delegation is rejected in ASSIST/MANUAL.
- Stop is versioned even before the first graph checkpoint exists. A queued Turn
  can be cancelled with its initial graph revision; racing start/stop wakeups
  both settle successfully and create no NodeRun.
- Creative-profile changes mark active Turns and their runtime controls stale,
  clear leases and make older wakeups successful no-ops. The existing
  production authorization Gate rejects pending grants after profile version or
  MANUAL changes while preserving already accepted NodeRuns.
- Real PostgreSQL/checkpointer/Worker coverage now includes persisted Proposal
  partial decision, one exact AUTO command receipt, and detached Shot reject
  completion. The focused D6 backend suite passed 65 tests, runtime/API tests
  passed 12, the detached PG chain passed, full backend unit regression passed
  1,041 tests, and frontend passed 154 tests plus lint/typecheck/build. Focused
  Playwright coverage for the Assistant, Editing and manual Scene workspace
  passed 6 browser tests, including AUTO delegation, sheet close/draft
  retention, the manual production controls and Formal.
- Formal lifecycle status stays `IN_PROGRESS`: no reviewed candidate commit,
  paid model call or production deployment was authorized for this local run.
