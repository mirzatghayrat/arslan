/**
 * FMT1 (0.1.64): Prism's grammars backtrack: some inputs of a few kB take tens of seconds, and a reply can carry text
 * from outside content. So Prism runs in a worker, and a worker that takes too long is terminated. That is the one
 * real bound: no size cap tells a slow fence from ordinary code. A fence with no answer stays plain text.
 */
import type { Tokens } from './highlightTokens';

const BUDGET_MS = 2000;
/** Answers kept, a slow fence's null among them, so a re-render or a remount never asks twice. */
const KEEP = 200;

interface Job { key: string; code: string; lang: string; done: () => void }

const answers = new Map<string, Tokens>();
const waiting: Job[] = [];
let worker: Worker | null = null;
let running: Job | null = null;
let timer: ReturnType<typeof setTimeout>;

function finish(tokens: Tokens) {
  clearTimeout(timer);
  const job = running!;
  running = null;
  answers.set(job.key, tokens);
  if (answers.size > KEEP) answers.delete(answers.keys().next().value!);
  job.done();
  next();
}

function kill() {
  worker?.terminate();
  worker = null;
  finish(null);
}

function spawn() {
  const w = new Worker(new URL('./highlight.worker.ts', import.meta.url), { type: 'module' });
  w.onmessage = ({ data }: MessageEvent<Tokens>) => finish(data);
  w.onerror = kill;
  return w;
}

function next() {
  if (running || !waiting.length) return;
  running = waiting.shift()!;
  worker ??= spawn();
  timer = setTimeout(kill, BUDGET_MS);
  worker.postMessage({ code: running.code, lang: running.lang });
}

const keyOf = (code: string, lang: string) => `${lang}\0${code}`;

/** Tokens, null for plain text, or undefined while the answer isn't in yet. */
export function answerFor(code: string, lang: string): Tokens | undefined {
  if (!lang || typeof Worker === 'undefined') return null;
  return answers.get(keyOf(code, lang));
}

/**
 * `done` runs once answerFor has the answer. Returns how to withdraw the question, for a stream that has moved on;
 * one already at the worker still answers, and its colours fit the start of the newer text.
 */
export function ask(code: string, lang: string, done: () => void): () => void {
  const job: Job = { key: keyOf(code, lang), code, lang, done };
  waiting.push(job);
  next();
  return () => {
    const i = waiting.indexOf(job);
    if (i >= 0) waiting.splice(i, 1);
  };
}
