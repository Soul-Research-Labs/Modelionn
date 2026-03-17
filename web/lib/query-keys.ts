/**
 * Query cache key utilities for deterministic, normalized cache behavior.
 *
 * Ensures that different parameter orderings don't create different cache entries.
 * For example, {a: 1, b: 2} and {b: 2, a: 1} should map to the same cache key.
 */

/** Normalize object keys alphabetically for deterministic stringification. */
function normalizeParams(
  params: Record<string, any>,
): Record<string, any> {

  const normalized: Record<string, any> = {};
  const keys = Object.keys(params).sort();
  for (const key of keys) {
    normalized[key] = params[key];
  }
  return normalized;
}

/** Create a deterministic cache key tuple. */
export function makeQueryKey(
  baseKey: string,
  params?: Record<string, any>,
): (string | Record<string, any>)[] {
  if (!params) return [baseKey];
  return [baseKey, normalizeParams(params)];
}

/** Create cache key for paginated queries. */
export function makePaginatedKey(
  baseKey: string,
  params?: Record<string, any> & { page?: number; page_size?: number },
): (string | Record<string, any>)[] {
  return makeQueryKey(baseKey, params);
}

/** Create cache key for single-item queries. */
export function makeSingleKey(
  baseKey: string,
  id: string | number,
): (string | number | Record<string, any>)[] {
  return [baseKey, id];
}
