/**
 * ExperimentCompare (P5-05 / 03 §49).
 *
 * Compares the formal shot against A/B experiments column-by-column:
 * image, video, model, prompt, translation warning and references.
 * Pure presentational: no provider/model-name branching.
 */

export interface ExperimentReferenceRow {
  purpose: string;
  delivery: string;
}

export interface ExperimentColumnData {
  label: string;
  model: string;
  imageArtifactUrl?: string | null;
  videoArtifactUrl?: string | null;
  prompt?: string | null;
  translationWarning?: string | null;
  references: ExperimentReferenceRow[];
}

export interface ExperimentCompareProps {
  formal: ExperimentColumnData | null;
  experiments: ExperimentColumnData[];
}

function ReferenceList({ references }: { references: ExperimentReferenceRow[] }) {
  if (references.length === 0) return <span className="text-gray-400">—</span>;
  return (
    <ul className="list-disc pl-4 text-xs">
      {references.map((reference, index) => (
        <li key={`${reference.purpose}-${index}`}>
          {reference.purpose} · <span className={reference.delivery === "exact" ? "text-green-600" : "text-amber-600"}>{reference.delivery}</span>
        </li>
      ))}
    </ul>
  );
}

function MediaCell({ url, label }: { url?: string | null; label: string }) {
  if (!url) return <span className="text-gray-400">—</span>;
  return (
    <img src={url} alt={label} className="h-24 w-full rounded border object-cover" />
  );
}

export function ExperimentCompare({ formal, experiments }: ExperimentCompareProps) {
  const columns: ExperimentColumnData[] = [];
  if (formal) columns.push(formal);
  columns.push(...experiments);

  return (
    <div className="overflow-x-auto" data-testid="experiment-compare">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="border p-2 text-left text-xs text-gray-500">对比项</th>
            {columns.map((column) => (
              <th key={column.label} className="border p-2 text-left">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="border p-2 text-xs text-gray-500">模型</td>
            {columns.map((column) => (
              <td key={column.label} className="border p-2">
                {column.model || "—"}
              </td>
            ))}
          </tr>
          <tr>
            <td className="border p-2 text-xs text-gray-500">关键帧</td>
            {columns.map((column) => (
              <td key={column.label} className="border p-2">
                <MediaCell url={column.imageArtifactUrl} label={`${column.label} 关键帧`} />
              </td>
            ))}
          </tr>
          <tr>
            <td className="border p-2 text-xs text-gray-500">视频</td>
            {columns.map((column) => (
              <td key={column.label} className="border p-2">
                <MediaCell url={column.videoArtifactUrl} label={`${column.label} 视频`} />
              </td>
            ))}
          </tr>
          <tr>
            <td className="border p-2 text-xs text-gray-500">Prompt</td>
            {columns.map((column) => (
              <td key={column.label} className="border p-2 text-xs">
                {column.prompt || "—"}
              </td>
            ))}
          </tr>
          <tr>
            <td className="border p-2 text-xs text-gray-500">翻译告警</td>
            {columns.map((column) => (
              <td key={column.label} className="border p-2 text-xs">
                {column.translationWarning ? (
                  <span className="text-amber-600">{column.translationWarning}</span>
                ) : (
                  <span className="text-green-600">无</span>
                )}
              </td>
            ))}
          </tr>
          <tr>
            <td className="border p-2 text-xs text-gray-500">References</td>
            {columns.map((column) => (
              <td key={column.label} className="border p-2">
                <ReferenceList references={column.references} />
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
