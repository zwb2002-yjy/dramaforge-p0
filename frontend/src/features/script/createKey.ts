/**
 * Content-derived idempotency key for Story proposal creation.
 *
 * The same draft content reuses one key across double-clicks, lost responses and
 * reloads, so the backend can replay the committed proposal. Editing the content
 * produces a different key and therefore a new proposal intent.
 */

function fnv1a(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

export function storyCreateIdempotencyKey(
  brief: string,
  filename: string,
  draftText: string,
): string {
  const source = `${brief}\u0000${filename}\u0000${draftText}`;
  return `story-create-${fnv1a(source)}-${source.length.toString(36)}`;
}
