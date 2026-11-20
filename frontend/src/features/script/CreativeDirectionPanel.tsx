import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useContext, useState } from "react";

import { ApiError } from "../../lib/api";
import { Sparkles, Send } from "lucide-react";
import { StudioSelection } from "../../components/workstation/StudioSelection";
import { ActionLink, Button, Field, Textarea } from "../../components/ui";
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
  const preview = useContext(StudioSelection)?.media;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [edit, setEdit] = useState<{ text: string; baseVersion: number } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const storageKey = `df.project.director.${projectId}`;
  const [threadId, setThreadId] = useState<string | null>(() => sessionStorage.getItem(storageKey));
  const [question, setQuestion] = useState("");
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
        intent: "conversation",
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
      setQuestion("");
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
        <Button tone="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
          创作方向
        </Button>
      </header>
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
        {preview && (
          <article className="studio-context-card">
            <strong>当前讨论的画面</strong>
            {preview.video ? (
              <video controls preload="metadata" src={preview.url + "#t=0.01"} />
            ) : (
              <img src={preview.url} alt="当前选中的画面" />
            )}
          </article>
        )}
        {messages.map((item) => (
          <article key={item.id} data-role={item.role}>
            <strong>{item.role === "assistant" ? "导演" : "你"}</strong>
            <p>{item.content}</p>
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
          if (question.trim() && !send.isPending && !awaitingReply) send.mutate();
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
        <Button
          aria-label="发送给导演"
          type="submit"
          tone="primary"
          disabled={!question.trim() || send.isPending || awaitingReply}
        >
          <Send size={17} />
        </Button>
      </form>
    </aside>
  );
}
