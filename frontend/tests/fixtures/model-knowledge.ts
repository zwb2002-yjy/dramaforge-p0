import type { ProviderPluginModelRead, ProviderPluginRead } from "../../src/lib/api";
import type {
  KnowledgeBound,
  KnowledgeParameter,
  ModelKnowledge,
} from "../../src/components/provider/modelKnowledge";

export function fixtureParameter(changes: Partial<KnowledgeParameter> = {}): KnowledgeParameter {
  return {
    type: "string",
    claim_status: "documented_supported",
    control: "native",
    required: false,
    enum: [],
    default_status: "unknown",
    ...changes,
  };
}

export const unknownBound: KnowledgeBound = {
  kind: "unknown",
  claim_status: "unknown",
  inclusive: true,
};
const bound = (value: number): KnowledgeBound => ({
  kind: "bounded",
  value,
  claim_status: "documented_supported",
  inclusive: true,
});

export const fixtureKnowledge: ModelKnowledge = {
  schema_version: "2",
  model_revision: "knowledge-fixture-r1",
  manifest_hash: "a".repeat(64),
  lifecycle: "preview",
  implementation_status: "not_implemented",
  product_open: false,
  account_status: "not_checked",
  blockers: ["MODEL_CONTRACT_NOT_TESTED"],
  official_supported_fields: 4,
  unknown_bounds: 1,
  claim_counts: { documented_supported: 4, unknown: 1, conflicting: 1 },
  fields: [
    {
      path: "/operations/video.generate/output_options/seed",
      claim_status: "conflicting",
      source_snapshot_ref: "fixture-source",
      evidence_resolution: "inherited",
      blocker: "CLAIM_CONFLICTING",
    },
    {
      path: "/operations/video.generate/input_contracts/reference/input_slots/reference_audio/maximum",
      claim_status: "unknown",
      source_snapshot_ref: "fixture-source",
      evidence_resolution: "inherited",
      blocker: "CLAIM_UNKNOWN",
    },
  ],
  sources: [
    {
      url: "https://example.invalid/model-doc",
      checked_at: "2026-10-13",
      status: "source_snapshot_reviewed",
      source_snapshot_ref: "fixture-source",
    },
  ],
  operations: {
    "video.generate": {
      operation: "video.generate",
      claim_status: "documented_supported",
      prompt_spec: fixtureParameter({
        required: true,
        min_length: bound(1),
        max_length: unknownBound,
      }),
      input_contracts: {
        reference: {
          claim_status: "documented_supported",
          minimum_total_references: bound(1),
          maximum_total_references: unknownBound,
          constraints: [],
          input_slots: {
            reference_audio: {
              claim_status: "documented_supported",
              required: false,
              minimum: bound(0),
              maximum: unknownBound,
              media_types: ["audio/wav"],
              codecs: [],
              aspect_ratios: [],
              ordering: "preserve",
              delivery_formats: [],
              max_bytes: { ...bound(15000000), inclusive: false },
              min_duration_seconds: bound(2),
              max_duration_seconds: bound(15),
            },
          },
          max_total_duration_seconds: { reference_audio: bound(15) },
        },
      },
      output_options: {
        resolution: fixtureParameter({ enum: ["480p", "720p"] }),
        seed: fixtureParameter({
          type: "integer",
          claim_status: "conflicting",
          control: "unknown",
        }),
        draft: fixtureParameter({ type: "boolean" }),
      },
      constraints: [
        {
          kind: "conditional",
          claim_status: "documented_supported",
          when: { draft: true },
          when_present: [],
          require: [],
          forbid: [],
          allowed: { resolution: ["480p"] },
          description: "",
          sum_fields: [],
        },
      ],
    },
    "video.extend": {
      operation: "video.extend",
      claim_status: "documented_supported",
      input_contracts: {},
      output_options: {},
      constraints: [],
    },
  },
};

export const fixtureKnowledgeModel: ProviderPluginModelRead = {
  catalog_entry_id: "catalog-knowledge",
  capability_manifest_hash: "b".repeat(64),
  model_id: "fixture-video-v2",
  display_name: "Fixture Video",
  media_type: "video",
  model_revision: "v2",
  lifecycle: "active",
  catalog_source: "official_static",
  implementation_status: "contract_tested",
  capabilities: ["video.generate"],
  option_schema: {},
  knowledge: fixtureKnowledge,
  new_create_blocker: "MODEL_OFFICIAL_EVIDENCE_GAP",
  capability_summary: {
    media_kind: "video",
    accepts_text_only: true,
    product_text_only: false,
    accepts: { reference_audio: true },
    product_open: { reference_audio: false },
    limits: {},
  },
};

export const fixtureKnowledgePlugin: ProviderPluginRead = {
  provider_type: "fixture",
  protocol_profile: "fixture_v1",
  display_name: "Fixture Provider",
  default_base_url: "https://example.invalid",
  model_list_path: "/models",
  kind: "media",
  implemented: true,
  capabilities: ["auth_models"],
  paid_capabilities: ["video_create"],
  models: [fixtureKnowledgeModel],
};
