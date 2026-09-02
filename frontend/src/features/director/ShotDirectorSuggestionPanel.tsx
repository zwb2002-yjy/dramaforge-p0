import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { suggestShotDesign } from "./api";
import type { ShotDirectorSuggestion } from "./suggestion-types";
import type { ShotDesignDraft } from "../shots/ShotDesignPanel";
import type { ShotLite } from "../shots/api";

type ShotDirectorSuggestionPanelProps = {
  projectId: string;
  shot: ShotLite;
  dirty: boolean;
  onApplyDraft: (draft: ShotDesignDraft) => void;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatState(state: Record<string, unknown>): string {
  return JSON.stringify(state, null, 2);
}

/**
 * One-shot Director suggestion surface.
 *
 * A returned suggestion is held only in component state. Apply sends its
 * design fields to ShotDesignPanel's local draft seam; neither this component
 * nor Apply calls /design, execution-plan, or executions.
 */
export function ShotDirectorSuggestionPanel({
  projectId,
  shot,
  dirty,
  onApplyDraft,
}: ShotDirectorSuggestionPanelProps) {
  const [instruction, setInstruction] = useState("");
  const [proposal, setProposal] = useState<ShotDirectorSuggestion | null>(null);
  const [applied, setApplied] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setInstruction("");
    setProposal(null);
    setApplied(false);
    setMessage(null);
  }, [shot.id]);

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
      });
    },
    onSuccess: (result) => {
      setProposal(result);
      setApplied(false);
      setMessage(null);
    },
    onError: (error: unknown) => {
      setProposal(null);
      setMessage(`建议生成失败：${errorMessage(error)}`);
    },
  });

  const stale = proposal !== null && proposal.base_shot_version !== shot.version;
  const canApply = proposal !== null && !dirty && !stale && !applied && !request.isPending;

  function applyProposal() {
    if (!proposal || !canApply) return;
    onApplyDraft({
      image_prompt: proposal.suggested_image_prompt,
      video_prompt: proposal.suggested_video_prompt,
      director_state: proposal.suggested_director_state,
    });
    setApplied(true);
    setMessage("建议已应用到镜头草稿；请点击“保存设计”写入服务器事实。");
  }

  function discardProposal() {
    setProposal(null);
    setApplied(false);
    setMessage("已丢弃建议。");
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
          <strong>针对当前镜头提出一句要求</strong>
        </div>
        <span className="qc-shot-production-version">v{shot.version}</span>
      </header>

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
              disabled={!canApply}
            >
              {applied ? "已应用到草稿" : "应用到镜头草稿"}
            </button>
            <button
              type="button"
              data-testid="discard-shot-director-suggestion"
              onClick={discardProposal}
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
    </section>
  );
}
