/**
 * The island's strings (0.1.51) in the app's six languages. Its own small table
 * instead of the app's i18next setup: the island page (web/src/island/) loads
 * none of the app bundle.
 * The language follows the app's choice (same origin, same localStorage key).
 */
export const LANGS = ['en', 'zh', 'ja', 'es', 'de', 'fr'] as const;
export type Lang = (typeof LANGS)[number];

const en = {
  region: 'Arslan Island',
  idle: 'Idle',
  running: '{{n}} running',
  learned: '+{{n}} practice',
  turn: 'Conversation',
  job: 'Background work',
  scheduled: 'Scheduled task',
  emptyTitle: 'Nothing running right now',
  openArslan: 'Open Arslan',
  openConversation: 'Open conversation',
  finished: 'Done',
  finishedNoSummary: 'Finished. The result is in the conversation.',
  stoppedNeedsReview: 'Stopped here for now',
  stoppedNeedsReviewText: 'It reached the work limit for this round or needs you to look before it goes on.',
  stoppedError: 'Stopped with an error',
  stoppedErrorText: 'Something went wrong. The conversation has the details.',
  stoppedPaused: 'Scheduled task paused',
  stoppedPausedText: 'It failed several times in a row, so it will not run again until you turn it back on.',
  needsYou: 'Waiting for you',
  needsYouText: 'Arslan wants to do something that needs your OK.',
  wantsTo: 'Wants to',
  openToApprove: 'Open to approve',
  close: 'Close',
  plan: 'Plan',
  stopHands: 'Stop',
  stoppedHands: 'Stopped',
  allow: 'Allow',
  decline: 'Decline',
  openInArslan: 'Open in Arslan',
  riskyNote: 'This one may delete, send or pay — read it in Arslan before allowing.',
  answerFailed: 'Could not answer here. Open Arslan.',
  stopJob: 'Stop',
  stoppingJob: 'Stopping…',
  ask: { run_command: 'Run a command', workspace_write: 'Write in your folder', schedule: 'Set up a scheduled task', browser_site: 'Act on a website', desktop_look: 'Look at an app', desktop_app: 'Act in an app', desktop_risky: 'A step that may delete, send or pay', mac_shortcut: 'Run a Shortcut', mac_script: 'Run an AppleScript', other: 'Needs your OK' },
  step: {
    desktop_apps: 'List the open apps', desktop_look: 'Look at {{t}}', desktop_click: 'Click {{t}}', desktop_type: 'Type in {{t}}', desktop_select: 'Choose in {{t}}', desktop_scroll: 'Scroll {{t}}', desktop_press: 'Press {{t}}',
    web_search: 'Search “{{t}}”', web_extract: 'Read {{t}}', browser_open: 'Open {{t}} in the browser',
    read_file: 'Read {{t}}', write_file: 'Write {{t}}', edit_file: 'Edit {{t}}', list_dir: 'Look in {{t}}',
    run_command: 'Run {{t}}', update_plan: 'Update the plan', recall: 'Look through memory', other: 'Use {{tool}}',
  },
};
type Messages = typeof en;

const zh: Messages = {
  region: 'Arslan 灵动岛',
  idle: '空闲',
  running: '{{n}} 个进行中',
  learned: '+{{n}} 个做法',
  turn: '对话',
  job: '后台工作',
  scheduled: '定时任务',
  emptyTitle: '现在没有在做的事',
  openArslan: '打开 Arslan',
  openConversation: '打开对话',
  finished: '做完了',
  finishedNoSummary: '做完了，结果在对话里。',
  stoppedNeedsReview: '先停在这里',
  stoppedNeedsReviewText: '这一轮的工作量到上限了，或者需要你看一眼再继续。',
  stoppedError: '出错停下了',
  stoppedErrorText: '出了点问题，详情在对话里。',
  stoppedPaused: '定时任务已暂停',
  stoppedPausedText: '连续失败了几次，你重新打开之前它不会再运行。',
  needsYou: '在等你',
  needsYouText: 'Arslan 想做一件需要你点头的事。',
  wantsTo: '想要',
  openToApprove: '打开去批准',
  close: '收起',
  plan: '计划',
  stopHands: '停止',
  stoppedHands: '已停止',
  allow: '允许',
  decline: '不要',
  openInArslan: '在 Arslan 里看',
  riskyNote: '这一步可能删除、发送或付款——请在 Arslan 里看完整再批准。',
  answerFailed: '这里没能答复，请打开 Arslan。',
  stopJob: '停下',
  stoppingJob: '正在停…',
  ask: { run_command: '跑一条命令', workspace_write: '写到你的文件夹', schedule: '建一个定时任务', browser_site: '在网站上操作', desktop_look: '看一个应用', desktop_app: '在应用里操作', desktop_risky: '可能删除、发送或付款的一步', mac_shortcut: '运行快捷指令', mac_script: '运行 AppleScript', other: '需要你点头' },
  step: {
    desktop_apps: '列出打开的应用', desktop_look: '查看 {{t}}', desktop_click: '点击 {{t}}', desktop_type: '在 {{t}} 输入', desktop_select: '在 {{t}} 选择', desktop_scroll: '滚动 {{t}}', desktop_press: '按键 {{t}}',
    web_search: '搜索「{{t}}」', web_extract: '读取 {{t}}', browser_open: '在浏览器里打开 {{t}}',
    read_file: '读取 {{t}}', write_file: '写入 {{t}}', edit_file: '修改 {{t}}', list_dir: '查看 {{t}}',
    run_command: '运行 {{t}}', update_plan: '更新计划', recall: '翻记忆', other: '使用 {{tool}}',
  },
};

const ja: Messages = {
  region: 'Arslan アイランド',
  idle: '待機中',
  running: '{{n}} 件実行中',
  learned: 'やり方 +{{n}}',
  turn: '会話',
  job: 'バックグラウンド作業',
  scheduled: 'スケジュールタスク',
  emptyTitle: '今は何も実行していません',
  openArslan: 'Arslan を開く',
  openConversation: '会話を開く',
  finished: '完了',
  finishedNoSummary: '完了しました。結果は会話にあります。',
  stoppedNeedsReview: 'ここでいったん停止',
  stoppedNeedsReviewText: 'この回の作業上限に達したか、続ける前に確認が必要です。',
  stoppedError: 'エラーで停止',
  stoppedErrorText: '問題が起きました。詳しくは会話を見てください。',
  stoppedPaused: 'スケジュールタスクを一時停止',
  stoppedPausedText: '続けて失敗したため、もう一度オンにするまで実行されません。',
  needsYou: 'あなたを待っています',
  needsYouText: 'Arslan があなたの許可が必要な操作をしようとしています。',
  wantsTo: 'やりたいこと',
  openToApprove: '開いて許可する',
  close: '閉じる',
  plan: '計画',
  stopHands: '止める',
  stoppedHands: '停止しました',
  allow: '許可',
  decline: '許可しない',
  openInArslan: 'Arslan で見る',
  riskyNote: '削除・送信・支払いになる可能性があります。Arslan で全体を見てから許可してください。',
  answerFailed: 'ここでは答えられませんでした。Arslan を開いてください。',
  stopJob: '止める',
  stoppingJob: '停止中…',
  ask: { run_command: 'コマンドを実行', workspace_write: 'フォルダに書き込む', schedule: '定期タスクを作る', browser_site: 'ウェブサイトで操作', desktop_look: 'アプリを見る', desktop_app: 'アプリで操作', desktop_risky: '削除・送信・支払いになりうる操作', mac_shortcut: 'ショートカットを実行', mac_script: 'AppleScript を実行', other: '確認が必要です' },
  step: {
    desktop_apps: '開いているアプリを一覧', desktop_look: '{{t}} を見る', desktop_click: '{{t}} をクリック', desktop_type: '{{t}} に入力', desktop_select: '{{t}} で選択', desktop_scroll: '{{t}} をスクロール', desktop_press: '{{t}} を押す',
    web_search: '「{{t}}」を検索', web_extract: '{{t}} を読む', browser_open: 'ブラウザで {{t}} を開く',
    read_file: '{{t}} を読む', write_file: '{{t}} に書き込む', edit_file: '{{t}} を編集', list_dir: '{{t}} を見る',
    run_command: '{{t}} を実行', update_plan: '計画を更新', recall: '記憶を探す', other: '{{tool}} を使う',
  },
};

const es: Messages = {
  region: 'Arslan Island',
  idle: 'En reposo',
  running: '{{n}} en curso',
  learned: '+{{n}} práctica',
  turn: 'Conversación',
  job: 'Trabajo en segundo plano',
  scheduled: 'Tarea programada',
  emptyTitle: 'Ahora no hay nada en marcha',
  openArslan: 'Abrir Arslan',
  openConversation: 'Abrir conversación',
  finished: 'Hecho',
  finishedNoSummary: 'Terminado. El resultado está en la conversación.',
  stoppedNeedsReview: 'Se detuvo aquí por ahora',
  stoppedNeedsReviewText: 'Llegó al límite de trabajo de esta ronda o necesita que lo revises antes de seguir.',
  stoppedError: 'Se detuvo por un error',
  stoppedErrorText: 'Algo salió mal. Los detalles están en la conversación.',
  stoppedPaused: 'Tarea programada en pausa',
  stoppedPausedText: 'Falló varias veces seguidas, así que no volverá a ejecutarse hasta que la reactives.',
  needsYou: 'Te está esperando',
  needsYouText: 'Arslan quiere hacer algo que necesita tu visto bueno.',
  wantsTo: 'Quiere',
  openToApprove: 'Abrir para aprobar',
  close: 'Cerrar',
  plan: 'Plan',
  stopHands: 'Detener',
  stoppedHands: 'Detenido',
  allow: 'Permitir',
  decline: 'No',
  openInArslan: 'Abrir en Arslan',
  riskyNote: 'Esto puede borrar, enviar o pagar: revísalo en Arslan antes de permitirlo.',
  answerFailed: 'No se pudo responder aquí. Abre Arslan.',
  stopJob: 'Detener',
  stoppingJob: 'Deteniendo…',
  ask: { run_command: 'Ejecutar un comando', workspace_write: 'Escribir en tu carpeta', schedule: 'Crear una tarea programada', browser_site: 'Actuar en un sitio web', desktop_look: 'Mirar una app', desktop_app: 'Actuar en una app', desktop_risky: 'Un paso que puede borrar, enviar o pagar', mac_shortcut: 'Ejecutar un Atajo', mac_script: 'Ejecutar un AppleScript', other: 'Necesita tu visto bueno' },
  step: {
    desktop_apps: 'Listar las apps abiertas', desktop_look: 'Ver {{t}}', desktop_click: 'Clic en {{t}}', desktop_type: 'Escribir en {{t}}', desktop_select: 'Elegir en {{t}}', desktop_scroll: 'Desplazar {{t}}', desktop_press: 'Pulsar {{t}}',
    web_search: 'Buscar «{{t}}»', web_extract: 'Leer {{t}}', browser_open: 'Abrir {{t}} en el navegador',
    read_file: 'Leer {{t}}', write_file: 'Escribir {{t}}', edit_file: 'Editar {{t}}', list_dir: 'Mirar en {{t}}',
    run_command: 'Ejecutar {{t}}', update_plan: 'Actualizar el plan', recall: 'Buscar en la memoria', other: 'Usar {{tool}}',
  },
};

const de: Messages = {
  region: 'Arslan Island',
  idle: 'Bereit',
  running: '{{n}} laufen',
  learned: '+{{n}} Vorgehensweise',
  turn: 'Unterhaltung',
  job: 'Hintergrundarbeit',
  scheduled: 'Geplante Aufgabe',
  emptyTitle: 'Gerade läuft nichts',
  openArslan: 'Arslan öffnen',
  openConversation: 'Unterhaltung öffnen',
  finished: 'Fertig',
  finishedNoSummary: 'Fertig. Das Ergebnis steht in der Unterhaltung.',
  stoppedNeedsReview: 'Vorerst hier angehalten',
  stoppedNeedsReviewText: 'Das Arbeitslimit dieser Runde ist erreicht, oder du solltest erst draufschauen.',
  stoppedError: 'Mit einem Fehler angehalten',
  stoppedErrorText: 'Etwas ist schiefgegangen. Details stehen in der Unterhaltung.',
  stoppedPaused: 'Geplante Aufgabe pausiert',
  stoppedPausedText: 'Sie ist mehrmals hintereinander fehlgeschlagen und läuft erst wieder, wenn du sie einschaltest.',
  needsYou: 'Wartet auf dich',
  needsYouText: 'Arslan möchte etwas tun, das dein OK braucht.',
  wantsTo: 'Möchte',
  openToApprove: 'Zum Freigeben öffnen',
  close: 'Schließen',
  plan: 'Plan',
  stopHands: 'Stoppen',
  stoppedHands: 'Gestoppt',
  allow: 'Erlauben',
  decline: 'Ablehnen',
  openInArslan: 'In Arslan öffnen',
  riskyNote: 'Das kann löschen, senden oder bezahlen – erst in Arslan ansehen, dann erlauben.',
  answerFailed: 'Hier ließ sich nicht antworten. Öffne Arslan.',
  stopJob: 'Stoppen',
  stoppingJob: 'Wird gestoppt…',
  ask: { run_command: 'Einen Befehl ausführen', workspace_write: 'In deinen Ordner schreiben', schedule: 'Geplante Aufgabe anlegen', browser_site: 'Auf einer Website handeln', desktop_look: 'Eine App ansehen', desktop_app: 'In einer App handeln', desktop_risky: 'Ein Schritt, der löschen, senden oder bezahlen kann', mac_shortcut: 'Kurzbefehl ausführen', mac_script: 'AppleScript ausführen', other: 'Braucht dein OK' },
  step: {
    desktop_apps: 'Offene Apps auflisten', desktop_look: '{{t}} ansehen', desktop_click: '{{t}} klicken', desktop_type: 'In {{t}} tippen', desktop_select: 'In {{t}} auswählen', desktop_scroll: '{{t}} scrollen', desktop_press: '{{t}} drücken',
    web_search: 'Suche „{{t}}“', web_extract: '{{t}} lesen', browser_open: '{{t}} im Browser öffnen',
    read_file: '{{t}} lesen', write_file: '{{t}} schreiben', edit_file: '{{t}} bearbeiten', list_dir: 'In {{t}} schauen',
    run_command: '{{t}} ausführen', update_plan: 'Plan aktualisieren', recall: 'Im Gedächtnis suchen', other: '{{tool}} verwenden',
  },
};

const fr: Messages = {
  region: 'Arslan Island',
  idle: 'Au repos',
  running: '{{n}} en cours',
  learned: '+{{n}} pratique',
  turn: 'Conversation',
  job: 'Travail en arrière-plan',
  scheduled: 'Tâche planifiée',
  emptyTitle: 'Rien en cours pour l’instant',
  openArslan: 'Ouvrir Arslan',
  openConversation: 'Ouvrir la conversation',
  finished: 'Terminé',
  finishedNoSummary: 'Terminé. Le résultat est dans la conversation.',
  stoppedNeedsReview: 'Arrêté ici pour l’instant',
  stoppedNeedsReviewText: 'La limite de travail de cette passe est atteinte, ou il faut votre regard avant de continuer.',
  stoppedError: 'Arrêté par une erreur',
  stoppedErrorText: 'Un problème est survenu. Les détails sont dans la conversation.',
  stoppedPaused: 'Tâche planifiée en pause',
  stoppedPausedText: 'Elle a échoué plusieurs fois de suite et ne tournera plus tant que vous ne la réactivez pas.',
  needsYou: 'Vous attend',
  needsYouText: 'Arslan veut faire quelque chose qui demande votre accord.',
  wantsTo: 'Veut',
  openToApprove: 'Ouvrir pour approuver',
  close: 'Fermer',
  plan: 'Plan',
  stopHands: 'Arrêter',
  stoppedHands: 'Arrêté',
  allow: 'Autoriser',
  decline: 'Refuser',
  openInArslan: 'Ouvrir dans Arslan',
  riskyNote: 'Cela peut supprimer, envoyer ou payer : lisez-le dans Arslan avant d’autoriser.',
  answerFailed: 'Impossible de répondre ici. Ouvrez Arslan.',
  stopJob: 'Arrêter',
  stoppingJob: 'Arrêt…',
  ask: { run_command: 'Lancer une commande', workspace_write: 'Écrire dans votre dossier', schedule: 'Créer une tâche planifiée', browser_site: 'Agir sur un site web', desktop_look: 'Regarder une app', desktop_app: 'Agir dans une app', desktop_risky: 'Une étape qui peut supprimer, envoyer ou payer', mac_shortcut: 'Lancer un Raccourci', mac_script: 'Lancer un AppleScript', other: 'Il faut votre accord' },
  step: {
    desktop_apps: 'Lister les apps ouvertes', desktop_look: 'Regarder {{t}}', desktop_click: 'Cliquer {{t}}', desktop_type: 'Écrire dans {{t}}', desktop_select: 'Choisir dans {{t}}', desktop_scroll: 'Faire défiler {{t}}', desktop_press: 'Appuyer sur {{t}}',
    web_search: 'Rechercher « {{t}} »', web_extract: 'Lire {{t}}', browser_open: 'Ouvrir {{t}} dans le navigateur',
    read_file: 'Lire {{t}}', write_file: 'Écrire {{t}}', edit_file: 'Modifier {{t}}', list_dir: 'Regarder dans {{t}}',
    run_command: 'Exécuter {{t}}', update_plan: 'Mettre à jour le plan', recall: 'Chercher dans la mémoire', other: 'Utiliser {{tool}}',
  },
};

export const MESSAGES: Record<Lang, Messages> = { en, zh, ja, es, de, fr };
export type MessageKey = Exclude<keyof Messages, 'step' | 'ask'>;

export function pickLang(stored: string | null, navigatorLang: string | undefined): Lang {
  for (const raw of [stored, navigatorLang]) {
    const base = (raw || '').toLowerCase().split('-')[0];
    if ((LANGS as readonly string[]).includes(base)) return base as Lang;
  }
  return 'en';
}

const fill = (text: string, vars: Record<string, string | number>) =>
  text.replace(/\{\{(\w+)\}\}/g, (_, k) => String(vars[k] ?? ''));

export function t(lang: Lang, key: MessageKey, vars: Record<string, string | number> = {}): string {
  return fill(MESSAGES[lang][key] ?? MESSAGES.en[key], vars);
}

/** "Search “jobs in Shanghai”", "Read careers.example.com" — a step in words. */
export function stepText(lang: Lang, tool: string, target: string | null): string {
  const table = MESSAGES[lang].step as Record<string, string>;
  const known = table[tool];
  if (known && (target || !known.includes('{{t}}'))) return fill(known, { t: target ?? '' });
  return fill(table.other, { tool: tool.replace(/_/g, ' ') });
}

/** What a waiting card asks, in a few words (0.1.55 Island v2). */
export function askText(lang: Lang, kind: string): string {
  const table = MESSAGES[lang].ask as Record<string, string>;
  return table[kind] ?? table.other;
}
