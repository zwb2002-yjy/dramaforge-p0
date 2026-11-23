import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useContext, useRef, useState } from "react";

import {
  ApiError,
  artifactVisionPreviewUrl,
  fileVisionPreviewUrl,
  publicVisionPreviewUrl,
} from "../../lib/api";
import { Sparkles, Send } from "lucide-react";
import { StudioSelection } from "../../components/workstation/StudioSelection";
import { ActionLink, Button, Checkbox, ExternalLink, Field, Textarea } from "../../components/ui";
import { ContentFields } from "../research/ResearchContent";
import { DeliveryGoals } from "../director/DeliveryGoals";
import { queryKeys } from "../../lib/queryKeys";
import {
  findProjectDirectorThread,
  getDirectorAgentRequest,
  getDirectorTurn,
  openProjectDirectorThread,
  readDirectorAgentThread,
  sendDirectorAgentMessage,
} from "../director/api";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
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
  const selectedPart = selection && "part" in selection ? selection.part : null;
  const research = selection && "research_ref" in selection ? selection : null;
  const preview = selection ? null : studio?.media;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [edit, setEdit] = useState<{ text: string; baseVersion: number } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const storageKey = `df.project.director.${projectId}`;
  const [openedThread, setOpenedThread] = useState<string | null>(null);
  const discovery = useQuery({
    queryKey: ["project-director-thread", projectId],
    queryFn: ({ signal }) => findProjectDirectorThread(projectId, signal),
    retry: false,
  });
  const existingThread =
    discovery.data?.scope_type === "project" && discovery.data.scope_entity_id === projectId
      ? discovery.data.id
      : null;
  const threadId = existingThread ?? openedThread;
  const userId = queryClient.getQueryData<{ id: string }>(queryKeys.auth.currentUser())?.id;
  const workspaceId = getSelectedWorkspaceId();
  const draftKey = userId && workspaceId ? `${storageKey}.${userId}.${workspaceId}.draft` : null;
  const [question, setQuestion] = useState(() =>
    draftKey ? (sessionStorage.getItem(draftKey) ?? "") : "",
  );
  useEffect(() => {
    if (!draftKey) return;
    if (question) sessionStorage.setItem(draftKey, question);
    else sessionStorage.removeItem(draftKey);
  }, [draftKey, question]);
  const lastSuggestedQuestion = useRef<string | null>(null);
  useEffect(() => {
    if (!research) return;
    const prior = lastSuggestedQuestion.current;
    setQuestion((value) => (!value.trim() || value === prior ? research.prompt : value));
    lastSuggestedQuestion.current = research.prompt;
  }, [research]);
  const submitLock = useRef(false);
  const sentText = useRef<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const transcript = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const [modelSetup, setModelSetup] = useState(false);
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
    refetchInterval: pendingRequest ? 2000 : false,
  });

  const draft = edit?.text ?? direction.data?.direction ?? "";

  function setDirectionDraft(text: string) {
    if (direction.data)
      setEdit({ text, baseVersion: edit?.baseVersion ?? direction.data.profile_version });
  }

  const messages = thread.data?.messages ?? [];
  const last = messages.at(-1);
  const lastMessageId = last?.id;
  const lastTurnId = last?.role === "user" ? last.turn_id : null;
  const previous = useQuery({
    queryKey: ["project-conversation-last-turn", projectId, threadId, lastTurnId],
    queryFn: () => getDirectorTurn(projectId, lastTurnId!),
    enabled: !!lastTurnId && !pendingRequest,
    retry: false,
    refetchInterval: (q) =>
      q.state.data && ["queued", "thinking", "awaiting_execution"].includes(q.state.data.status)
        ? 1800
        : false,
  });
  const observed = previous.data?.thread_id === threadId ? previous.data : null;
  const awaitingReply = Boolean(
    pendingRequest ||
    (observed && ["queued", "thinking", "awaiting_execution"].includes(observed.status)),
  );
  useEffect(() => {
    if (observed && ["completed", "awaiting_user"].includes(observed.status)) {
      void queryClient.invalidateQueries({ queryKey: ["direction-thread", projectId] });
    }
  }, [observed, projectId, queryClient]);
  useEffect(() => {
    const list = transcript.current;
    if (list && followLatest.current) list.scrollTop = list.scrollHeight;
  }, [lastMessageId, awaitingReply]);
  const receipt = useQuery({
    queryKey: ["project-director-receipt", projectId, threadId, pendingRequest],
    queryFn: ({ signal }) => getDirectorAgentRequest(projectId, threadId!, pendingRequest!, signal),
    enabled: !!threadId && !!pendingRequest && !submitting,
    retry: false,
    refetchInterval: (query) => (pendingRequest && !query.state.error ? 1800 : false),
  });
  useEffect(() => {
    const state = receipt.data?.turn.status;
    if (
      pendingRequest &&
      state &&
      ["failed", "cancelled", "completed", "awaiting_user", "stale", "rejected"].includes(state)
    ) {
      if (receipt.data?.turn.transport_status === "unknown_submission") {
        setError("模型提交结果未知。请核对原任务的回执后再决定下一步。");
      } else if (state === "completed" || state === "awaiting_user") {
        const original =
          sentText.current ??
          thread.data?.messages.find(
            (item) => item.id === receipt.data?.acceptance?.user_message_id,
          )?.content;
        if (original) setQuestion((current) => (current.trim() === original.trim() ? "" : current));
      } else if (state === "failed") {
        setError(`导演未能完成本轮：${receipt.data?.turn.stop_reason || "请检查文本模型连接"}。`);
      } else if (state === "stale" || state === "cancelled" || state === "rejected") {
        setError(
          state === "stale"
            ? "本轮依据已变化，请重新选择讨论内容。"
            : "本轮已结束，未产生新的回复。",
        );
      }
      sentText.current = null;
      if (sessionStorage.getItem(pendingKey) === pendingRequest)
        sessionStorage.removeItem(pendingKey);
      setPendingRequest(null);
      void queryClient.invalidateQueries({ queryKey: ["direction-thread", projectId] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.director.goals(projectId) });
    }
  }, [pendingRequest, pendingKey, receipt.data, thread.data, projectId, queryClient]);

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
    retry: false,
    mutationFn: async ({ content, reuseKey }: { content: string; reuseKey?: string }) => {
      const opened = threadId ? null : await openProjectDirectorThread(projectId);
      if (opened && (opened.scope_type !== "project" || opened.scope_entity_id !== projectId))
        throw new Error("无法核对当前项目会话，请重新打开项目。");
      if (!mounted.current) throw new Error("已离开当前项目。");
      const id = opened?.id ?? threadId!;
      setOpenedThread(id);
      if (opened) queryClient.setQueryData(["project-director-thread", projectId], opened);
      // getRandomValues is available on LAN HTTP as well as HTTPS.
      const requestKey =
        reuseKey ??
        `direction:${Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
          b.toString(16).padStart(2, "0"),
        ).join("")}`;
      sentText.current = content;
      sessionStorage.setItem(pendingKey, requestKey);
      setPendingRequest(requestKey);
      return sendDirectorAgentMessage(projectId, id, {
        content: content.trim(),
        request_key: requestKey,
        intent: !research && goalsOpen && createGoal ? "create_goal" : "conversation",
        ...(research && { research_ref: research.research_ref }),
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
    onSettled: () => {
      submitLock.current = false;
      setSubmitting(false);
    },
    onSuccess: () => {
      setCreateGoal(false);
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
      const code = cause instanceof ApiError ? String(cause.details.code ?? cause.code) : "";
      const needsModel = /MODEL_PROFILE|MODEL_UNAVAILABLE|TOOLS_UNAVAILABLE|MODEL_BINDING/.test(
        code,
      );
      setModelSetup(needsModel);
      setError(
        needsModel
          ? "当前项目没有可用的导演文本模型。请选择支持工具对话的文本连接，再发送这条消息。"
          : cause instanceof Error
            ? cause.message
            : "发送失败",
      );
    },
  });

  function submitMessage(reuseKey?: string) {
    if (
      submitLock.current ||
      !question.trim() ||
      (previewUrl && loadedPreview !== previewUrl) ||
      (awaitingReply && (!reuseKey || reuseKey !== pendingRequest))
    )
      return;
    submitLock.current = true;
    followLatest.current = true;
    setModelSetup(false);
    setError(null);
    send.mutate({ content: question, reuseKey });
  }

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
      <div
        className="institution-conversation"
        aria-label="项目对话记录"
        ref={transcript}
        onScroll={(event) => {
          const el = event.currentTarget;
          followLatest.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
        }}
      >
        {discovery.isError && !threadId && (
          <p role="alert">
            项目对话读取失败。
            <Button onClick={() => void discovery.refetch()}>重新读取项目对话</Button>
          </p>
        )}
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
        {research && (
          <article className="studio-context-card" aria-label="将随消息发送的研究正文">
            <strong>{research.label}</strong>
            <ContentFields value={research.body} />
            <Button tone="ghost" onClick={() => studio?.showAttachment(null)}>
              移除研究附件
            </Button>
          </article>
        )}
        {selection && selectedPart && (
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
            {item.role === "user" && "research_ref" in item && !!item.research_ref && (
              <small>已引用固定研究版本</small>
            )}
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
        {!pendingRequest && !error && observed?.status === "failed" && (
          <p role="alert">
            {observed.transport_status === "unknown_submission"
              ? "上次模型提交结果未知，请核对原任务回执。"
              : `上次对话未完成：${observed.last_error || "请检查项目文本模型"}。`}
          </p>
        )}
        {awaitingReply && (
          <p role="status">
            {receipt.data === null
              ? "服务器暂未找到这条消息。可重新核对，也可使用原请求键再次发送。"
              : receipt.isError
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
      {pendingRequest && receipt.data === null && !receipt.isFetching && !submitting && (
        <Button
          tone="ghost"
          disabled={!question.trim() || (!!previewUrl && loadedPreview !== previewUrl)}
          onClick={() => submitMessage(pendingRequest)}
        >
          按原请求键发送当前内容
        </Button>
      )}
      {error && (
        <p role="alert">
          {error}
          {modelSetup && (
            <ExternalLink
              type="link"
              href={`/settings/projects/${encodeURIComponent(projectId)}?returnTo=${encodeURIComponent(`/projects/${projectId}`)}`}
            >
              配置项目模型
            </ExternalLink>
          )}
        </p>
      )}
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
          submitMessage();
        }}
      >
        <Textarea
          id="project-director-message"
          aria-label="给导演的想法"
          placeholder="给导演留言，Enter 发送，Shift+Enter 换行"
          onKeyDown={(event) => {
            if (
              event.key !== "Enter" ||
              event.shiftKey ||
              event.nativeEvent.isComposing ||
              event.nativeEvent.keyCode === 229
            )
              return;
            event.preventDefault();
            if (!event.repeat) submitMessage();
          }}
          rows={3}
          maxLength={16000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
        {goalsOpen && !research && (
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
