# Current Model Supply Drift

**Task:** `MS0-01-CURRENT-MODEL-SUPPLY-DRIFT`  
**Audited baseline:** `dev@ac1e5991c8f617d23629b14d23b043b29918831d`  
**Audit date:** 2026-08-26  
**Authority:** Review Revised Design §§ 3–6, 19–21 and Review Revised Implementation Plan §§ 5–7, read with the seven-plan precedence in [`README.md`](README.md).

## Executive verdict

The repository has a substantial Provider / Manifest / Binding / Runtime foundation and must **reuse** it. It is not yet compliant with the Review P0 execution-identity gate. The first execution task is therefore the revised **MS1-R + MS1-C** slice, not Phase 4 UI work and not a Provider rewrite.

The high-risk drift is precise: the current code can plan model X through a profile but, when no credentialed matching binding exists, select a legacy project binding Y. It also has several independent selection and runtime entry points, while the required `ExecutionModelResolver`, typed `ExecutionModelResolution`, immutable Connection/Credential revisions, and unified execution identity snapshot do not exist.

## Current path map

| Required audit subject | Current code path | Observed responsibility | Drift against seven-plan program |
|---|---|---|---|
| Planned profile resolution | `backend/app/providers/model_profiles/resolver.py::ModelBindingResolver` | Resolves request override → project-or-workspace profile → system registry default and validates registered capability. | Useful planned-preference resolver, but not the sole concrete execution resolver. A project profile with the requested slot absent stops workspace-slot inheritance because the profile object is selected before per-slot fallback. |
| Media selection | `backend/app/providers/selection.py::ModelSelectionService` | Normalizes image/video intent, resolves a `ProviderModelBinding`, evaluates eligibility, and returns `SelectionPlan`. | Independent business model selector. With a profile X whose credentialed binding is absent, `_resolve_binding()` falls back to `ProjectProviderBinding` Y; this violates “explicit X unavailable → fail, request count 0”. |
| Legacy/bridge routing | `backend/app/providers/workspace_router.py` and `backend/app/providers/adapters_v2.py` | Resolves connection/runtime and may call `select_seed_manifest()`; A+B bridge compiles/creates V3 requests. | `select_seed_manifest()` is a first-capable/seed fallback entry. It cannot remain an execution authority on the Professional path. |
| Generation route | `backend/app/providers/generation_service.py`, `backend/app/api/v1/generations.py`, `backend/app/providers/router.py` | Uses `ModelBindingResolver` and `CapabilityRouter` for legacy/general generation APIs. | Must remain compatible, but must not become a second Professional concrete-model decision point. |
| Node profile snapshot | `backend/app/providers/model_profiles/node_snapshot.py` | Best-effort planned model metadata on `NodeRun.input_snapshot`; explicitly catches errors and returns a marker. | Planning-only and non-blocking. It cannot substitute for a fail-closed execution identity decision. |
| Manifest conversion | `ModelCatalogEntry.capability_manifest_json` → `ModelCapabilityManifest` in selection/runtime/compiler paths | Manifest is persisted in catalog and its hash reaches `SelectionPlan` / `ProviderOperation`. | Reusable authority. It still needs to be carried by one typed resolution/snapshot rather than several ad-hoc dictionaries. |
| Runtime resolution | `backend/app/providers/runtime.py::ProviderRuntimeResolver` and `backend/app/execution/product_path.py` | Resolves compiler/runtime from concrete connection, binding, catalog entry, and connection settings; product path calls selection again then runtime resolution. | Good concrete runtime primitive. Professional execution must receive a frozen resolution instead of rediscovering current selection/credential state. |
| Provider connection | `backend/app/providers/models.py::ProviderConnection`, `backend/app/providers/connection_service.py` | Mutable connection row with `credential_id`, integer `credential_revision`, base URL and evidence invalidation. | No immutable `ProviderConnectionRevision`; later base URL / protocol / credential changes can change what a resumed job reads. |
| Credential | `backend/app/security/models.py`, `backend/app/security/credentials.py` | One `UNIQUE(workspace_id, provider)` row. `store_credential()` updates ciphertext/key version in place; `read_credential()` looks up by workspace+provider. | Direct conflict with MS5-IDENTITY-A. Old credentials cannot be recovered by identity and runtime lookup is ambiguous after rotation. |
| Execution record | `backend/app/execution/models.py::ProviderOperation` | Persists connection id, binding id, catalog entry id, manifest hash, selection plan, resume token and actual provider/model. | Strong partial provenance. It lacks `provider_connection_revision_id` / `credential_revision_id` and no normalized immutable `ExecutionIdentitySnapshot` is written consistently to NodeRun and operation. |
| Reference transport | `backend/app/providers/adapters_v2.py`, `backend/app/execution/product_path.py`, normalizer inputs | Some compiler paths use `list[ResolvedReference]`; A+B bridge rebuilds references through `dict[role, ResolvedArtifact]`; selection normalizes reference roles as sets. | Same-role references can collapse and cardinality/order are not represented end-to-end. MS3 is required. |
| Mode semantics | intent/selection `mode` strings and current capability variants | Current plans carry a free-form `mode`, while video capability is derived from first/last/reference inputs. | No reviewed `mode_id` contract, exclusivity validator, frozen mode snapshot or trace-wide mode identity. MS4-LITE remains required. |

## Required behavioral proof versus current evidence

| Review gate | Current evidence | Result |
|---|---|---|
| Profile X → actual model X | Profile snapshot and selection are separate; actual path can resolve a different project binding if X has no credentialed match. | **FAIL / MS1 blocking** |
| X unavailable + Legacy Y exists → fail with zero Provider requests | `ModelSelectionService._resolve_binding()` contains the Y fallback. | **FAIL / MS1 blocking** |
| Project slot absent → workspace slot → system default | `ModelBindingResolver` resolves one chosen profile object, then system default; slot-level inheritance is not guaranteed after selecting a project profile. | **PARTIAL / MS1 blocking** |
| One business execution resolver | `ModelBindingResolver`, `ModelSelectionService`, `CapabilityRouter`, `workspace_router`, GenerationService and product execution all participate. | **FAIL / MS1-R blocking** |
| Concrete binding/catalog/manifest frozen | Selection plan and ProviderOperation persist partial data. | **PARTIAL / MS1-C and MS5-IDENTITY** |
| Connection / credential revision frozen across resume | Connection is mutable; credential storage mutates one row in place and lookup is by provider. | **FAIL / MS5-IDENTITY blocking** |
| Multi-reference count/order preserved | dict/set conversions can collapse role duplicates. | **FAIL / MS3 blocking** |
| Unknown input slot rejects before Provider request | Existing manifest/compiler validation is reusable, but there is no dedicated reviewed strict-slot proof across all Professional execution planning. | **PARTIAL / MS2 blocking** |
| `mode_id` survives plan/snapshot/trace | Current `mode` is not the reviewed contract. | **FAIL / MS4-LITE blocking** |
| Retry/restart retains same identity | Resume token/recovery exists, but credential and connection identity are still current mutable lookups. | **PARTIAL / MS5-IDENTITY blocking** |

## Existing tests that preserve useful behavior

- `backend/tests/unit/test_model_binding_resolver.py` — profile resolver priority/capability behavior;
- `backend/tests/unit/test_model_selection.py` — binding selection and eligibility behavior;
- `backend/tests/unit/test_model_profile_snapshot.py` — planned NodeRun profile snapshot;
- `backend/tests/unit/test_provider_connections.py` — connection/credential service behavior;
- `backend/tests/unit/test_provider_references.py` and `backend/tests/unit/test_v3_adapters_v2.py` — reference/compiler bridge behavior;
- `backend/tests/unit/test_media_provider_polling.py` — operation polling/recovery semantics.

These tests are baseline facts, not proof that MS1–MS5-IDENTITY are done. No old test may be weakened to preserve the profile-X-to-Y fallback.

## Minimal ordered next tasks

1. **MS1-R + MS1-C — one concrete execution resolver and typed result**
   - add `ExecutionModelResolution` as a typed, non-ORM contract;
   - introduce one `ExecutionModelResolver` that enforces request override → project slot → workspace slot → system default at **slot level**;
   - represent `RESOLVED` / `UNAVAILABLE` and stable reasons; formal automatic fallback remains disabled;
   - adapt the Professional execution path to consume this resolution rather than silently reselecting a legacy binding;
   - serialize the resolution into NodeRun snapshot without secret values.
2. **MS2** — strict slot/media/cardinality validation, no Provider request on unknown slot.
3. **MS3** — replace role-keyed reference maps with ordered reference lists.
4. **MS4-LITE** — introduce mode id, exclusivity validation and trace persistence without flattening existing video capabilities.
5. **MS5-R / MS5-IDENTITY A–C** — freeze concrete binding/catalog/runtime plus immutable credential and connection revisions before Phase 4 merge.

## Explicit non-changes for MS1

- no new Generation ORM, AIJob, ProfessionalRuntime or RuntimeV4;
- no Worker/ProductionGraph rewrite;
- no Provider-specific UI branching;
- no automatic fallback, no paid Provider request, and no credential material in snapshot, trace or test output;
- legacy routes remain compatible until Phase 10, but Professional media execution must stop treating them as model-selection authority.
