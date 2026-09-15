import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  describeScriptImportOutcome,
  importScript,
  scriptTextSizeError,
  type ScriptImportOutcome,
} from "./api";

type ScriptImportPanelProps = {
  projectId: string;
  /** Refresh Script/Scene/Shot reads after a successful import. */
  onImported?: (result: ScriptImportOutcome) => void | Promise<void>;
  /** Leave the panel for the first imported Shot. */
  onOpenFirstShot?: (result: ScriptImportOutcome) => void;
};

const MAX_BYTES_LABEL = "1 MiB";

const SUPPORTED_FORMAT_EXAMPLE = [
  "# Episode 1 — 雨夜车站",
  "## Scene 1 — 站台 / night",
  "### Shot 1 — medium",
  "Visual: 林墨站在雨中看向列车",
  "Dialogue: 你终于来了。",
].join("\n");

function readFileAsText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("无法读取所选文件"));
    reader.readAsText(file, "utf-8");
  });
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Canonical script import (paste or read a local UTF-8 file).
 *
 * Confirmation writes canonical Episode/Scene/Shot rows; the panel keeps the
 * text on failure, explains why, and never reports success from the client.
 */
export function ScriptImportPanel({
  projectId,
  onImported,
  onOpenFirstShot,
}: ScriptImportPanelProps) {
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [filename, setFilename] = useState("");
  const [text, setText] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [result, setResult] = useState<ScriptImportOutcome | null>(null);

  const sizeError = scriptTextSizeError(text);
  const byteCount = new TextEncoder().encode(text).length;

  const importMut = useMutation({
    mutationFn: async () => {
      setLocalError(null);
      return importScript(projectId, filename.trim() || "script.md", text);
    },
    onSuccess: async (imported) => {
      setResult(imported);
      await onImported?.(imported);
    },
    onError: (error: unknown) => {
      setResult(null);
      setLocalError(errorMessage(error));
    },
  });

  async function loadFile(file: File | null | undefined): Promise<void> {
    if (!file) return;
    setResult(null);
    setLocalError(null);
    try {
      const content = await readFileAsText(file);
      setFilename(file.name);
      setText(content);
      const tooLarge = scriptTextSizeError(content);
      if (tooLarge) setLocalError(tooLarge);
    } catch (error) {
      setLocalError(errorMessage(error));
    }
  }

  const submitDisabled = importMut.isPending || !text.trim() || Boolean(sizeError);
  const summary = result ? describeScriptImportOutcome(result) : null;
  const error = localError ?? (importMut.isError ? errorMessage(importMut.error) : null);

  return (
    <section className="qc-settings-band" data-testid="script-import-panel">
      <h2>导入剧本</h2>
      <p className="muted">
        支持 UTF-8 的 .md / .txt，结构为 <code># Episode</code> / <code>## Scene</code> /{" "}
        <code>### Shot</code>；文件在浏览器读取为文本后提交，上限 {MAX_BYTES_LABEL}。
      </p>
      <pre className="qc-script-import-format" data-testid="script-import-format-example">
        {SUPPORTED_FORMAT_EXAMPLE}
      </pre>

      <label>
        选择本地剧本文件
        <input
          ref={fileInput}
          type="file"
          accept=".md,.txt,text/plain,text/markdown"
          aria-label="选择剧本文件"
          onChange={(event) => {
            void loadFile(event.target.files?.[0]);
          }}
        />
      </label>

      <label>
        文件名
        <input
          aria-label="导入文件名"
          value={filename}
          onChange={(event) => setFilename(event.target.value)}
          placeholder="episode_script.md"
          disabled={importMut.isPending}
        />
      </label>

      <label>
        剧本内容
        <textarea
          aria-label="剧本内容"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setLocalError(null);
          }}
          rows={10}
          placeholder="粘贴或从上方选择文件"
          disabled={importMut.isPending}
        />
      </label>
      <p className="muted" data-testid="script-import-size">
        {byteCount} / {1024 * 1024} 字节
      </p>

      <button
        type="button"
        data-testid="script-import-submit"
        disabled={submitDisabled}
        onClick={() => importMut.mutate()}
      >
        确认导入
      </button>

      {sizeError && (
        <p className="flash err" data-testid="script-import-size-error" role="alert">
          {sizeError}
        </p>
      )}
      {error && !sizeError && (
        <p className="flash err" data-testid="script-import-error" role="alert">
          {error}
        </p>
      )}
      {summary && result && (
        <div data-testid="script-import-result" data-outcome={summary.tone} role="status">
          <p>{summary.message}</p>
          <button
            type="button"
            data-testid="script-import-open-first-shot"
            onClick={() => onOpenFirstShot?.(result)}
            disabled={result.shot_ids.length === 0}
          >
            进入第一个镜头
          </button>
        </div>
      )}
    </section>
  );
}
