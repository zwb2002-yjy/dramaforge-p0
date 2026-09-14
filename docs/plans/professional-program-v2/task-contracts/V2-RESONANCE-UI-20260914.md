# V2 Resonance UI — 2026-09-14

## Dev integration — 2026-09-14

Owner explicitly authorized committing and pushing the local implementation to
dev. Integration checks on base 794534d passed: 44 affected unit tests, 27 browser
tests (navigation, resonance and manual production), full frontend lint,
typecheck/build and formatting (after formatting design/README.md). No backend
runtime change or paid operation is included. This supersedes the earlier
no-push boundary for this integration only; deployment and release remain out
of scope. Earlier local-only/uncommitted statements below are historical
checkpoints; final commits are recorded by Git and the local progress ledger.

Status: LOCAL_VERIFIED (local implementation; no release claim).

## Authority and current evidence

Owner requested implementation of the preceding Polanyi / 共鸣场 UI design.
Read source order: 01 §§15–20, 02 §§41–44, 06 §§1–2, 03 P3-05/06,
current SceneWorkspace, DirectorSidebar, ShotDirectorSuggestionPanel and shell.
The clean starting worktree contains a film creation application, not a multi-agent
game runtime. SceneWorkspace has canonical snapshots, local drafts and explicit
save / proposal decision / production / formal gates. Its canvas is media or a
text placeholder, and the director interaction is buried below a design form.

## Outcome

Apply the Owner's tacit-first interaction and warm science-fiction visual language
to the actual creation experience. World/scene attention, spatial selection,
contextual natural-language expression, truthful agent feedback, progressively
disclosed controls and accessible equivalents must be functional, not a separate
mock landing page. Owner clarified: “根据该项目真实情况，不是game方向”.
The target is DramaForge film creation, preserving actual scenes, shots, identity
references and Director collaboration. No game runtime, fictional Agent cast,
invented emotions or new product direction is part of this UI reconstruction.

## Owned paths

- frontend/src/features/resonance/*
- frontend/src/features/scenes/* and shots UI components
- frontend/src/features/director/* UI seams
- frontend/src/components/workstation/*, frontend/design/*
- focused frontend unit/e2e tests and this contract

## Requirements / verification

1. World/creation dominates; warm minimal surfaces, controls revealed in context.
2. Spatial focus / group attention / intention transfer have pointer, touch and
   keyboard equivalents. Local gestures never silently save, generate or confirm.
3. Natural-language intent reaches the existing director request with correct
   project, scene, shot and version; dirty and stale guards remain effective.
4. Real received/active/blocked/ready states remain distinguishable, with reduced
   motion and silent operation supported. No invented emotions or execution facts.
5. History and world navigation remain available without persistent dashboards.
6. First-use affordances work without tutorial paragraphs. The 30-second human
   learnability claim requires user observation and cannot be proved by unit tests.
7. Responsive desktop and 390px touch layout; no clipped actions or page overflow.
8. Preserve manual authoring, candidate preview and explicit formal confirmation,
   model identity, isolation, recovery and existing unsaved-change protection.

Focused verification: new interaction unit tests, SceneWorkspace / director /
canvas / navigation regression tests, typecheck, scoped lint, production build,
Playwright integration with existing professional mock fixtures (declared mocked
UI coverage, not real-provider acceptance). Use DOM/layout assertions; screenshots
are evidence only. Broaden tests when affected paths require it.

## Boundaries

No new provider calls, fees, production deployment, remote push/merge or backend
runtime replacement are authorized by this UI task. Seven original plans remain
verbatim. Keep canonical writes through existing API gates. No synthetic success.

## Evidence

Implemented scene portals, spatial shot focus, group attention, editable shot
transition intentions (drag and keyboard/tap equivalents), identity reference
focus, contextual Director input, journal-based Director presence, optional
sound, reduced motion, history disclosure, and a progressively revealed manual
editor. Existing proposal, Save, production and formal confirmation gates remain.

2026-09-14 local checks: production build/typecheck and scoped ESLint passed;
56 unit tests across seven affected suites passed. WorkstationShell fixtures
still emit two pre-existing undefined workflow-overview warnings. Final combined
browser run passed 23 tests: navigation (6), review (1), editing (1), resonance
(10), professional manual (5). This run followed the Owner's scope clarification,
the keyboard transition action, progressive manual editor, persistent request
failure indicator and cross-shot intention isolation changes. Browser coverage
uses mocked APIs, not real-provider acceptance. Scoped ESLint and production
build/typecheck were rerun successfully on these final source changes.
After that combined run, one additional history test passed, proving that
previous turn understanding/suggestion content is initially hidden, opens on
demand and neither replaces the current turn nor performs a business write.
The visible history label was changed to “此前的协作” to match the film product.

### Actual-data follow-up

- Removed raw node keys, English execution codes and artifact IDs from the central
  canvas; retained localized execution state, candidate/formal distinction and
  technical details in the existing details/tray surfaces. Canvas state tests now
  assert both the canonical `data-status` and the human-facing state, rather than
  requiring internal codes as visible copy. The 17 affected unit tests passed.
- Started the current-source Vite preview on `http://127.0.0.1:5173/` (owned exec
  session 97751). Existing gateway health reports database up. Opened the existing
  Wuzhen project and scene `8cdbfad7-c903-4ef3-aeca-fa8af04307a7`; real candidate and
  formal thumbnails loaded, Director journal was idle, its manual editor was
  initially collapsed, and the page had no horizontal overflow. No generation,
  design Save or formal confirmation was invoked in this real-data check.
- Real portrait media exposed the intention below the mobile first screen.
  The 390px layout now limits media to 38svh. The actual input bottom moved from
  945.91px to 813.91px in an 844px-high viewport. A dedicated regression loads a
  900x1600 portrait, asserts successful decode and checks preview/input geometry;
  it passed. Its first attempt failed because the route omitted the workspace
  query string, which was corrected without weakening the geometry assertions.
- Asked the Owner for a real 30-second entry-discovery observation. No response
  has been received yet. Automated or agent-driven operation is not substituted
  for novice learnability. The preview remains available for this observation.
- Final follow-up run: resonance (12) + professional manual (5) passed together;
  production build/typecheck, scoped ESLint and whitespace checks passed. Other
  README/architecture/runbook edits appeared concurrently during verification;
  they are outside this task and have been left untouched.

### Requirement audit

| Requirement | Current evidence | Limit |
| --- | --- | --- |
| Creation-first layout | SceneWorkspace wraps actual CinematicCanvas; sheets closed initially; scene thumbnails are entry points; desktop sheet bounds checked | Aesthetic preference needs Owner feedback |
| Spatial interactions | Resonance e2e covers pointer tether, enclosure, cancellation, keyboard transition and touch group selection | These prepare current-shot suggestions; they do not edit multiple shots |
| Contextual instructions | Mock API assertion checks shot/scene/version and exactly one explicit request; new switch test proves instruction isolation | No provider request made |
| Truthful feedback | Live journal status and keyed mutation status; failed request remains visible after closing panel; actual reduced-motion media assertion; default sound off | No inferred emotions or fictional agents |
| Navigation/history | Existing navigation regression; dedicated history browser test verifies disclosure, current turn identity and no business writes | Uses mocked journal data |
| Discoverability | Local hover/target rings, focus states, input context and direct scene/shot actions implemented | 30-second novice learnability unmeasured; no claim of complete zero-text mastery |
| Responsive accessibility | 390px touch, keyboard, minimum target geometry, reduced motion, sheet reachability checked | No new screen-reader user session |
| Existing authoring gates | 56 unit and relevant browser flows cover draft guards, candidate preview, Save, formal confirmation, review and editing | Mocked frontend verification only |

The Owner supplied concrete usability feedback about Project/Creation/Production/
Editing navigation and workspace-filter jumps. That feedback was implemented and
verified in V2-NAVIGATION-FLOW-20260914.md: 24 relevant unit tests, 25 combined
browser regressions, build/typecheck and scoped lint passed on the resulting UI.
Current worktree inspection and diff whitespace verification found no additional
implementation changes to reconcile after those checks.

The earlier wait for a separate 30-second approval was an agent-imposed process,
not an Owner-required permission gate. It is removed: the requested real-product
UI implementation and concrete feedback fixes are locally delivered. The
30-second learnability statement remains an unmeasured design target, not a
guaranteed outcome or a claimed human-study result. Existing production gates,
accessible equivalents and truthfulness requirements remain in force.

Local implementation is not committed or deployed. This status does not claim
formal Task COMPLETED, real-provider acceptance or a release. Unrelated worktree
changes are preserved. No new product work is inferred from this local delivery.
