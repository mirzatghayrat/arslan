/**
 * FMT1 PR 2 (0.1.64): models also write formulas as \[...\] and \(...\), and Markdown would eat those backslashes. This
 * turns them into the $$ that remark-math reads, and leaves code alone. No lookbehind: the app runs on WebKit 14 (macOS 11).
 */
const PIECES = new RegExp([
  String.raw`\\\\`,                                                                    // an escaped backslash: what follows is text
  String.raw`(?:^|\n)[ \t]*(\`{3,}|~{3,})[^\n]*(?:\n[\s\S]*?(?:\n[ \t]*\1[ \t]*(?=\n|$)|$)|$)`,  // a fence, closed or not
  String.raw`(\`+)[\s\S]*?\2`,                                                         // inline code
  String.raw`\\\[([\s\S]+?)\\\]`,
  String.raw`\\\(([^\n]+?)\\\)`,
].join('|'), 'g');

export function texDelimiters(text: string): string {
  return text.replace(PIECES, (whole, _fence, _code, block?: string, inline?: string) => {
    if (block !== undefined) return `\n$$\n${block}\n$$\n`;
    return inline !== undefined ? `$$${inline}$$` : whole;
  });
}
