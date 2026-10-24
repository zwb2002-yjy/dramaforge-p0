/** Human-readable media facts; raw values remain available in file details. */
export function formatFileSize(bytes: number | null | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  const index =
    bytes === 0 ? 0 : Math.max(0, Math.min(units.length - 1, Math.floor(Math.log10(bytes) / 3)));
  const size = new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: index === 0 ? 0 : 1,
  }).format(bytes / 1000 ** index);
  return `${size} ${units[index]}`;
}

export function formatMediaDuration(value: string | number): string {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  const parts = [Math.floor(total / 60) % 60, total % 60];
  if (total >= 3600) parts.unshift(Math.floor(total / 3600));
  return parts.map((part) => String(part).padStart(2, "0")).join(":");
}
