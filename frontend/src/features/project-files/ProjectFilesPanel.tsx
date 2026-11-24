import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";

import {
  ActionLink,
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Upload,
} from "../../components/ui";
import { FileUseEditor } from "./FileUseEditor";
import { StudioSelection } from "../../components/workstation/StudioSelection";
import { ApiError } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  acceptExtraction,
  fetchSourceCapabilities,
  fetchSourceRevision,
  listFragments,
  listProjectFiles,
  unlinkSource,
  uploadSource,
  type ProjectFileRead,
  type SourceCapabilityFormat,
} from "./api";

import { locatorText } from "./locatorText";

const STATUS_LABELS: Record<string, string> = {
  pending: "等待本地解析",
  parsed: "已完成本地解析",
  failed: "解析失败",
};

const COMPONENT_LABELS: Record<string, string> = {
  pdf_text: "PDF 文本层",
  pdf_ocr: "PDF 扫描页 OCR",
  xlsx: "XLSX 表格",
  image_ocr: "图片 OCR",
  audio_transcript: "音频转写",
  video_transcript: "视频音轨转写",
  video_frames: "视频画面取样",
};

function requestKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function formatMiB(bytes: number): string {
  return `${Math.round((bytes / (1024 * 1024)) * 10) / 10} MiB`;
}

function capabilityHint(formats: SourceCapabilityFormat[] | undefined): string {
  if (!formats || formats.length === 0) {
    return "支持格式以上传时的服务端能力为准。";
  }
  const available = formats.filter((item) => item.available);
  const names = available.map((item) => item.format.toUpperCase()).join("、");
  const limit = available.reduce((min, item) => Math.min(min, item.max_bytes), Infinity);
  return `当前可用：${names}；单次原件上限 ${formatMiB(limit)}。`;
}

export function ProjectFilesPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const files = useQuery({
    queryKey: queryKeys.source.files(projectId),
    queryFn: () => listProjectFiles(projectId),
    refetchInterval: (query) =>
      query.state.data?.some((file) => file.status === "pending" && file.source_available)
        ? 1500
        : false,
    retry: false,
  });
  const capabilities = useQuery({
    queryKey: queryKeys.source.capabilities(projectId),
    queryFn: () => fetchSourceCapabilities(projectId),
    retry: false,
  });
  const accept = (capabilities.data?.formats ?? [])
    .filter((item) => item.available)
    .flatMap((item) => item.extensions)
    .join(",");
  const missingComponents = Object.entries(capabilities.data?.components ?? {})
    .filter(([key, ready]) => !ready && key in COMPONENT_LABELS)
    .map(([key]) => COMPONENT_LABELS[key]);

  const selected: ProjectFileRead | undefined =
    files.data?.find((item) => item.id === selectedId) ?? files.data?.[0];
  const revision = useQuery({
    queryKey: [
      ...queryKeys.source.revision(projectId, selected?.revision_id),
      selected?.attempt,
      selected?.status,
      selected?.current_extraction_id,
    ],
    queryFn: () => fetchSourceRevision(projectId, selected!.revision_id),
    enabled: Boolean(selected?.revision_id),
    retry: false,
  });
  const [page, setPage] = useState<{ extraction: string; offset: number } | null>(null);
  const extractionId = revision.data?.extraction?.id ?? null;
  const showAttachment = useContext(StudioSelection)?.showAttachment;
  useEffect(
    () => () => showAttachment?.(null),
    [showAttachment, selected?.revision_id, extractionId],
  );
  const offset = page?.extraction === extractionId ? page.offset : 0;
  const fragments = useQuery({
    queryKey: queryKeys.source.fragments(projectId, extractionId, offset, ""),
    queryFn: () => listFragments(projectId, extractionId!, { limit: 200, offset }),
    enabled: Boolean(extractionId),
    retry: false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.source.root(projectId) });
  };

  const upload = useMutation({
    mutationFn: (file: File) =>
      uploadSource(projectId, {
        filename: file.name,
        data: file,
        requestKey: requestKey("upload"),
      }),
    onSuccess: (created) => {
      setError(null);
      setNotice(`已接收「${created.filename}」，本地解析在后台进行。`);
      setSelectedId(created.id);
      refresh();
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "上传失败"),
  });

  const acceptance = useMutation({
    mutationFn: (input: { item: ProjectFileRead; action: "retry" | "reparse" }) =>
      acceptExtraction(projectId, input.item.revision_id, input.action, {
        requestKey: requestKey(input.action),
        expectedFileVersion: input.item.version,
        expectedAttempt: input.item.attempt,
        expectedExtractionId: input.item.current_extraction_id,
        processorProfileRevision: capabilities.data?.profile_revision ?? "",
      }),
    onSuccess: (accepted, variables) => {
      setError(null);
      setNotice(
        variables.action === "retry"
          ? `已重新排入本地解析（第 ${accepted.accepted_attempt} 次尝试）。`
          : `已受理重新识别（第 ${accepted.accepted_attempt} 次尝试）；旧解析结果保留到新结果完成。`,
      );
      refresh();
    },
    onError: (caught) => {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("资料已变化或处理器配置已更新，请刷新后重新确认。");
        void queryClient.invalidateQueries({
          queryKey: queryKeys.source.capabilities(projectId),
        });
        refresh();
        return;
      }
      setError(caught instanceof Error ? caught.message : "受理失败");
    },
  });

  const unlink = useMutation({
    mutationFn: (item: ProjectFileRead) => unlinkSource(projectId, item.id, item.version),
    onSuccess: () => {
      setError(null);
      setNotice("已解除关联；原件与历史修订仍然保留。");
      refresh();
    },
    onError: (caught) => {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("资料已发生变化，请刷新后重新确认解除关联。");
        refresh();
        return;
      }
      setError(caught instanceof Error ? caught.message : "解除关联失败");
    },
  });

  return (
    <section aria-label="项目资料">
      <PageHeader
        title="项目资料"
        eyebrow="原件与本地解析"
        description="原件按项目私有保存；解析只在本机进行，结果作为证据片段保留，不会自动外发或调用模型。"
      />
      <Card aria-label="上传资料原件">
        <Upload
          accept={accept || ".txt,.csv,.tsv,.docx,.pdf,.xlsx"}
          multiple={false}
          showUploadList={false}
          beforeUpload={(file) => {
            upload.mutate(file as File);
            return false;
          }}
        >
          <Button disabled={upload.isPending} aria-label="选择资料原件">
            选择资料原件
          </Button>
        </Upload>
        <p className="muted" data-testid="source-capabilities">
          {capabilityHint(capabilities.data?.formats)}
        </p>
        {missingComponents.length > 0 && (
          <p className="muted" role="status">
            本机缺少处理组件：{missingComponents.join("、")}；相应格式不会被伪装成已解析。
          </p>
        )}
        {upload.isPending && <p role="status">正在上传…</p>}
      </Card>

      {notice && <p role="status">{notice}</p>}
      {(error || files.isError) && (
        <Alert
          role="alert"
          type="error"
          showIcon
          description={
            error ?? (files.error instanceof Error ? files.error.message : "无法读取资料")
          }
          action={<Button onClick={() => void files.refetch()}>重试</Button>}
        />
      )}

      {files.isSuccess && files.data.length === 0 && (
        <EmptyState title="还没有资料" description="上传地方志、访谈记录或表格等原件后开始整理。" />
      )}

      <div role="list" aria-label="资料列表">
        {files.data?.map((item) => (
          <Card key={item.id} role="listitem" selected={selected?.id === item.id}>
            <Button tone="ghost" onClick={() => setSelectedId(item.id)}>
              {item.filename}
            </Button>
            <Badge
              tone={
                item.status === "parsed" ? "success" : item.status === "failed" ? "danger" : "info"
              }
            >
              {STATUS_LABELS[item.status] ?? item.status}
            </Badge>
            <span className="muted">
              第 {item.content_version} 版 · {item.byte_size} 字节
              {item.source_available ? "" : " · 已解除关联"}
            </span>
            {item.status === "failed" && (
              <>
                <p role="alert">
                  解析失败：{item.error_code ?? "未知原因"}。原件已保留，可单独重试。
                </p>
                <Button
                  disabled={acceptance.isPending || !capabilities.data}
                  onClick={() => acceptance.mutate({ item, action: "retry" })}
                >
                  重试解析
                </Button>
              </>
            )}
            {item.status === "parsed" && item.source_available && (
              <Button
                tone="ghost"
                disabled={acceptance.isPending || !capabilities.data}
                onClick={() => acceptance.mutate({ item, action: "reparse" })}
              >
                重新识别
              </Button>
            )}
            {item.source_available && (
              <Button tone="danger" disabled={unlink.isPending} onClick={() => unlink.mutate(item)}>
                解除关联
              </Button>
            )}
          </Card>
        ))}
      </div>

      {selected && (
        <Card aria-label="解析结果">
          <h3>{selected.filename} 的解析结果</h3>
          {selected.source_available && (
            <FileUseEditor
              key={selected.revision_id}
              projectId={projectId}
              revisionId={selected.revision_id}
            />
          )}
          {revision.isLoading && <p role="status">正在读取解析状态…</p>}
          {revision.isError && (
            <Alert role="alert" type="error" showIcon description="无法读取解析结果，请重试。" />
          )}
          {revision.data && !revision.data.extraction && (
            <p role="status">
              {selected.status === "failed"
                ? "本次解析未产生结果，原件保留。"
                : "尚未产生解析结果。"}
            </p>
          )}
          {revision.data?.extraction && (
            <>
              <p className="muted">
                {revision.data.extraction.parser_key} · 定位版本{" "}
                {revision.data.extraction.extraction_schema_version}· 覆盖{" "}
                {revision.data.extraction.coverage.complete ? "完整" : "部分"} · 尝试{" "}
                {revision.data.extraction.attempt}
              </p>
              {fragments.isLoading && <p role="status">正在读取证据片段…</p>}
              <ol aria-label="证据片段">
                {fragments.data?.items.map((fragment) => (
                  <li key={fragment.id} data-testid="source-fragment">
                    <strong>
                      {locatorText(fragment.locator, fragment.extraction_schema_version)}
                    </strong>
                    <p>{fragment.text_content}</p>
                    {selected.source_available && fragment.source_available && (
                      <ActionLink
                        tone="ghost"
                        to="/projects/$projectId/research"
                        params={{ projectId }}
                        search={{
                          revision: selected.revision_id,
                          extraction: fragment.extraction_id,
                          fragment: fragment.id,
                          offset: offset || undefined,
                        }}
                      >
                        引用此段进行研究
                      </ActionLink>
                    )}
                    {showAttachment &&
                      selected.source_available &&
                      fragment.source_available &&
                      (fragment.locator_kind === "page_region" ||
                        fragment.locator_kind === "image_region") && (
                        <Button
                          tone="ghost"
                          onClick={() => {
                            showAttachment({
                              part: {
                                kind: "file",
                                file_revision_id: selected.revision_id,
                                source_fragment_id: fragment.id,
                                expected_content_hash: selected.content_hash,
                              },
                              label:
                                selected.filename +
                                " · " +
                                locatorText(fragment.locator, fragment.extraction_schema_version),
                            });
                            const input = document.getElementById("project-director-message");
                            if (!input?.getClientRects().length)
                              document.getElementById("studio-chat-toggle")?.click();
                            requestAnimationFrame(() => input?.focus());
                          }}
                        >
                          附到导演对话
                        </Button>
                      )}
                    <span className="muted">
                      方法 {fragment.extraction_method} · 处理器 {fragment.processor_ref}
                      {(fragment.limitations ?? []).length > 0
                        ? ` · 复核提示 ${(fragment.limitations ?? []).join("、")}`
                        : ""}
                    </span>
                  </li>
                ))}
              </ol>
              {fragments.isError && (
                <Alert
                  type="error"
                  description="未能读取证据片段。"
                  action={<Button onClick={() => void fragments.refetch()}>重新读取</Button>}
                />
              )}
              {extractionId &&
                fragments.data &&
                (offset > 0 || fragments.data.next_offset != null) && (
                  <div aria-label="片段分页">
                    <Button
                      disabled={offset === 0}
                      onClick={() =>
                        setPage({ extraction: extractionId, offset: Math.max(0, offset - 200) })
                      }
                    >
                      上一页
                    </Button>
                    <span>
                      第 {offset + 1}–{offset + fragments.data.items.length} 段，共{" "}
                      {fragments.data.total} 段
                    </span>
                    <Button
                      disabled={fragments.data.next_offset == null}
                      onClick={() => {
                        const next = fragments.data?.next_offset;
                        if (next != null) setPage({ extraction: extractionId, offset: next });
                      }}
                    >
                      下一页
                    </Button>
                  </div>
                )}
              {fragments.data && fragments.data.items.length === 0 && (
                <p role="status">本次解析没有可定位的文字片段。</p>
              )}
            </>
          )}
        </Card>
      )}
    </section>
  );
}
