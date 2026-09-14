"""Local lexical fallback for memory relevance; never a permission decision.

No model, network or downloaded index is required. Small multilingual aliases
cover common work nouns; this is not a semantic translator or a claim that every
paraphrase is recognized. A miss returns no memory, not the whole eligible store.
"""
import re
import unicodedata


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in unicodedata.normalize("NFKD", value)
                   if not unicodedata.combining(char))


_STOP = frozenset(_normalize("""
a an the this that these those i me my mine you your yours we our us they their
is are was were be been being am do does did have has had can could will would
shall should may might must it its and or but of for to from in on at by with
without about as into only not no yes what which who when where why how please
use using used prefer preference preferences remember remembered want need needs
make create write start new next another current one task tasks work help tell
mi mis me yo tu tus su sus el la los las un una unos unas de del al en por para
con sin y o que como es son ser estar este esta esto favor usa usar hacer haz
crear escribe escribir nuevo nueva tarea tareas quiero necesito
le la les un une des du de au aux en pour par avec sans et ou ce cette ces est
sont etre je moi mon ma mes tu ton ta tes vous votre vos nous notre nos que quoi
quel quelle comment veuillez utilise utiliser ecris ecrire creer nouveau nouvelle
tache taches prefere preferences
der die das ein eine einer eines einem einen den dem des und oder fur von zu zum
zur mit ohne in auf an ist sind sein ich mir mein meine du dein deine sie ihr
wir unser uns bitte nutze nutzen verwende verwenden schreibe schreiben erstelle
erstellen neu neue neuen aufgabe aufgaben was wie welche welcher
请问 请你 请帮 帮我 帮忙 可以 能否 需要 想要 希望 现在 这次 一次 一个 一份
一下 这个 那个 我的 你的 我们 你们 使用 生成 创建 新建 开始 任务 内容 工作
""").split())

_ALIASES = {
    "report": "report reports bericht berichte berichten rapport rapports informe informes 报告 報告 レポート",
    "documentation": "documentation documentations docs document documents dokumentation dokumentationen dokument dokumente documento documentos documentation 文档 文件 ドキュメント 文書",
    "design": "design designs designing layout layouts color colors colour colours style styles styling stylebook diseño diseños diseno disenos couleur couleurs estilo estilos farbe farben gestaltung gestalten 设计 設計 风格 風格 配色 布局 佈局 デザイン レイアウト スタイル",
    "code": "code codes coding patch patches refactor refactoring codigo codigos codieren programmieren quellcode 代码 代碼 编程 編程 补丁 補丁 コード パッチ リファクタリング",
    "summary": "summary summaries summarize summarise summarizing summarising resume resumes resumir resumen resúmenes zusammenfassung zusammenfassungen zusammenfassen 总结 總結 摘要 要約 まとめ",
    "review": "review reviews reviewing revision revisions reviser revisionen relecture revoir revue 审查 審查 评审 評審 レビュー",
    "answer": "answer answers reply replies response responses responder respuesta respuestas reponse reponses repondre antwort antworten 回答 回复 回覆 返答 返信",
    "research": "research researching recherche recherches investigar investigacion recherche forschung 研究 调研 調研 調査",
    "identity": "name names nickname nicknames nombre nombres nom noms namen spitzname 名字 姓名 名前",
}
_ALIAS_WORDS = {word: f"topic:{topic}" for topic, aliases in _ALIASES.items()
                for word in _normalize(aliases).split()}
_CJK_ALIASES = {word: topic for word, topic in _ALIAS_WORDS.items()
                if any(ord(char) > 0x3000 for char in word)}

_BROWSE = re.compile(
    r"(?:please )?(?:list|show)(?: all)? my(?: saved| confirmed)? (?:memories|preferences)"
    r"|what do you (?:know|remember) about me"
    r"|(?:请)?(?:列出|显示|展示)(?:所有)?我的(?:全部|已保存|已确认)?(?:记忆|偏好)"
    r"|你(?:记得|了解|知道)我(?:什么|哪些事情)"
    r"|私の(?:保存された)?(?:記憶|好み)を(?:すべて)?(?:表示して|教えて)"
    r"|(?:muestra|enumera)(?: todas)? mis (?:preferencias|memorias)(?: guardadas)?"
    r"|(?:zeige|liste)(?: alle)? meine (?:erinnerungen|praferenzen)(?: auf)?"
    r"|(?:montre|affiche|liste)(?: toutes)? mes (?:preferences|souvenirs)",
)


def browse_requested(query: str) -> bool:
    """An explicit personal-memory inventory, not an empty-query fallback.

    Full-match only: quoted webpage prose or appended instructions do not turn
    into an inventory request. This still grants no scope/privacy permission.
    """
    return bool(_BROWSE.fullmatch(_normalize(query).strip().rstrip(".!?。！？")))


def terms(value: str) -> frozenset[str]:
    value = _normalize(value[:8000])
    words = {word for word in re.findall(r"[^\W_]{2,}", value)
             if word not in _STOP and not word.isdigit()}
    # Unicode61-style word matching alone cannot segment unspaced Chinese text.
    words.update(value[i:i + 2] for i in range(len(value) - 1)
                 if "\u3400" <= value[i] <= "\u9fff" and "\u3400" <= value[i + 1] <= "\u9fff"
                 and value[i:i + 2] not in _STOP)
    words.update(_ALIAS_WORDS[word] for word in tuple(words) if word in _ALIAS_WORDS)
    words.update(topic for word, topic in _CJK_ALIASES.items() if word in value)
    if re.fullmatch(r"(?:who am i|como me llamo|wie hei(?:ss|ß)e ich|comment je m.appelle)",
                    value.strip(" ¿¡?？.!")):
        words.add("topic:identity")
    return frozenset(words)


def score(query_terms: frozenset[str], content: str, *, kind: str = "preference") -> int:
    content_terms = terms(content)
    if kind == "style_rule":
        content_terms = content_terms | {"topic:design"}
    return len(query_terms & content_terms)
