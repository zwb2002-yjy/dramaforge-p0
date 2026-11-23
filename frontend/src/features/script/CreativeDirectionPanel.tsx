import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useContext, useState } from "react";

import {
  ApiError,
  artifactVisionPreviewUrl,
  fileVisionPreviewUrl,
  publicVisionPreviewUrl,
} from "../../lib/api";
import { Sparkles, Send } from "lucide-react";
import { StudioSelection } from "../../components/workstation/StudioSelection";
import { ActionLink, Button, Checkbox, Field, Textarea } from "../../components/ui";
import { DeliveryGoals } from "../director/DeliveryGoals";
import { queryKeys } from "../../lib/queryKeys";
import {
  getDirectorAgentRequest,
  openProjectDirectorThread,
  readDirectorAgentThread,
  sendDirectorAgentMessage,
} from "../director/api";
import { fetchCreativeDirection, saveCreativeDirection } from "./api";

type CreativeDirectionPanelProps = {
  projectId: string;
  goal?: string;
};

/**
 * Project creative direction plus a project-scoped Director discussion.
 *
 * The note is user-authored context for the story brief; the discussion reuses
 * the existing agent thread (one per project scope) and only copies an
 * assistant message into the draft when the user explicitly adopts it.
 */
export function CreativeDirectionPanel({ projectId, goal }: CreativeDirectionPanelProps) {
  const studio = useContext(StudioSelection);
  const selection = studio?.attachment;
  const selectedPart = selection?.part;
  const preview = selection ? null : studio?.media;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [edit, setEdit] = useState<{ text: string; baseVersion: number } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const storageKey = `df.project.director.${projectId}`;
  const [threadId, setThreadId] = useState<string | null>(() => sessionStorage.getItem(storageKey));
  const [question, setQuestion] = useState("");
  const [goalsOpen, setGoalsOpen] = useState(false);
  const [createGoal, setCreateGoal] = useState(false);
  const [attachment, setAttachment] = useState<{
    id: string;
    hash: string;
    time: number | null;
  } | null>(null);
  const [loadedPreview, setLoadedPreview] = useState("");
  const attached =
    attachment?.id === preview?.id && attachment?.hash === preview?.contentHash ? attachment : null;
  const previewUrl =
    selectedPart?.kind === "public_asset"
      ? publicVisionPreviewUrl(projectId, selectedPart)
      : selectedPart
        ? fileVisionPreviewUrl(
            projectId,
            selectedPart.file_revision_id,
            selectedPart.source_fragment_id,
            selectedPart.expected_content_hash,
          )
        : attached
          ? artifactVisionPreviewUrl(projectId, attached.id, attached.hash, attached.time)
          : "";
  useEffect(() => {
    setAttachment(null);
    setLoadedPreview("");
  }, [projectId, preview?.id, preview?.contentHash]);
  const attachSelected = () => {
    if (!preview?.contentHash) return;
    const time = preview.video
      ? Math.floor((preview.player.current?.currentTime ?? 0) * 1000)
      : null;
    setLoadedPreview("");
    setAttachment({ id: preview.id, hash: preview.contentHash, time });
  };
  const pendingKey = storageKey + ".pending-request";
  const [pendingRequest, setPendingRequest] = useState<string | null>(() =>
    sessionStorage.getItem(pendingKey),
  );
  const awaitingReply = Boolean(pendingRequest);
  const [submitting, setSubmitting] = useState(false);

  const direction = useQuery({
    queryKey: ["creative-direction", projectId],
    queryFn: () => fetchCreativeDirection(projectId),
    enabled: open,
    retry: false,
  });
  const thread = useQuery({
    queryKey: ["direction-thread", projectId, threadId],
    queryFn: () => readDirectorAgentThread(projectId, threadId!),
    enabled: threadId !== null,
    retry: false,
    refetchInterval: awaitingReply ? 2000 : false,
  });

  const draft = edit?.text ?? direction.data?.direction ?? "";

  function setDirectionDraft(text: string) {
    if (direction.data)
      setEdit({ text, baseVersion: edit?.baseVersion ?? direction.data.profile_version });
  }

  const messages = thread.data?.messages ?? [];
  const receipt = useQuery({
    queryKey: ["project-director-receipt", projectId, threadId, pendingRequest],
    queryFn: ({ signal }) => getDirectorAgentRequest(projectId, threadId!, pendingRequest!, signal),
    enabled: !!threadId && !!pendingRequest && !submitting,
    retry: false,
    refetchInterval: (query) =>
      pendingRequest && query.state.data && !query.state.error ? 1800 : false,
  });
  useEffect(() => {
    const state = receipt.data?.turn.status;
    if (
      pendingRequest &&
      state &&
      ["failed", "cancelled", "completed", "awaiting_user", "stale", "rejected"].includes(state)
    ) {
      if (state === "failed") setError("导演任务未完成，请查看任务回执或检查项目文本模型。");
      if (sessionStorage.getItem(pendingKey) === pendingRequest)
        sessionStorage.removeItem(pendingKey);
      setPendingRequest(null);
      void queryClient.invalidateQueries({ queryKey: ["direction-thread", projectId] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.director.goals(projectId) });
    }
  }, [pendingRequest, pendingKey, receipt.data?.turn.status, projectId, queryClient]);

  const save = useMutation({
    mutationFn: () => {
      if (!edit) throw new Error("没有待保存的修改");
      return saveCreativeDirection(projectId, {
        expected_profile_version: edit.baseVersion,
        direction: edit.text,
      });
    },
    onSuccess: (saved) => {
      setError(null);
      setMessage("创作方向已保存。");
      setEdit(null);
      queryClient.setQueryData(["creative-direction", projectId], saved);
    },
    onError: (cause) => {
      setMessage(null);
      setError(cause instanceof Error ? cause.message : "保存失败");
    },
  });

  const send = useMutation({
    mutationFn: async () => {
      const id = threadId ?? (await openProjectDirectorThread(projectId)).id;
      sessionStorage.setItem(storageKey, id);
      setThreadId(id);
      const requestKey = `direction:${crypto.randomUUID()}`;
      sessionStorage.setItem(pendingKey, requestKey);
      setPendingRequest(requestKey);
      return sendDirectorAgentMessage(projectId, id, {
        content: question.trim(),
        request_key: requestKey,
        intent: goalsOpen && createGoal ? "create_goal" : "conversation",
        ...(selectedPart && { media_parts: [selectedPart] }),
        ...(attached && {
          media_parts: [
            {
              kind: "artifact",
              artifact_id: attached.id,
              expected_content_hash: attached.hash,
              transform: { max_edge: 1024, frame_time_ms: attached.time },
            },
          ],
        }),
        ...(preview && {
          ui_context: {
            selected_refs: [
              { kind: "shot", id: preview.shotId },
              { kind: "artifact", id: preview.id },
            ],
          },
        }),
      });
    },
    onMutate: () => setSubmitting(true),
    onSettled: () => setSubmitting(false),
    onSuccess: () => {
      setCreateGoal(false);
      setQuestion("");
      studio?.showAttachment(null);
      setAttachment(null);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["direction-thread", projectId] });
    },
    onError: (cause) => {
      if (cause instanceof ApiError && cause.details.request_accepted === false) {
        sessionStorage.removeItem(pendingKey);
        setPendingRequest(null);
      }
      setError(cause instanceof Error ? cause.message : "发送失败");
    },
  });

  return (
    <aside
      id="project-chat-rail"
      className="institution-director"
      aria-label="项目导演对话"
      data-testid="creative-direction"
    >
      <header>
        <h2>
          <Sparkles size={20} /> AI 创意助手
        </h2>
        <Button
          tone="ghost"
          aria-expanded={goalsOpen}
          onClick={() => {
            setGoalsOpen(!goalsOpen);
            setCreateGoal(false);
          }}
        >
          持续目标
        </Button>
        <Button tone="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
          创作方向
        </Button>
      </header>
      {goalsOpen && <DeliveryGoals key={projectId} projectId={projectId} />}
      <p className="studio-chat-intro">随时告诉我你的想法，一起修改和完善作品。</p>
      {open && (
        <div className="direction-editor">
          <Field>
            <span>方向说明</span>
            <Textarea
              aria-label="创作方向"
              rows={3}
              value={draft}
              disabled={!direction.data || save.isPending}
              onChange={(event) => setDirectionDraft(event.target.value)}
            />
          </Field>
          {direction.isError && <p role="alert">无法读取方向说明。</p>}
          <Button disabled={!edit || save.isPending || !draft.trim()} onClick={() => save.mutate()}>
            保存创作方向
          </Button>
        </div>
      )}
      {message && <p role="status">{message}</p>}
      <div className="institution-conversation" aria-label="项目对话记录">
        {thread.isError && (
          <p role="alert">
            读取对话失败。<Button onClick={() => void thread.refetch()}>重试</Button>
          </p>
        )}
        {!messages.length && goal && (
          <article data-role="user">
            <strong>项目目标</strong>
            <p>{goal}</p>
          </article>
        )}
        {selection && (
          <article className="studio-context-card">
            <strong>{selection.label}</strong>
            <img
              key={previewUrl}
              src={previewUrl}
              alt={
                selectedPart?.kind === "public_asset"
                  ? "将随消息发送的公共画面"
                  : "将随消息发送的资料片段"
              }
              onLoad={() => setLoadedPreview(previewUrl)}
              onError={() => {
                setLoadedPreview("");
                setError("素材已变更或无法预览，请重新选择。");
              }}
            />
            <Button tone="ghost" onClick={() => studio?.showAttachment(null)}>
              移除附件
            </Button>
          </article>
        )}
        {preview && (
          <article className="studio-context-card">
            <strong>当前讨论的画面</strong>
            {!attached &&
              (preview.video ? (
                <video
                  key={preview.id}
                  controls
                  preload="metadata"
                  src={preview.url}
                  onPlay={(event) => {
                    preview.player.current = event.currentTarget;
                  }}
                  onSeeking={(event) => {
                    preview.player.current = event.currentTarget;
                  }}
                />
              ) : (
                <img src={preview.url} alt="当前选中的画面" />
              ))}
            {attached ? (
              <>
                <img
                  key={previewUrl}
                  src={previewUrl}
                  alt="将随消息发送的画面"
                  onLoad={() => setLoadedPreview(previewUrl)}
                  onError={() => setError("无法准备这张画面，请重新选择。")}
                />
                <Button tone="ghost" onClick={() => setAttachment(null)}>
                  移除附件
                </Button>
              </>
            ) : (
              preview.contentHash && (
                <Button tone="ghost" onClick={attachSelected}>
                  {preview.video ? "附上当前视频帧" : "附上这张图片"}
                </Button>
              )
            )}
          </article>
        )}
        {messages.map((item) => (
          <article key={item.id} data-role={item.role}>
            <strong>{item.role === "assistant" ? "导演" : "你"}</strong>
            <p>{item.content}</p>
            {item.role === "user" &&
              item.media_parts?.map((part, index) => (
                <img
                  key={index}
                  alt="发送给导演的画面"
                  loading="lazy"
                  src={
                    part.kind === "public_asset"
                      ? publicVisionPreviewUrl(projectId, part)
                      : part.kind === "file"
                        ? fileVisionPreviewUrl(
                            projectId,
                            part.file_revision_id,
                            part.source_fragment_id,
                            part.expected_content_hash,
                            part.transform,
                          )
                        : artifactVisionPreviewUrl(
                            projectId,
                            part.artifact_id,
                            part.expected_content_hash,
                            part.transform?.frame_time_ms ?? null,
                            part.transform?.max_edge,
                            part.transform?.crop,
                          )
                  }
                />
              ))}
            {item.context?.selected_refs
              ?.filter((ref) => ref.kind === "artifact")
              .map((ref) => (
                <ActionLink
                  key={ref.id}
                  tone="ghost"
                  to="/projects/$projectId"
                  params={{ projectId }}
                  search={{
                    previewShot: item.context?.selected_refs?.find((r) => r.kind === "shot")?.id,
                    previewArtifact: ref.id,
                  }}
                >
                  查看本条讨论的画面
                </ActionLink>
              ))}
            {item.role === "assistant" && (
              <Button
                tone="ghost"
                onClick={() => {
                  setOpen(true);
                  queryClient
                    .fetchQuery({
                      queryKey: ["creative-direction", projectId],
                      queryFn: () => fetchCreativeDirection(projectId),
                    })
                    .then((row) =>
                      setEdit({ text: item.content, baseVersion: row.profile_version }),
                    )
                    .catch(() => setError("无法读取创作方向"));
                }}
              >
                采用为方向草稿
              </Button>
            )}
          </article>
        ))}
        {awaitingReply && (
          <p role="status">
            {receipt.isError || receipt.data === null
              ? "暂未确认本次消息的处理状态。"
              : "正在等待导演回复…"}
          </p>
        )}
      </div>
      {pendingRequest && !submitting && (receipt.isError || receipt.data === null) && (
        <Button tone="ghost" onClick={() => void receipt.refetch()}>
          重新读取本次回执
        </Button>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="studio-suggestions">
        {["我想修改…", "帮我调整…", "继续优化…"].map((label) => (
          <Button
            tone="ghost"
            key={label}
            onClick={() => {
              setQuestion((value) => value || label.replace("…", ""));
              document.getElementById("project-director-message")?.focus();
            }}
          >
            <Sparkles size={12} />
            {label}
          </Button>
        ))}
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (
            question.trim() &&
            (!previewUrl || loadedPreview === previewUrl) &&
            !send.isPending &&
            !awaitingReply
          )
            send.mutate();
        }}
      >
        <Textarea
          id="project-director-message"
          aria-label="给导演的想法"
          placeholder="请输入你的需求，例如：我想修改画面风格…"
          rows={3}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
        {goalsOpen && (
          <Checkbox checked={createGoal} onChange={(e) => setCreateGoal(e.target.checked)}>
            将本条消息建立为持续目标
          </Checkbox>
        )}
        <Button
          aria-label="发送给导演"
          type="submit"
          tone="primary"
          disabled={
            (!!previewUrl && loadedPreview !== previewUrl) ||
            !question.trim() ||
            send.isPending ||
            awaitingReply
          }
        >
          <Send size={17} />
        </Button>
      </form>
    </aside>
  );
}
