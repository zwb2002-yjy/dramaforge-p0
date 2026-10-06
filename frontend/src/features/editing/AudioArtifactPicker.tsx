import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { Button, Select } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { fetchEditingAudioArtifacts } from "./api";
import "./audio-artifact-picker.css";

const MUTED = "__muted__";

/** Browsing and playback are reads; selecting only changes the local timeline draft. */
export function AudioArtifactPicker({
  projectId,
  label,
  value,
  defaultLabel,
  muted = false,
  allowMute = false,
  testId,
  onChange,
}: {
  projectId: string;
  label: string;
  value: string;
  defaultLabel: string;
  muted?: boolean;
  allowMute?: boolean;
  testId: string;
  onChange: (artifactId: string, muted: boolean) => void;
}) {
  const id = useId();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [selectedCaption, setSelectedCaption] = useState<{ id: string; label: string } | null>(
    null,
  );
  const [failedPreview, setFailedPreview] = useState<string | null>(null);
  const cursor = cursors[cursors.length - 1];
  const audio = useQuery({
    queryKey: queryKeys.editing.audioLibrary(projectId, cursor),
    queryFn: ({ signal }) => fetchEditingAudioArtifacts(projectId, cursor, signal),
    enabled: open && Boolean(projectId),
    staleTime: 60_000,
    retry: false,
  });
  const previewId = muted ? "" : value;

  return (
    <div className="editing-audio-picker">
      <label htmlFor={id}>{label}</label>
      <div className="editing-audio-picker-actions">
        <Select
          id={id}
          aria-label={label}
          data-testid={testId}
          value={muted ? MUTED : value}
          onChange={(event) =>
            onChange(
              event.target.value === MUTED ? "" : event.target.value,
              event.target.value === MUTED,
            )
          }
        >
          <option value="">{defaultLabel}</option>
          {allowMute && <option value={MUTED}>不使用配音</option>}
          {value && (
            <option value={value}>
              {selectedCaption?.id === value ? selectedCaption.label : "当前已绑定音频"}
            </option>
          )}
        </Select>
        <Button
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-library`}
          onClick={() => setOpen(!open)}
        >
          {open ? `收起${label}音频库` : `选择${label}`}
        </Button>
      </div>
      {previewId && (
        <div className="editing-audio-preview">
          <audio
            key={previewId}
            controls
            preload="none"
            aria-label={`${label}试听`}
            src={artifactContentUrl(projectId, previewId)}
            onError={() => setFailedPreview(previewId)}
            onCanPlay={() => setFailedPreview(null)}
          />
          {failedPreview === previewId && (
            <p role="alert">此音频暂时无法播放，已保留原选择；可刷新列表或改选，不会自动替换。</p>
          )}
        </div>
      )}
      {open && (
        <section
          id={`${id}-library`}
          className="editing-audio-library"
          aria-label={`${label}音频库`}
        >
          <div className="editing-audio-picker-actions">
            <strong>可用音频</strong>
            <Button
              type="button"
              disabled={audio.isFetching}
              onClick={() => {
                setCursors([null]);
                void client.invalidateQueries({
                  queryKey: queryKeys.editing.audioLibraryRoot(projectId),
                });
              }}
            >
              刷新音频
            </Button>
          </div>
          <p className="muted">
            试听后选择。只使用当前项目已入库的音频结果，选择不会生成或保存；确认后仍须保存时间线。
          </p>
          {audio.isPending && <p role="status">正在读取音频…</p>}
          {audio.isError && (
            <p role="alert">音频读取失败，不能据此判断没有素材。{audio.error.message}</p>
          )}
          {audio.data && !audio.isError && (
            <>
              {audio.data.items.length === 0 ? (
                <p>
                  当前没有可用音频结果；声音设定卡不是音频文件。可以不加配乐继续导出，不会自动生成或计费。
                </p>
              ) : (
                <ul>
                  {audio.data.items.map((item, index) => {
                    const number = (cursors.length - 1) * 25 + index + 1;
                    const duration = Number(item.duration_seconds);
                    const caption = `音频 ${number}${Number.isFinite(duration) && duration > 0 ? ` · ${duration.toFixed(2)} 秒` : ""}`;
                    return (
                      <li key={item.id}>
                        <div className="editing-audio-picker-actions">
                          <strong>{caption}</strong>
                          <small>{Math.ceil(item.byte_size / 1024)} KB</small>
                        </div>
                        <audio
                          controls
                          preload="none"
                          aria-label={`试听音频 ${number}`}
                          src={artifactContentUrl(projectId, item.id)}
                        />
                        <Button
                          type="button"
                          aria-pressed={!muted && value === item.id}
                          onClick={() => {
                            setSelectedCaption({ id: item.id, label: caption });
                            onChange(item.id, false);
                            setOpen(false);
                          }}
                        >
                          使用音频 {number}
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              )}
              <nav aria-label={`${label}音频翻页`} className="editing-audio-picker-actions">
                <Button
                  type="button"
                  disabled={cursors.length === 1 || audio.isFetching}
                  onClick={() => setCursors((pages) => pages.slice(0, -1))}
                >
                  上一页音频
                </Button>
                <span>第 {cursors.length} 页</span>
                <Button
                  type="button"
                  disabled={!audio.data.next_cursor || audio.isFetching}
                  onClick={() => {
                    if (audio.data.next_cursor)
                      setCursors((pages) => [...pages, audio.data.next_cursor]);
                  }}
                >
                  下一页音频
                </Button>
              </nav>
            </>
          )}
        </section>
      )}
    </div>
  );
}
