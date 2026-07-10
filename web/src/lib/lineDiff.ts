/**
 * lineDiff — a tiny line-level diff over two strings via the classic
 * Longest-Common-Subsequence (LCS) dynamic program. No dependency: the app ships
 * no diff library, and the S2 promotion card only needs an honest add/del/same
 * rendering of a base prompt vs a candidate prompt, so a small LCS is the right
 * amount of machinery.
 *
 * Returns rows in reading order. `same` lines appear once (shared); a changed
 * region emits its `del` (base-only) lines followed by its `add` (candidate-only)
 * lines — the conventional unified-diff ordering.
 */
export type LineDiffType = "same" | "add" | "del";
export interface LineDiffRow {
  type: LineDiffType;
  text: string;
}

export function lineDiff(a: string, b: string): LineDiffRow[] {
  const aLines = a.split("\n");
  const bLines = b.split("\n");
  const n = aLines.length;
  const m = bLines.length;

  // lcs[i][j] = length of the LCS of aLines[i:] and bLines[j:].
  const lcs: number[][] = Array.from({ length: n + 1 }, () =>
    new Array<number>(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] =
        aLines[i] === bLines[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const rows: LineDiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (aLines[i] === bLines[j]) {
      rows.push({ type: "same", text: aLines[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ type: "del", text: aLines[i] });
      i++;
    } else {
      rows.push({ type: "add", text: bLines[j] });
      j++;
    }
  }
  while (i < n) {
    rows.push({ type: "del", text: aLines[i] });
    i++;
  }
  while (j < m) {
    rows.push({ type: "add", text: bLines[j] });
    j++;
  }
  return rows;
}
