import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, EmptyState, PageHeader, Upload } from "../../components/ui";
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

function locatorText(locator: Record<string, unknown>): string {
  const kind = String(locator.kind ?? "");
  if (kind === "paragraph") {
    const start = Number(locator.paragraph_start ?? 0);
    return String(locator.container_key) === "text-lines"
      ? `第 ${start + 1} 行`
      : `第 ${start + 1} 段`;
  }
  if (kind === "table_cells") {
    const row = Number(locator.row_start ?? 0) + 1;
    const column = Number(locator.column_start ?? 0) + 1;
    const sheet = locator.sheet ? `${String(locator.sheet)} · ` : "";
    return `${sheet}第 ${row} 行第 ${column} 列`;
  }
  if (kind === "page_region") {
    return `第 ${Number(locator.page_start ?? 0) + 1} 页`;
  }
  if (kind === "time_range") {
    const start = Number(locator.start_ms ?? 0);
    const end = Number(locator.end_ms ?? 0);
    return `${(start / 1000).toFixed(1)}–${(end / 1000).toFixed(1)} 秒`;
  }
  if (kind === "image_region") {
    const frame = locator.time_ms ?? locator.frame;
    return frame === undefined ? "图像区域" : `画面 ${frame}${locator.time_ms ? " 毫秒" : ""}`;
  }
  return kind || "未知定位";
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
    queryKey: queryKeys.source.revision(projectId, selected?.revision_id),
    queryFn: () => fetchSourceRevision(projectId, selected!.revision_id),
    enabled: Boolean(selected?.revision_id),
    retry: false,
  });
  const extractionId = revision.data?.extraction?.id ?? null;
  const fragments = useQuery({
    queryKey: queryKeys.source.fragments(projectId, extractionId, 0, ""),
    queryFn: () => listFragments(projectId, extractionId!, { limit: 200 }),
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
                {revision.data.extraction.extraction_schema_version}（从 0 开始）· 覆盖{" "}
                {revision.data.extraction.coverage.complete ? "完整" : "部分"} · 尝试{" "}
                {revision.data.extraction.attempt}
              </p>
              {fragments.isLoading && <p role="status">正在读取证据片段…</p>}
              <ol aria-label="证据片段">
                {fragments.data?.items.map((fragment) => (
                  <li key={fragment.id} data-testid="source-fragment">
                    <strong>{locatorText(fragment.locator)}</strong>
                    <p>{fragment.text_content}</p>
                    <span className="muted">
                      方法 {fragment.extraction_method} · 处理器 {fragment.processor_ref}
                      {(fragment.limitations ?? []).length > 0
                        ? ` · 复核提示 ${(fragment.limitations ?? []).join("、")}`
                        : ""}
                    </span>
                  </li>
                ))}
              </ol>
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
