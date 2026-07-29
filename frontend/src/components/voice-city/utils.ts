// Shared helpers for the Voice City studio components.
// deepClone / errorMessage / mergeParameters / setPath are consumed by
// VoiceCityStudio.tsx; getPath is used by the panel components in this folder.

import type { VoiceParameterGroup, VoiceParameters, VoiceParameterValue } from '../../types/voice-city'

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Structured clone with a JSON fallback for exotic environments. */
export function deepClone<T>(value: T): T {
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value)
    } catch {
      // Fall through to the JSON strategy below.
    }
  }
  if (value === undefined || value === null) return value
  return JSON.parse(JSON.stringify(value)) as T
}

/** Best human-readable message for an unknown thrown value (axios-aware). */
export function errorMessage(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value
  if (isPlainObject(value)) {
    const response = value.response
    if (isPlainObject(response)) {
      const data = response.data
      if (isPlainObject(data)) {
        if (typeof data.error === 'string' && data.error) return data.error
        if (typeof data.message === 'string' && data.message) return data.message
      }
    }
    if (typeof value.message === 'string' && value.message) return value.message
  }
  if (value instanceof Error && value.message) return value.message
  return 'Something went wrong. Please try again.'
}

function mergeInto(base: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const next: Record<string, unknown> = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue
    const current = next[key]
    if (isPlainObject(current) && isPlainObject(value)) {
      next[key] = mergeInto(current, value)
    } else if (isPlainObject(value)) {
      next[key] = mergeInto({}, value)
    } else {
      next[key] = deepClone(value)
    }
  }
  return next
}

/**
 * Deep-merges a sparse parameter patch over a base document and returns a new
 * document. Neither input is mutated; nested groups are merged key by key.
 */
export function mergeParameters(base: VoiceParameters, patch: VoiceParameters): VoiceParameters {
  return mergeInto(deepClone(base), patch) as VoiceParameters
}

/**
 * Immutably sets a dotted path such as "identity.resonance.chest" and returns
 * a new document. Intermediate groups are created when missing.
 */
export function setPath(
  document: VoiceParameters,
  path: string,
  value: VoiceParameterValue | VoiceParameterGroup,
): VoiceParameters {
  const segments = path.split('.').filter(Boolean)
  const root = deepClone(document) as Record<string, unknown>
  if (!segments.length) return root as VoiceParameters
  let cursor: Record<string, unknown> = root
  for (const segment of segments.slice(0, -1)) {
    const existing = cursor[segment]
    const child: Record<string, unknown> = isPlainObject(existing) ? existing : {}
    cursor[segment] = child
    cursor = child
  }
  cursor[segments[segments.length - 1]] = deepClone(value)
  return root as VoiceParameters
}

/** Reads the scalar stored at a dotted path, if any. */
export function getPath(
  document: VoiceParameters | null | undefined,
  path: string,
): VoiceParameterValue | undefined {
  if (!document) return undefined
  let cursor: unknown = document
  for (const segment of path.split('.').filter(Boolean)) {
    if (!isPlainObject(cursor)) return undefined
    cursor = cursor[segment]
  }
  if (cursor === null) return null
  const kind = typeof cursor
  if (kind === 'string' || kind === 'number' || kind === 'boolean') return cursor as VoiceParameterValue
  return undefined
}
