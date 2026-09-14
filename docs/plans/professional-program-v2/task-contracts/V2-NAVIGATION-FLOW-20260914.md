# Navigation flow correction — 2026-09-14

## Dev integration — 2026-09-14

Owner explicitly authorized committing and pushing the current local changes to dev.
Rechecked on base 794534d after the frontend skeleton integration: 44 relevant
unit tests and 27 browser tests passed, along with full frontend lint,
typecheck/build and diff whitespace checks. Frontend format check required only
Prettier formatting of design/README.md and then passed. Existing documentation
updates are included in a separate commit. This is dev integration, not a
container release gate, production deployment, or real-provider acceptance.
Earlier uncommitted/local-only statements below describe the pre-integration
checkpoint; Git and the local progress ledger record subsequent commits.

Status: LOCAL_VERIFIED (not committed or deployed). Owner requests fixing Project / Creation / Production / Editing switching and workspace-filter anchor jumps.

## Follow-up: explicit project context and settings return (2026-09-14)

Status: LOCAL_VERIFIED (not committed or deployed). Owner reports remembered projects incorrectly enabling creation from Lobby, hidden Settings navigation, ambiguous workspace/project naming and return behavior. Authority additionally includes navigation-ia Owner amendment §§3–7, 11 and current Owner clarification.

Outcome: Lobby Creation selects a project explicitly; global settings do not infer a current project from persistent history. Settings navigation opens on entry and repeated activation, separates global scope from project scope, preserves a validated return location including search state. Workspace wording clarifies its role as a container for projects; defaults identify new-project scope. No runtime changes or production writes.

Owned paths additionally include settings route validation and settings page labels. Verify browser back/forward, settings return/reload, mobile activation, stale remembered-project isolation, existing navigation and manual dirty guards; build/typecheck and scoped lint.

Follow-up evidence: navigation browser suite 10 and professional-manual regression 5 passed (15 total). Shell unit 21 and navigation preference unit 4 passed (25 total); build/typecheck, scoped ESLint and diff whitespace checks passed. Browser cases assert explicit project selection after leaving a project, no current-project settings from stale browser history, direct settings navigation on mobile, repeated Settings activation preserving the selected page, return after refresh, scene restoration and browser back/forward. Return locations are URL-carried and validated as internal lobby/project routes; no settings-return loop or external destination is accepted. Labels now distinguish workspace project grouping and new-project defaults, with project settings under a separate scope label. Defaults remain the existing read-only capability. No provider operation, backend change, commit or deployment.

Authority: 01 §§12–14, 02 §41, 06 §1, 03 P3-05, current routes and workspace preferences. Preserve existing dirty guards and all production gates. Existing unrelated worktree changes stay untouched.

Outcome: project lobby controls operate as filters/views, not document anchors; active primary navigation exposes its context; project reentry preserves validated project-specific location; switching creation workspaces remains inside the current project. No backend runtime or paid operations.

Owned paths: workstation navigation shell, index/project routes, navigation preference helper, focused navigation tests and this contract.

Verification: navigation unit/e2e, manual dirty-guard regression, typecheck/build, scoped lint and diff review. Local only; no deployment or remote changes.

Implemented flow:
- Lobby selects projects and switches all/recent/workspace-filter views with route search state; legacy hashes redirect before rendering and never anchor-scroll the document. Workspace control gains focus after layout.
- Desktop context navigation is initially visible at 720px and above. Clicking the active Project/Creation entry reveals its context without changing the current workspace; mobile still uses the labelled drawer.
- Existing project reentry restores the browser's validated per-project pathname (including a scene ID), falling back to the existing server last-view preference. This does not claim cross-device restoration of a shot or editing-session query parameter.
- New-project visibility follows URL state, including cancellation and reopening. Manual authoring and unsaved-change guards remain unchanged.

Evidence: 24 unit tests (navigation preferences + workstation shell), 25 combined browser tests (navigation 8, professional manual 5, resonance 12), production build/typecheck, scoped lint and diff whitespace checks passed. Existing shell fixtures emit two unrelated workflow-overview warnings. Mocked lobby workspace/project lists were completed to cover actual reentry, and old expectations of hidden laptop navigation / lost last-view state were replaced with assertions of the requested behavior.

Actual local backend check: legacy `/?create=false#project-filters` resolves to `/?create=false&panel=workspace`, scrollY=0, workspace selector focused at y=221.19, no horizontal overflow. No paid request, generation or canonical save executed. Existing unrelated source/doc changes preserved.
