// Prism, once loaded, highlights every `code[class*=language-]` on the page by itself, and would rewrite the
// elements React renders. `manual` turns that off; Prism reads it while it loads, so this module must be
// imported before 'prismjs' (ES modules run in import order).
(globalThis as { Prism?: unknown }).Prism = { manual: true };
