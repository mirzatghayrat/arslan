/**
 * THROWAWAY PROBE — never merged.
 *
 * Data point 2 of 2: does a red `frontend` check block a merge on its own?
 *
 * The line below is a deliberate tsc type error. It fails the typecheck step, so
 * `frontend` goes red while backend / macos / secrets stay green — this file is
 * TypeScript, so no Python job sees it, and it contains nothing secret.
 */

export const PROBE_DELIBERATE_TYPE_ERROR: number = "this string is not a number";
