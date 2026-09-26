// Development-only visual fixture. Not a production entry or live acceptance.
// All API/WS traffic is replaced before App mounts; no credentials or real data.
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from '../src/App';
import '../src/index.css';
import '../src/i18n';

const conversation = 'layout-synthetic';
const language = new URLSearchParams(location.search).get('lang') ?? 'zh';
localStorage.setItem('i18nextLng', language);
localStorage.setItem('arslan_first_run_seen', '1');
localStorage.setItem('arslan.threads', JSON.stringify([{ id: conversation, title: '研究计划 · 隔离界面验收', archived: false }]));
localStorage.setItem('arslan.activeThreadId', conversation);
sessionStorage.setItem('arslan.session', '1');
const task = { version: 1, conversation_id: conversation, pause_reason: null, cancel_requested: false,
  spec: { id: 'layout-task', revision: 1, instruction: '核对研究报告与引用来源', locale: language, acceptance: [] },
  state: { task_id: 'layout-task', spec_revision: 1, run_id: '1', sequence: 1, phase: 'waiting_user', checkpoint_ref: null, results: [] },
  budget: { id: 'layout-budget', used: {}, limits: {}, stop_reason: null },
  checkpoint: null, attempts: [], actions: [], workers: [] };
const originalFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
  if (url.origin !== location.origin) throw new Error('External traffic disabled in layout fixture');
  if (!url.pathname.startsWith('/api/')) return originalFetch(input, init);
  const path = url.pathname.replace('/api/v1', '');
  const method = init?.method ?? (input instanceof Request ? input.method : 'GET');
  if (method !== 'GET') return new Response(JSON.stringify({ detail: 'Read-only visual fixture' }), { status: 403 });
  let body: unknown = [];
  if (path === '/health') body = { status: 'ok' };
  else if (path === '/settings') body = { language, first_run_seen: 'true', orchestrator_shell_enabled: 'true',
    shell_confirm_policy: 'ask_risky', voice_mode: 'push_to_talk' };
  else if (path === '/settings/provider-configs') body = [{ id: 1, label: 'Synthetic model', provider: 'openai', model: 'fixture-only', is_primary: true }];
  else if (path === '/registry') body = { tools: [], toolsets: [], skills: [], skill_packs: [] };
  else if (path === '/conversations') body = [{ conversation_id: conversation, title: '研究计划 · 隔离界面验收', message_count: 2 }];
  else if (path === '/projects') body = [{ id: 'layout-project', name: 'Cedar', status: 'active', version: 1 }];
  else if (path.endsWith('/context')) body = { conversation_id: conversation, version: 1, project_id: 'layout-project',
    no_memory: false, no_learning: false, temporary: false, cloud_memory_allowed: false, allow_sensitive: false };
  else if (path === '/tasks') body = [task];
  else if (path === '/tasks/layout-task') body = task;
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
};

class FixtureSocket {
  static OPEN = 1;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() {
    setTimeout(() => {
      this.onopen?.();
      this.onmessage?.({ data: JSON.stringify({ type: 'history', messages: [
        { message_id: 1, role: 'user', content: '比较三个研究工具，给出来源和下一步建议。' },
        { message_id: 2, role: 'arslan', content: '## 先解决什么问题\n\n这是一份**隔离合成资料**，用来检查界面布局，不代表真实模型结果。\n\n### 研究结论\n\n- 先完成当前任务，再引入新的工具。\n- 报告保留来源、未知项和可继续修改的成果。\n- 有风险的执行仍需要明确确认。\n\n### 接下来\n\n请先核对比较口径，再决定是否继续。' },
      ] }) });
    }, 50);
  }
  send() { /* Never execute a command or call a model. */ }
  close() { this.readyState = 3; }
}
window.WebSocket = FixtureSocket as unknown as typeof WebSocket;
createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
