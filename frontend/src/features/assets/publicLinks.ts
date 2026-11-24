import { apiGet } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export async function loadPublicLinks(projectId: string, signal: AbortSignal) {
  const links = new Map<string, components["schemas"]["PublicLinkReadModel"]>();
  let offset: number | null = 0;
  while (offset !== null) {
    const page: components["schemas"]["PublicLinkPage"] = await apiGet(
      `/api/v1/projects/${projectId}/public-asset-links?active=false&limit=100&offset=${offset}`,
      undefined,
      signal,
    );
    for (const link of page.items) links.set(link.publication_id, link);
    offset = page.next_offset;
  }
  return links;
}
