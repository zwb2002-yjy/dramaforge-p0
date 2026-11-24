const integer = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0;

// Schema 2 uses zero-based, half-open document indices and top-left raster pixels.
export function locatorText(loc: Record<string, unknown>, schema: number): string {
  if (schema !== 2) return "历史定位，请核对原件";
  const range = (start: unknown, end: unknown, unit: string) => {
    if (!integer(start) || !integer(end) || end <= start) return "";
    return end === start + 1 ? `第 ${start + 1} ${unit}` : `第 ${start + 1}–${end} ${unit}`;
  };
  const parts: string[] = [];
  if (loc.kind === "paragraph" || loc.kind === "table_cells") {
    if (typeof loc.part_path === "string") parts.push(loc.part_path);
    if (
      typeof loc.container_key === "string" &&
      !["text-lines", "body"].includes(loc.container_key)
    )
      parts.push(loc.container_key);
    if (loc.kind === "paragraph")
      parts.push(
        range(
          loc.paragraph_start,
          loc.paragraph_end,
          loc.container_key === "text-lines" ? "行" : "段",
        ),
      );
    else {
      if (typeof loc.sheet === "string") parts.push(loc.sheet);
      parts.push(
        range(loc.row_start, loc.row_end, "行"),
        range(loc.column_start, loc.column_end, "列"),
      );
      if (integer(loc.cell_paragraph)) parts.push(`格内第 ${loc.cell_paragraph + 1} 段`);
    }
  } else if (loc.kind === "page_region") parts.push(range(loc.page_start, loc.page_end, "页"));
  else if (loc.kind === "image_region") {
    if (integer(loc.time_ms)) parts.push(`画面 ${loc.time_ms / 1000} 秒`);
    else if (integer(loc.frame)) parts.push(`第 ${loc.frame + 1} 帧`);
  } else if (loc.kind === "time_range" && integer(loc.start_ms) && integer(loc.end_ms))
    parts.push(`${loc.start_ms / 1000}–${loc.end_ms / 1000} 秒`);
  if (loc.bbox && typeof loc.bbox === "object" && !Array.isArray(loc.bbox)) {
    const b = loc.bbox as Record<string, unknown>;
    if ([b.x, b.y, b.width, b.height].every(integer))
      parts.push(`区域（${b.x}, ${b.y}）· ${b.width} × ${b.height} 像素`);
  }
  if (integer(loc.char_start) && integer(loc.char_end) && loc.char_end > loc.char_start)
    parts.push(range(loc.char_start, loc.char_end, "字符"));
  return parts.filter(Boolean).join(" · ") || "位置未确认";
}
