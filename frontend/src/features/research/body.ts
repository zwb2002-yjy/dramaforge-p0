import type { ResearchKind } from "./api";

export function bodyFromText(kind: ResearchKind, text: string): Record<string, unknown> {
  switch (kind) {
    case "summary":
      return { schema_version: 1, text };
    case "person":
    case "place":
      return { schema_version: 1, display_name: text };
    case "event":
      return { schema_version: 1, description: text };
    case "timeline":
      return { schema_version: 1, items: [{ label: text }] };
    case "cultural_clue":
      return { schema_version: 1, theme: text, interpretation: text };
  }
}

export function correctedBody(kind: ResearchKind, body: Record<string, unknown>, text: string) {
  if (kind === "timeline" && Array.isArray(body.items) && body.items.length) {
    const [first, ...rest] = body.items;
    return { ...body, items: [{ ...first, label: text }, ...rest] };
  }
  if (kind === "cultural_clue") return { ...body, theme: text };
  return { ...body, ...bodyFromText(kind, text) };
}

export function bodyText(body: Record<string, unknown> | undefined): string {
  if (!body) return "";
  for (const key of ["text", "display_name", "description", "theme"]) {
    const value = body[key];
    if (typeof value === "string" && value) return value;
  }
  const items = body.items;
  if (Array.isArray(items) && items.length > 0) {
    const first = items[0] as Record<string, unknown>;
    return typeof first?.label === "string" ? first.label : "";
  }
  return "";
}
