import { apiGet } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export function fetchProjectCreativeOptions(): Promise<
  components["schemas"]["CapabilityCatalogBody"]
> {
  return apiGet("/api/v1/creative-capabilities/catalog");
}
