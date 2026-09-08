import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  decideDirectorTurn,
  getDirectorTurn,
  listDirectorTurns,
  recommendShotDesign,
  resumeDirectorTurn,
  stopDirectorTurn,
  suggestShotDesign,
} from "./api";
import { DirectorTurnStatus } from "./DirectorTurnStatus";
import type {
  DirectorInvocationEvidence,
  DirectorRecommendation,
  DirectorTurnRead,
  ShotDirectorSuggestion,
} from "./suggestion-types";
import { queryKeys } from "../../lib/queryKeys";
import type { ShotDesignDraft } from "../shots/ShotDesignPanel";
import type { ShotLite } from "../shots/api";

type ShotDirectorSuggestionPanelProps = {
  projectId: string;
  shot: ShotLite;
  dirty: boolean;
  onApplyDraft: (draft: ShotDesignDraft) => void;
};

const EMPTY_TURNS: DirectorTurnRead[] = [];
const ACTIVE_TURN_STATUSES = new Set(["queued", "thinking", "awaiting_user", "awaiting_execution"]);
const RECOMMENDATION_CATEGORIES = new Set([
  "PERFORMANCE",
  "BLOCKING",
  "SHOT_SIZE",
  "CAMERA_ANGLE",
  "CAMERA_MOTION",
  "PACING",
]);
const RECOMMENDATION_FIELDS = new Set([
  "framing",
  "camera",
  "action",
  "expression",
  "gaze",
  "composition",
  "continuity_constraints",
  "video_reference_risk",
  "performance",
]);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatState(state: Record<string, unknown>): string {
  return JSON.stringify(state, null, 2);
}

function newDirectorRequestKey(kind: "suggestion" | "recommendation", shotId: string): string {
  return `${kind}:${shotId}:${globalThis.crypto.randomUUID()}`;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function evidenceFromTurn(turn: DirectorTurnRead): DirectorInvocationEvidence | null {
  const resolution = turn.model_resolution;
  const slot = resolution.slot;
  const modelId = resolution.model_id;
  const bindingRef = resolution.model_binding_ref;
  if (
    !turn.output_hash ||
    typeof slot !== "string" ||
    typeof modelId !== "string" ||
    typeof bindingRef !== "string"
  ) {
    return null;
  }
  const actualModel = turn.response_summary.actual_model;
  return {
    turn_id: turn.id,
    request_key: turn.request_key,
    context_hash: turn.context_hash,
    output_hash: turn.output_hash,
    slot,
    model_id: modelId,
    model_binding_ref: bindingRef,
    actual_model: typeof actualModel === "string" ? actualModel : null,
    transport_status: "succeeded",
    token_usage: turn.token_usage,
    reported_cost: turn.reported_cost,
    cost_status: turn.cost_status === "reported" ? "reported" : "unknown",
    currency: turn.currency,
    schema_repair_count: turn.schema_repair_count,
  };
}

function suggestionFromTurn(turn: DirectorTurnRead): ShotDirectorSuggestion | null {
  const output = turn.output_snapshot;
  if (
    typeof output.base_shot_version !== "number" ||
    typeof output.suggested_image_prompt !== "string" ||
    typeof output.suggested_video_prompt !== "string" ||
    !objectValue(output.suggested_director_state) ||
    typeof output.change_summary !== "string"
  ) {
    return null;
  }
  return {
    base_shot_version: output.base_shot_version,
    suggested_image_prompt: output.suggested_image_prompt,
    suggested_video_prompt: output.suggested_video_prompt,
    suggested_director_state: objectValue(output.suggested_director_state)!,
    change_summary: output.change_summary,
    director_evidence: evidenceFromTurn(turn),
  };
}

function recommendationFromTurn(turn: DirectorTurnRead): DirectorRecommendation | null {
  const output = turn.output_snapshot;
  if (
    typeof output.base_shot_version !== "number" ||
    output.scope !== "shot" ||
    typeof output.category !== "string" ||
    !RECOMMENDATION_CATEGORIES.has(output.category) ||
    typeof output.current_state !== "string" ||
    typeof output.suggested_change !== "string" ||
    typeof output.reason !== "string" ||
    typeof output.expected_effect !== "string" ||
    typeof output.risk !== "string" ||
    !Array.isArray(output.affected_facts) ||
    !Array.isArray(output.typed_operations)
  ) {
    return null;
  }
  return {
    base_shot_version: output.base_shot_version,
    scope: "shot",
    category: output.category,
    current_state: output.current_state,
    suggested_change: output.suggested_change,
    reason: output.reason,
    expected_effect: output.expected_effect,
    risk: output.risk,
    affected_facts: output.affected_facts.filter(
      (value): value is string => typeof value === "string",
    ),
    typed_operations: output.typed_operations.filter(
      (value): value is DirectorRecommendation["typed_operations"][number] => {
        const operation = objectValue(value);
        return (
          operation?.op === "update_director_state" &&
          typeof operation.field === "string" &&
          RECOMMENDATION_FIELDS.has(operation.field) &&
          typeof operation.value === "object" &&
          operation.value !== null
        );
      },
    ),
    director_evidence: evidenceFromTurn(turn),
  };
}

function decisionFor(turn: DirectorTurnRead): Record<string, unknown> | null {
  return objectValue(turn.response_summary.user_decision);
}

/**
 * One-shot Director suggestion surface.
 *
 * A returned suggestion is held in component state while its invocation
 * evidence is durable on the server. Apply sends only design fields to
 * ShotDesignPanel's local draft seam; neither this component nor Apply calls
 * /design, execution-plan, or executions.
 */
export function ShotDirectorSuggestionPanel({
  projectId,
  shot,
  dirty,
  onApplyDraft,
}: ShotDirectorSuggestionPanelProps) {
  const queryClient = useQueryClient();
  const [instruction, setInstruction] = useState("");
  const [proposal, setProposal] = useState<ShotDirectorSuggestion | null>(null);
  const [applied, setApplied] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState<DirectorRecommendation | null>(null);
  const [selectedOps, setSelectedOps] = useState<Record<number, boolean>>({});
  const [dismissedTurnIds, setDismissedTurnIds] = useState<Set<string>>(() => new Set());

  const turnsKey = queryKeys.director.turns(projectId, "shot", shot.id);
  const turnsQuery = useQuery({
    queryKey: turnsKey,
    queryFn: () => listDirectorTurns(projectId, "shot", shot.id),
    retry: false,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((turn) => ACTIVE_TURN_STATUSES.has(turn.status)) ? 4000 : false,
  });
  const turns = turnsQuery.data ?? EMPTY_TURNS;

  async function refreshTurns() {
    await queryClient.invalidateQueries({ queryKey: turnsKey });
  }

  useEffect(() => {
    setInstruction("");
    setProposal(null);
    setApplied(false);
    setMessage(null);
    setRecommendation(null);
    setSelectedOps({});
    setDismissedTurnIds(new Set());
  }, [shot.id]);

  useEffect(() => {
    const restorable = turns.find(
      (turn) =>
        turn.status === "awaiting_user" &&
        !dismissedTurnIds.has(turn.id) &&
        decisionFor(turn)?.decision !== "reject",
    );
    if (!restorable) return;
    const task = restorable.request_summary.task;
    if (!proposal && task === "shot_director_suggestion") {
      setProposal(suggestionFromTurn(restorable));
      return;
    }
    if (!recommendation && task === "shot_director_recommendation") {
      const restored = recommendationFromTurn(restorable);
      if (restored) {
        setRecommendation(restored);
        const accepted = decisionFor(restorable)?.accepted_operation_indices;
        const selected = Array.isArray(accepted)
          ? accepted.filter((value): value is number => typeof value === "number")
          : restored.typed_operations.map((_operation, index) => index);
        setSelectedOps(Object.fromEntries(selected.map((index) => [index, true])));
      }
    }
  }, [dismissedTurnIds, proposal, recommendation, turns]);

  const request = useMutation({
    mutationFn: () => {
      if (dirty) {
        throw new Error("请先保存或撤销未保存的镜头设计，再请求导演建议。");
      }
      return suggestShotDesign(projectId, shot.id, {
        scene_id: shot.scene_id,
        shot_id: shot.id,
        expected_shot_version: shot.version,
        user_instruction: instruction.trim(),
        request_key: newDirectorRequestKey("suggestion", shot.id),
      });
    },
    onSuccess: (result) => {
      setProposal(result);
      setApplied(false);
      setMessage(null);
      void refreshTurns();
    },
    onError: (error: unknown) => {
      setProposal(null);
      setMessage(`建议生成失败：${errorMessage(error)}`);
    },
  });

  const proposalTurn = turns.find((turn) => turn.id === proposal?.director_evidence?.turn_id);
  const proposalTurnInactive = Boolean(proposalTurn && proposalTurn.status !== "awaiting_user");
  const stale = proposal !== null && proposal.base_shot_version !== shot.version;
  const canApply =
    proposal !== null &&
    !dirty &&
    !stale &&
    !proposalTurnInactive &&
    !applied &&
    !request.isPending;
  const recommendationTurn = turns.find(
    (turn) => turn.id === recommendation?.director_evidence?.turn_id,
  );
  const recommendationTurnInactive = Boolean(
    recommendationTurn && recommendationTurn.status !== "awaiting_user",
  );
  const recStale = recommendation !== null && recommendation.base_shot_version !== shot.version;

  const proactive = useMutation({
    mutationFn: () => {
      if (dirty) {
        throw new Error("请先保存或撤销未保存的镜头设计，再请求导演建议。");
      }
      return recommendShotDesign(projectId, shot.id, {
        scene_id: shot.scene_id,
        shot_id: shot.id,
        expected_shot_version: shot.version,
        request_key: newDirectorRequestKey("recommendation", shot.id),
      });
    },
    onSuccess: (result) => {
      setRecommendation(result);
      setSelectedOps(Object.fromEntries(result.typed_operations.map((_, index) => [index, true])));
      setMessage(null);
      void refreshTurns();
    },
    onError: (error: unknown) => {
      setRecommendation(null);
      setMessage(`主动分析失败：${errorMessage(error)}`);
    },
  });

  async function persistDetachedDecision(
    turnId: string,
    decision: "accept" | "reject",
    acceptedOperationIndices: number[],
  ) {
    const current = await getDirectorTurn(projectId, turnId);
    if (["stale", "cancelled", "failed"].includes(current.status)) {
      throw new Error(`该导演轮次已${current.status}，不能再应用。`);
    }
    return decideDirectorTurn(projectId, turnId, {
      expected_revision: current.revision,
      decision,
      accepted_operation_indices: acceptedOperationIndices,
    });
  }

  const proposalDecision = useMutation({
    mutationFn: ({ decision }: { decision: "accept" | "reject" }) => {
      const turnId = proposal?.director_evidence?.turn_id;
      if (!turnId) throw new Error("该建议没有可恢复的导演轮次，不能记录决定。");
      return persistDetachedDecision(turnId, decision, decision === "accept" ? [0] : []);
    },
    onSuccess: (turn, variables) => {
      setDismissedTurnIds((current) => new Set(current).add(turn.id));
      if (variables.decision === "accept" && proposal) {
        onApplyDraft({
          image_prompt: proposal.suggested_image_prompt,
          video_prompt: proposal.suggested_video_prompt,
          director_state: proposal.suggested_director_state,
        });
        setApplied(true);
        setMessage("采纳决定已保存，建议已应用到镜头草稿；请点击“保存设计”写入服务器事实。");
      } else {
        setProposal(null);
        setApplied(false);
        setMessage("拒绝决定已保存；相同创作上下文不会重新生成这条建议。");
      }
      void refreshTurns();
    },
    onError: (error: unknown) => setMessage(`保存建议决定失败：${errorMessage(error)}`),
  });

  const recommendationDecision = useMutation({
    mutationFn: ({ decision }: { decision: "accept" | "reject" }) => {
      const turnId = recommendation?.director_evidence?.turn_id;
      if (!turnId) throw new Error("该推荐没有可恢复的导演轮次，不能记录决定。");
      const indices = Object.entries(selectedOps)
        .filter(([, selected]) => selected)
        .map(([index]) => Number(index));
      return persistDetachedDecision(turnId, decision, decision === "accept" ? indices : []);
    },
    onSuccess: (turn, variables) => {
      setDismissedTurnIds((current) => new Set(current).add(turn.id));
      if (variables.decision === "accept" && recommendation) {
        const directorState = { ...(shot.director_state ?? {}) };
        recommendation.typed_operations.forEach((operation, index) => {
          if (!selectedOps[index]) return;
          const field = typeof operation.field === "string" ? operation.field : "performance";
          if (typeof operation.value === "object" && operation.value !== null) {
            directorState[field] = operation.value;
          }
        });
        onApplyDraft({
          image_prompt: shot.image_prompt,
          video_prompt: shot.video_prompt,
          director_state: directorState,
        });
        setRecommendation(null);
        setSelectedOps({});
        setMessage("采纳决定已保存，主动推荐已应用到镜头草稿；请点击“保存设计”写入服务器事实。");
      } else {
        setRecommendation(null);
        setSelectedOps({});
        setMessage("拒绝决定已保存；相同创作上下文不会重新推荐。");
      }
      void refreshTurns();
    },
    onError: (error: unknown) => setMessage(`保存推荐决定失败：${errorMessage(error)}`),
  });

  const turnControl = useMutation({
    mutationFn: async ({
      turn,
      action,
    }: {
      turn: DirectorTurnRead;
      action: "stop" | "resume";
    }): Promise<void> => {
      if (action === "stop") {
        await stopDirectorTurn(projectId, turn.id, turn.revision);
      } else {
        await resumeDirectorTurn(
          projectId,
          turn.id,
          turn.revision,
          `ui-resume:${turn.id}:${globalThis.crypto.randomUUID()}`,
        );
      }
    },
    onSuccess: () => void refreshTurns(),
    onError: (error: unknown) => setMessage(`导演状态更新失败：${errorMessage(error)}`),
  });

  function applySelectedRecommendation() {
    if (!recommendation || dirty || recStale) return;
    recommendationDecision.mutate({ decision: "accept" });
  }

  function applyProposal() {
    if (!proposal || !canApply) return;
    proposalDecision.mutate({ decision: "accept" });
  }

  function discardProposal() {
    proposalDecision.mutate({ decision: "reject" });
  }

  return (
    <section
      className="qc-shot-director-suggestion"
      data-testid="shot-director-suggestion-panel"
      data-shot-id={shot.id}
    >
      <header>
        <div>
          <span className="director-stage-kicker">Director suggestion</span>
          <strong>导演分析与建议</strong>
        </div>
        <span className="qc-shot-production-version">v{shot.version}</span>
      </header>

      <DirectorTurnStatus
        turns={turns}
        loading={turnsQuery.isLoading}
        syncError={turnsQuery.isError ? errorMessage(turnsQuery.error) : null}
        busyTurnId={turnControl.isPending ? (turnControl.variables?.turn.id ?? null) : null}
        onStop={(turn) => turnControl.mutate({ turn, action: "stop" })}
        onResume={(turn) => turnControl.mutate({ turn, action: "resume" })}
      />

      <button
        type="button"
        data-testid="request-proactive-director-recommendation"
        onClick={() => proactive.mutate()}
        disabled={proactive.isPending || dirty}
      >
        {proactive.isPending ? "正在主动分析…" : "主动分析当前镜头"}
      </button>

      <label>
        导演要求
        <textarea
          aria-label="导演要求"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="例如：让人物更克制，镜头缓慢推进"
          disabled={request.isPending}
        />
      </label>
      <button
        type="button"
        data-testid="request-shot-director-suggestion"
        onClick={() => request.mutate()}
        disabled={request.isPending || dirty || !instruction.trim()}
      >
        {request.isPending ? "正在生成建议…" : "生成镜头建议"}
      </button>

      {dirty && (
        <p
          className="qc-shot-director-suggestion-hint"
          data-testid="suggestion-dirty-guard"
          role="status"
        >
          请先保存或撤销未保存的镜头设计，再请求导演建议。
        </p>
      )}

      {proposal && (
        <article
          className="qc-shot-director-suggestion-proposal"
          data-testid="shot-director-suggestion-proposal"
          data-base-shot-version={proposal.base_shot_version}
        >
          <header>
            <strong>提案预览 · 基于 Shot v{proposal.base_shot_version}</strong>
            {stale && <span className="qc-shot-director-suggestion-stale">已过期</span>}
          </header>
          <p data-testid="suggestion-change-summary">{proposal.change_summary}</p>
          {proposal.director_evidence && (
            <p className="muted" data-testid="suggestion-model-evidence">
              模型 {proposal.director_evidence.actual_model ?? proposal.director_evidence.model_id}{" "}
              · 调用 {proposal.director_evidence.turn_id.slice(0, 8)} ·
              {proposal.director_evidence.cost_status === "reported"
                ? ` ${proposal.director_evidence.reported_cost} ${proposal.director_evidence.currency}`
                : " 费用未返回"}
            </p>
          )}

          <div className="qc-shot-director-suggestion-diff" data-testid="suggestion-diff">
            <section>
              <h4>图片提示词</h4>
              <div>
                <span>旧</span>
                <pre data-testid="suggestion-old-image-prompt">{shot.image_prompt || "（空）"}</pre>
              </div>
              <div>
                <span>新</span>
                <pre data-testid="suggestion-new-image-prompt">
                  {proposal.suggested_image_prompt || "（空）"}
                </pre>
              </div>
            </section>
            <section>
              <h4>视频提示词</h4>
              <div>
                <span>旧</span>
                <pre data-testid="suggestion-old-video-prompt">{shot.video_prompt || "（空）"}</pre>
              </div>
              <div>
                <span>新</span>
                <pre data-testid="suggestion-new-video-prompt">
                  {proposal.suggested_video_prompt || "（空）"}
                </pre>
              </div>
            </section>
            <section>
              <h4>导演状态</h4>
              <div>
                <span>旧</span>
                <pre data-testid="suggestion-old-director-state">
                  {formatState(shot.director_state)}
                </pre>
              </div>
              <div>
                <span>新</span>
                <pre data-testid="suggestion-new-director-state">
                  {formatState(proposal.suggested_director_state)}
                </pre>
              </div>
            </section>
          </div>

          {stale && (
            <p
              className="qc-shot-director-suggestion-hint"
              data-testid="suggestion-stale-guard"
              role="alert"
            >
              当前镜头版本已变化，不能应用这条旧建议；请重新生成。
            </p>
          )}
          {proposalTurnInactive && !stale ? (
            <p className="qc-shot-director-suggestion-hint" role="alert">
              该导演轮次已变为 {proposalTurn?.status}，当前预览不能再应用。
            </p>
          ) : null}
          {dirty && !stale && (
            <p
              className="qc-shot-director-suggestion-hint"
              data-testid="suggestion-apply-dirty-guard"
              role="status"
            >
              当前镜头有未保存修改；请先保存或撤销后再应用建议。
            </p>
          )}
          <div className="qc-shot-director-suggestion-actions">
            <button
              type="button"
              data-testid="apply-shot-director-suggestion"
              onClick={applyProposal}
              disabled={!canApply || proposalDecision.isPending}
            >
              {applied ? "已应用到草稿" : "应用到镜头草稿"}
            </button>
            <button
              type="button"
              data-testid="discard-shot-director-suggestion"
              onClick={discardProposal}
              disabled={proposalDecision.isPending || stale || proposalTurnInactive || applied}
            >
              丢弃建议
            </button>
          </div>
        </article>
      )}

      {message && (
        <p
          className={
            message.startsWith("建议生成失败")
              ? "qc-shot-director-suggestion-error"
              : "qc-shot-director-suggestion-message"
          }
          role={message.startsWith("建议生成失败") ? "alert" : "status"}
        >
          {message}
        </p>
      )}
      <p className="qc-shot-director-suggestion-footer">
        建议只生成预览，不会自动保存、采纳或生产。
      </p>

      {recommendation && (
        <article
          className="qc-shot-director-suggestion-proposal"
          data-testid="director-recommendation-preview"
          data-base-shot-version={recommendation.base_shot_version}
        >
          <header>
            <strong>
              {recommendation.category} · 基于 Shot v{recommendation.base_shot_version}
            </strong>
            {recStale && <span className="qc-shot-director-suggestion-stale">已过期</span>}
          </header>
          <p>{recommendation.current_state}</p>
          {recommendation.director_evidence && (
            <p className="muted" data-testid="recommendation-model-evidence">
              模型
              {recommendation.director_evidence.actual_model ??
                recommendation.director_evidence.model_id}
              · 调用 {recommendation.director_evidence.turn_id.slice(0, 8)}
            </p>
          )}
          <p>
            <strong>建议：</strong>
            {recommendation.suggested_change}
          </p>
          <p className="muted">{recommendation.reason}</p>
          <p className="muted">预期：{recommendation.expected_effect}</p>
          <p className="muted">风险：{recommendation.risk}</p>
          <div data-testid="recommendation-affected-facts">
            {recommendation.affected_facts.map((fact) => (
              <code key={fact}>{fact}</code>
            ))}
          </div>
          {recommendation.typed_operations.map((operation, index) => (
            <label key={`${operation.op}-${index}`} className="qc-recommendation-operation-row">
              <input
                type="checkbox"
                data-testid={`recommendation-operation-${index}`}
                checked={Boolean(selectedOps[index])}
                onChange={(event) =>
                  setSelectedOps((current) => ({
                    ...current,
                    [index]: event.target.checked,
                  }))
                }
              />
              <code>{operation.op}</code>
              {typeof operation.field === "string" ? <span>{operation.field}</span> : null}
            </label>
          ))}
          {recStale && (
            <p className="qc-shot-director-suggestion-hint" role="alert">
              当前镜头版本已变化，不能应用这条旧推荐；请重新主动分析。
            </p>
          )}
          {recommendationTurnInactive && !recStale ? (
            <p className="qc-shot-director-suggestion-hint" role="alert">
              该导演轮次已变为 {recommendationTurn?.status}，当前推荐不能再应用。
            </p>
          ) : null}
          <div className="qc-shot-director-suggestion-actions">
            <button
              type="button"
              data-testid="apply-director-recommendation"
              disabled={
                dirty ||
                recStale ||
                recommendationTurnInactive ||
                proactive.isPending ||
                recommendationDecision.isPending ||
                !Object.values(selectedOps).some(Boolean)
              }
              onClick={applySelectedRecommendation}
            >
              采用已选推荐
            </button>
            <button
              type="button"
              data-testid="discard-director-recommendation"
              disabled={recommendationDecision.isPending || recStale || recommendationTurnInactive}
              onClick={() => recommendationDecision.mutate({ decision: "reject" })}
            >
              拒绝推荐
            </button>
          </div>
        </article>
      )}
    </section>
  );
}
