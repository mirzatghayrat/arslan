// Prism reads these while it loads, so this module must be imported before 'prismjs' (ES modules run in import order).
// disableWorkerMessageHandler: in a worker, Prism otherwise answers every message itself and closes the worker.
// manual: with a page around (the tests have one), Prism otherwise rewrites every `code[class*=language-]` on it.
(globalThis as { Prism?: unknown }).Prism = { manual: true, disableWorkerMessageHandler: true };
