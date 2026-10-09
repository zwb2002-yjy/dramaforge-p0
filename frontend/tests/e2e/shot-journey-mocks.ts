import { createHash } from "node:crypto";
import { expect, type Page } from "@playwright/test";

import {
  installProfessionalMock,
  PROJECT_ID,
  SCENE_ID,
  SHOT_ID,
  SECOND_SHOT_ID,
} from "./professional-mocks";

export const JOURNEY_SHOT_IDS = [SHOT_ID, SECOND_SHOT_ID, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"];

type Candidate = {
  artifact_id: string;
  node_run_id: string;
  node_key: string;
  stage: string;
  status: string;
  artifact_type: string;
  mime_type: string;
  review_allowed: boolean;
  review_decision: string | null;
  review_node_run_id: string | null;
  review_artifact_id: string | null;
};

export async function installShotJourneyMock(page: Page) {
  await installProfessionalMock(page);
  const shots = JOURNEY_SHOT_IDS.map((id, index) => ({
    id,
    project_id: PROJECT_ID,
    scene_id: SCENE_ID,
    shot_number: index + 1,
    sort_order: index + 1,
    version: 1,
    shot_type: "wide",
    camera_move: "static",
    status: "draft",
    visual_description: `镜头 ${index + 1} 原始画面`,
    dialogue: "",
    duration_seconds: "5",
    image_prompt: `frame ${index + 1}`,
    video_prompt: `motion ${index + 1}`,
    director_state: {},
    formal_keyframe_artifact_id: null as string | null,
    formal_video_artifact_id: null as string | null,
    formal_composite_artifact_id: null,
  }));
  const candidates = Object.fromEntries(shots.map((shot) => [shot.id, [] as Candidate[]]));
  const requests: Array<{
    method: string;
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }> = [];
  const plans = new Map<
    string,
    { shotId: string; version: number; stage: string; prompt: string; firstFrame: string | null }
  >();
  const receipts = new Map<string, Record<string, unknown>>();
  const state = { shots, candidates, requests, plans, failNextFormal: false, failNextSave: false };
  const base = `/api/v1/projects/${PROJECT_ID}`;

  // Override only the journey endpoints. Ancillary reads reuse the existing fixture;
  // unknown writes to these Shots fail instead of silently succeeding in that fixture.
  await page.route(
    (url) => url.pathname.startsWith(base),
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const method = request.method();
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      const json = (value: unknown, status = 200) => route.fulfill({ json: value, status });
      const scene = {
        id: SCENE_ID,
        episode_id: "episode-1",
        episode_number: 1,
        scene_number: 1,
        location_name: "三镜头创作验收",
        time_of_day: "day",
        synopsis: "",
        version: 1,
        design_state: {},
      };
      const overview = Object.fromEntries(
        shots.map((shot) => [
          shot.id,
          {
            pending_review: candidates[shot.id].some(
              (candidate) =>
                candidate.artifact_id !== shot.formal_keyframe_artifact_id &&
                candidate.artifact_id !== shot.formal_video_artifact_id &&
                !candidate.review_allowed &&
                candidate.review_decision !== "rejected",
            ),
            generating: false,
            generation_failed: false,
            outcome_unknown: false,
          },
        ]),
      );
      if (path === `${base}/scenes` && method === "GET") {
        return json([
          {
            ...scene,
            project_id: PROJECT_ID,
            shot_count: 3,
            formal_keyframe_count: shots.filter((shot) => shot.formal_keyframe_artifact_id).length,
            formal_video_count: shots.filter((shot) => shot.formal_video_artifact_id).length,
            risk_count: 0,
            pending_review_count: Object.values(overview).filter((facts) => facts.pending_review)
              .length,
            generating_count: 0,
            failed_count: 0,
            unknown_count: 0,
            representative_artifact: null,
          },
        ]);
      }
      if (path === `${base}/scenes/${SCENE_ID}/workspace` && method === "GET") {
        return json({ scene, shots, references: {}, candidates, trace: {}, overview });
      }
      if (path === `${base}/shots` && method === "GET") return json(shots);
      const match = path.match(/\/shots\/([^/]+)\/(.+)$/);
      const shot = shots.find((item) => item.id === match?.[1]);
      if (!shot) return route.fallback();
      const action = match?.[2];
      const rows = candidates[shot.id];
      if (method !== "GET")
        requests.push({ method, path, body, key: request.headers()["idempotency-key"] });
      if (action === "workbench" && method === "GET") {
        return json({
          shot,
          references: [],
          candidates: rows,
          trace: [],
          old_version_warnings: [],
        });
      }
      if ((action === "canvas" || action === "design") && method === "PATCH") {
        if (state.failNextSave) {
          state.failNextSave = false;
          const expectedVersion = shot.version;
          shot.version += 1;
          return json(
            {
              code: "CONFLICT",
              detail: "镜头保存版本冲突",
              details: { expected_version: expectedVersion, actual_version: shot.version },
            },
            409,
          );
        }
        expect(body.expected_version).toBe(shot.version);
        const { expected_version: _version, ...fields } = body;
        void _version;
        Object.assign(shot, fields);
        shot.version += 1;
        return json(
          action === "canvas"
            ? { shot, revision: { id: `canvas-${shot.id}-${shot.version}` } }
            : shot,
        );
      }
      if (action === "execution-plan" && method === "POST") {
        expect(body.expected_shot_version).toBe(shot.version);
        const stage = String(body.stage);
        if (stage === "video") expect(shot.formal_keyframe_artifact_id).not.toBeNull();
        const frozen = {
          shotId: shot.id,
          version: shot.version,
          stage,
          prompt: stage === "video" ? shot.video_prompt : shot.image_prompt,
          firstFrame: stage === "video" ? shot.formal_keyframe_artifact_id : null,
        };
        const fingerprint = createHash("sha256").update(JSON.stringify(frozen)).digest("hex");
        plans.set(fingerprint, frozen);
        return json({
          plan_fingerprint: fingerprint,
          plan: {
            project_id: PROJECT_ID,
            shot_id: shot.id,
            stage,
            prompt: frozen.prompt,
            mode_id: body.mode_id,
            expected_shot_version: shot.version,
            resolved_model: {
              resolved_model_id: "provider/model-b",
              provider_model_binding_id: "77777777-7777-4777-8777-777777777777",
              status: "RESOLVED",
            },
            planned_references: [],
            capability_gaps: [],
            accepted_approximations: [],
          },
        });
      }
      if (action === "executions" && method === "POST") {
        const frozen = plans.get(String(body.plan_fingerprint));
        expect(frozen).toMatchObject({ shotId: shot.id, version: shot.version, stage: body.stage });
        expect(body.expected_shot_version).toBe(shot.version);
        expect(request.headers()["idempotency-key"]).toBeTruthy();
        if (body.stage === "video")
          expect(frozen?.firstFrame).toBe(shot.formal_keyframe_artifact_id);
        const artifactId = `journey-${shot.shot_number}-${body.stage}`;
        rows.push({
          artifact_id: artifactId,
          node_run_id: `run-${artifactId}`,
          node_key: body.stage === "video" ? "video" : "keyframe",
          stage: String(body.stage),
          status: "completed",
          artifact_type: body.stage === "video" ? "video" : "image",
          mime_type: body.stage === "video" ? "video/mp4" : "image/png",
          review_allowed: false,
          review_decision: null,
          review_node_run_id: null,
          review_artifact_id: null,
        });
        const receipt = {
          node_run_id: `run-${artifactId}`,
          graph_id: "graph-1",
          graph_version_id: "graph-version-1",
          status: "completed",
          plan_fingerprint: body.plan_fingerprint,
        };
        receipts.set(request.headers()["idempotency-key"], receipt);
        return json(receipt);
      }
      if (action === "executions/receipt" && method === "GET") {
        const receipt = receipts.get(url.searchParams.get("idempotency_key") ?? "");
        return receipt ? json(receipt) : json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      if (action === "review-summary" && method === "GET") {
        const candidate = rows.find(
          (item) => item.artifact_id === url.searchParams.get("artifact_id"),
        );
        expect(candidate).toBeDefined();
        return json({
          shot_id: shot.id,
          shot_version: shot.version,
          artifact_id: candidate?.artifact_id,
          review_kind: url.searchParams.get("review_kind"),
          node_key: "identity_review",
          review_node_run_id: candidate?.review_node_run_id,
          review_artifact_id: candidate?.review_artifact_id,
          machine_status: candidate?.review_node_run_id ? "needs_human" : null,
          decision: candidate?.review_decision,
          decision_reason: null,
          applies: candidate?.review_allowed,
          blocked_reason: candidate?.review_allowed ? null : "REVIEW_AWAITING_HUMAN",
          allowed_actions: ["approve", "reject"],
        });
      }
      if (action === "review-evidence" && method === "POST") {
        const candidate = rows.find((item) => item.artifact_id === body.artifact_id);
        expect(candidate).toBeDefined();
        if (candidate) {
          candidate.review_node_run_id = `review-run-${candidate.artifact_id}`;
          candidate.review_artifact_id = `review-${candidate.artifact_id}`;
        }
        return json({ node_run_id: candidate?.review_node_run_id, status: "completed" });
      }
      if (action === "review-decisions" && method === "POST") {
        const candidate = rows.find((item) => item.artifact_id === body.artifact_id);
        expect(candidate?.review_node_run_id).toBe(body.review_node_run_id);
        expect(body.expected_shot_version).toBe(shot.version);
        expect(body.reason).toBeTruthy();
        expect(request.headers()["idempotency-key"]).toBeTruthy();
        if (candidate) {
          candidate.review_decision = String(body.decision);
          candidate.review_allowed = body.decision === "approved";
        }
        return json(
          {
            id: `decision-${candidate?.artifact_id}`,
            ...body,
            shot_id: shot.id,
            shot_version_at_decision: shot.version,
          },
          201,
        );
      }
      if ((action === "formal-keyframe" || action === "formal-video") && method === "POST") {
        const candidate = rows.find((item) => item.artifact_id === body.artifact_id);
        expect(candidate?.review_allowed).toBe(true);
        expect(body.expected_shot_version).toBe(shot.version);
        if (state.failNextFormal) {
          state.failNextFormal = false;
          shot.version += 1;
          return json({ code: "CONFLICT", detail: "正式选择版本冲突" }, 409);
        }
        if (action === "formal-keyframe")
          shot.formal_keyframe_artifact_id = String(body.artifact_id);
        else shot.formal_video_artifact_id = String(body.artifact_id);
        shot.version += 1;
        return json({
          shot_id: shot.id,
          version: shot.version,
          ...(action === "formal-video"
            ? { formal_video_artifact_id: shot.formal_video_artifact_id }
            : { formal_keyframe_artifact_id: shot.formal_keyframe_artifact_id }),
        });
      }
      if (method !== "GET" && action !== "references/resolve")
        return json({ detail: `Unexpected journey write: ${action}` }, 400);
      return route.fallback();
    },
  );
  return state;
}
