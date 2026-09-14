"""Product-owned runtime notices, separate from model/user-authored prose."""
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from server.db import session as db_session
from server.db.models import Setting


MESSAGES = {
    "en": {
        "proposal_handled": "This proposal has already been handled, or there is no pending proposal. Tell me what you would like to do next.",
        "round_incomplete": 'I didn\'t finish this one in a single round. Reply "continue" and I\'ll keep going — or narrow the scope a little for a faster answer.',
        "findings_header": "[Findings so far] (gathered this round, not yet written up)",
        "chat_miss": "Sorry, I didn't quite catch that — could you say it another way?",
        "correction": "Correction: I did not delegate any task, and nothing is running in the background. The answer above was my own response.",
        "named_correction": "Correction: my claim about assigning this to {name} was not true. I did not delegate any task this turn; the answer above was my own response. To involve {name}, mention them explicitly.",
        "no_tools_correction": "Correction: I do not have the tools needed to produce that file or data. My earlier completion claim was not true: I produced no such result and delegated no task. Please use an expert with the required capabilities.",
    },
    "zh": {
        "proposal_handled": "这个提案已经处理过了，或目前没有待处理的提案。直接告诉我接下来要做什么就好。",
        "round_incomplete": "这个任务这一轮还没做完。回复“继续”我就接着做;也可以把范围缩小一点,会更快。",
        "findings_header": "【阶段性发现】(本轮已查到的资料,尚未成稿)",
        "chat_miss": "抱歉,我刚没接住你的意思——能再说一次或换个说法吗?",
        "correction": "更正:本回合我没有派发任何任务,也没有任何东西正在后台运行——上面的内容是我自己作答的。",
        "named_correction": "更正:我刚才说交给 {name} 处理并不属实——本回合我没有派发任何任务,上面的内容是我自己作答的。需要真的交给 {name},直接点名它即可。",
        "no_tools_correction": "更正:我没有配备相应工具,无法自己产出这个文件或数据。刚才那段“已完成/已交付”的说法并不属实——本回合没有真正做出任何东西,也没有把任务交给谁。需要真的做出来,请改用配备相应能力的分身。",
    },
    "ja": {
        "proposal_handled": "この提案はすでに処理済みか、現在保留中の提案はありません。次に行いたいことを教えてください。",
        "round_incomplete": "このタスクは今回の応答では完了しませんでした。「続けて」と返信すると再開できます。範囲を絞ると、より早く回答できます。",
        "findings_header": "【これまでの調査結果】（今回収集した資料。最終回答は未作成）",
        "chat_miss": "すみません、意図を十分に理解できませんでした。別の言い方でもう一度教えていただけますか？",
        "correction": "訂正：タスクを委任しておらず、バックグラウンドで動作している処理もありません。上記は私自身が回答した内容です。",
        "named_correction": "訂正：{name} に依頼したという説明は事実ではありません。今回はタスクを委任しておらず、上記は私自身の回答です。{name} に依頼する場合は、明示的に指定してください。",
        "no_tools_correction": "訂正：そのファイルやデータを作成するためのツールがありません。先ほどの完了という説明は事実ではなく、成果物の作成もタスクの委任も行っていません。必要な機能を備えた専門家をご利用ください。",
    },
    "es": {
        "proposal_handled": "Esta propuesta ya se ha gestionado o no hay ninguna pendiente. Dime qué quieres hacer a continuación.",
        "round_incomplete": 'No he terminado esta tarea en este turno. Responde «continúa» para retomarla, o reduce el alcance para obtener una respuesta más rápida.',
        "findings_header": "[Hallazgos hasta ahora] (recopilados en este turno, aún sin redactar)",
        "chat_miss": "Lo siento, no he entendido bien lo que querías decir. ¿Puedes expresarlo de otra forma?",
        "correction": "Corrección: no he delegado ninguna tarea y no hay nada ejecutándose en segundo plano. La respuesta anterior era mía.",
        "named_correction": "Corrección: no era cierto que hubiera asignado esto a {name}. No he delegado ninguna tarea en este turno; la respuesta anterior era mía. Para involucrar a {name}, menciónalo explícitamente.",
        "no_tools_correction": "Corrección: no tengo las herramientas necesarias para producir ese archivo o esos datos. Mi afirmación anterior de haber terminado no era cierta: no he producido ese resultado ni delegado ninguna tarea. Usa un experto con las capacidades necesarias.",
    },
    "de": {
        "proposal_handled": "Dieser Vorschlag wurde bereits bearbeitet, oder es gibt keinen ausstehenden Vorschlag. Sag mir, was du als Nächstes tun möchtest.",
        "round_incomplete": 'Ich habe diese Aufgabe in dieser Runde nicht abgeschlossen. Antworte mit „Weiter“, um fortzufahren, oder grenze den Umfang für eine schnellere Antwort ein.',
        "findings_header": "[Bisherige Erkenntnisse] (in dieser Runde gesammelt, noch nicht ausgearbeitet)",
        "chat_miss": "Entschuldigung, ich habe dich nicht ganz verstanden. Kannst du es anders formulieren?",
        "correction": "Korrektur: Ich habe keine Aufgabe delegiert, und es läuft nichts im Hintergrund. Die obige Antwort stammt von mir selbst.",
        "named_correction": "Korrektur: Meine Aussage, dies an {name} übergeben zu haben, war nicht richtig. Ich habe in dieser Runde keine Aufgabe delegiert; die obige Antwort stammt von mir selbst. Wenn {name} mitwirken soll, erwähne den Namen ausdrücklich.",
        "no_tools_correction": "Korrektur: Mir fehlen die Werkzeuge, um diese Datei oder Daten zu erstellen. Meine vorherige Aussage, fertig zu sein, war nicht richtig: Ich habe dieses Ergebnis weder erstellt noch eine Aufgabe delegiert. Bitte nutze einen Experten mit den nötigen Fähigkeiten.",
    },
    "fr": {
        "proposal_handled": "Cette proposition a déjà été traitée, ou aucune proposition n’est en attente. Dis-moi ce que tu souhaites faire ensuite.",
        "round_incomplete": 'Je n’ai pas terminé cette tâche pendant ce tour. Réponds « continue » pour reprendre, ou réduis le périmètre pour obtenir une réponse plus rapidement.',
        "findings_header": "[Résultats recueillis] (rassemblés pendant ce tour, pas encore rédigés)",
        "chat_miss": "Désolé, je n’ai pas bien compris. Peux-tu le reformuler ?",
        "correction": "Correction : je n’ai délégué aucune tâche et rien ne s’exécute en arrière-plan. La réponse ci-dessus était la mienne.",
        "named_correction": "Correction : mon affirmation selon laquelle j’avais confié cela à {name} était fausse. Je n’ai délégué aucune tâche pendant ce tour ; la réponse ci-dessus était la mienne. Pour faire intervenir {name}, mentionne explicitement son nom.",
        "no_tools_correction": "Correction : je ne dispose pas des outils nécessaires pour produire ce fichier ou ces données. Mon affirmation précédente d’avoir terminé était fausse : je n’ai produit aucun résultat de ce type ni délégué de tâche. Utilise un expert doté des capacités nécessaires.",
    },
}


def normalize(locale):
    locale = {"English (US)": "en", "Chinese (Simplified)": "zh", "Japanese": "ja", "German": "de"}.get(locale, locale)
    code = str(locale or "en").replace("_", "-").split("-")[0].lower()
    return code if code in MESSAGES else "en"


async def selected_locale():
    from server.services import task_service
    runtime = task_service.current()
    if runtime is not None:
        return normalize(runtime.spec.locale)
    try:
        # Do not read/decrypt provider or other secret settings to choose copy.
        async with db_session.AsyncSessionLocal() as db:
            return normalize(await db.scalar(select(Setting.value).where(Setting.key == "language")))
    except SQLAlchemyError:
        return "en"  # A notice must still be available when settings cannot load.


def render(key, locale, **values):
    return MESSAGES[normalize(locale)][key].format(**values)


def has_findings(text):
    for copy in MESSAGES.values():
        header = copy["findings_header"]
        end = "】" if header.startswith("【") else "]"
        if header[:header.index(end) + 1] in (text or ""):
            return True
    return False


def is_round_incomplete(text):
    return any(copy["round_incomplete"] in text for copy in MESSAGES.values())
