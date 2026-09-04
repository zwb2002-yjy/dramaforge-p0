# Task: P1-04 — Asset Reference to Shot Production Execution

## Status

- **State:** IMPLEMENTED
- **Boundary:** Connect the existing Project/Scene/Shot asset-reference binding
  and resolution flow to the existing Workbench execution-plan/executions flow.
  Preserve the existing graph, Worker, Runtime, Provider identity, formal
  keyframe, and approximation gates.

## Implementation evidence

- `AssetReferencePicker` resolves persisted Shot bindings to concrete
  `artifact_id`/`asset_version_id`/`binding_id` execution references, clears
  them on Shot changes and deletion, and invalidates the existing queries.
- `SceneWorkspace` owns the selected-Shot reference context; production and
  picker components are keyed by Shot identity to prevent stale references.
- `ShotProductionActions` freezes one typed reference list and sends it to both
  `execution-plan` and `executions`.
- `WorkbenchExecutionService` validates Shot, Binding, AssetVersion, and
  Artifact project/lineage ownership, hydrates authoritative MIME/hash values,
  and persists the planned references in the frozen NodeRun snapshot.
- The existing unified Worker consumes those frozen references through the
  existing compiler/runtime boundary and fails closed if compiled references
  differ from the frozen selection.

## Verification

- Frontend focused reference/scene/production tests cover selection, plan /
  execute parity, Shot switching, deletion, and real error handling.
- Backend focused Workbench/reference/compiler/unified runtime tests cover
  frozen snapshots, cross-project rejection, and fake compiler/runtime
  transport. PostgreSQL integration remains environment-gated.
- No migration, new reference truth table, Provider, Runtime, Worker, budget,
  pricing, or automatic fallback was added.
