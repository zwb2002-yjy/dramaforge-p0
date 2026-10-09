/** A display label is substituted as a whole token, never by substring or Asset name. */
export function replaceMentionLabel(value: string, before: string, after: string): string {
  return value.replace(/@[\p{L}\p{N}_-]+/gu, (token) => token === before ? after : token);
}
