# P10-C4 — Runtime and Provider single path

**Status:** USER-AUTHORIZED / IN PROGRESS
**Parent:** P10 legacy hard removal

## Outcome

Remote image/video execution is owned by the unified Provider compiler/runtime.
The Worker never selects a historical Director or batch branch, and the
configuration no longer contains a switch that can restore the removed media
path. Local voice is an explicit zero-cost runtime with the same NodeRun →
ProviderOperation → Artifact lineage.

## Implemented boundary

- Product execution dispatches keyframe/video directly to unified-v1.
- Provider-specific reference transport decisions live in the provider delivery
  layer, not in shared execution orchestration.
- Direct Shot start/rerun/approve/reject/lock/manual-media routes are removed;
  Workbench execution-plan/executions and Workbench Review/Repair routes remain.
- The old first-frame/P0 fake pipeline and shadow-switch report are removed.
- The retained provider adapter bridge has a neutral name and remains below the
  CapabilityRouter boundary.
