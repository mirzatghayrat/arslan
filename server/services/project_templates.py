"""Level templates per project type (0.1.56 §2).

Like Jira / Linear status categories: the board's columns are fixed (Shaping / Doing /
Done), and every type's levels each belong to one of them. These are the starting point
of a draft (§3); the user edits them, and the model draft may adapt them.

Level names are the user's content once a project is created, so the template carries
them in the app's six languages and the draft is written in the user's language.
"""
from __future__ import annotations

LANGS = ("en", "zh", "ja", "es", "de", "fr")
BANDS = ("shaping", "doing", "done")

# key -> [(band, {lang: name})]
_L = lambda band, en, zh, ja, es, de, fr: (band, dict(zip(LANGS, (en, zh, ja, es, de, fr))))  # noqa: E731

TEMPLATES: dict[str, list[tuple[str, dict[str, str]]]] = {
    "game": [
        _L("shaping", "Idea", "点子", "アイデア", "Idea", "Idee", "Idée"),
        _L("shaping", "Prototype (find the fun)", "原型（找乐子）", "プロトタイプ（面白さを探す）", "Prototipo (buscar la diversión)", "Prototyp (den Spaß finden)", "Prototype (trouver le fun)"),
        _L("doing", "Vertical slice", "垂直切片", "バーティカルスライス", "Corte vertical", "Vertical Slice", "Tranche verticale"),
        _L("doing", "Production", "制作", "制作", "Producción", "Produktion", "Production"),
        _L("doing", "Beta", "Beta", "ベータ", "Beta", "Beta", "Bêta"),
        _L("doing", "Store prep", "上架准备", "ストア準備", "Preparar la tienda", "Store-Vorbereitung", "Préparer la boutique"),
        _L("done", "Launch", "上线", "リリース", "Lanzamiento", "Launch", "Lancement"),
    ],
    "app": [
        _L("shaping", "Problem and users", "想清楚问题和用户", "課題とユーザー", "Problema y usuarios", "Problem und Nutzer", "Problème et utilisateurs"),
        _L("shaping", "Prototype", "原型", "プロトタイプ", "Prototipo", "Prototyp", "Prototype"),
        _L("doing", "Core features", "核心功能", "コア機能", "Funciones clave", "Kernfunktionen", "Fonctions clés"),
        _L("doing", "Polish and test", "打磨与测试", "仕上げとテスト", "Pulir y probar", "Feinschliff und Tests", "Finition et tests"),
        _L("doing", "Store prep", "上架准备", "ストア準備", "Preparar la tienda", "Store-Vorbereitung", "Préparer la boutique"),
        _L("done", "Launch", "上线", "リリース", "Lanzamiento", "Launch", "Lancement"),
    ],
    "website": [
        _L("shaping", "Goal and readers", "目标和读者", "目的と読者", "Objetivo y lectores", "Ziel und Leser", "Objectif et lecteurs"),
        _L("shaping", "Structure and wireframe", "结构和线框", "構成とワイヤーフレーム", "Estructura y wireframe", "Struktur und Wireframe", "Structure et maquette"),
        _L("doing", "Visual design", "视觉稿", "ビジュアルデザイン", "Diseño visual", "Visuelles Design", "Design visuel"),
        _L("doing", "Build", "搭建", "構築", "Construir", "Bauen", "Construction"),
        _L("doing", "Content", "内容", "コンテンツ", "Contenido", "Inhalte", "Contenu"),
        _L("doing", "Pre-launch check", "上线前检查", "公開前チェック", "Revisión previa", "Check vor dem Start", "Vérification avant mise en ligne"),
        _L("done", "Launch", "上线", "公開", "Lanzamiento", "Launch", "Mise en ligne"),
    ],
    "research": [
        _L("shaping", "Question", "问题", "問い", "Pregunta", "Fragestellung", "Question"),
        _L("shaping", "Literature", "读文献", "文献調査", "Literatura", "Literatur", "Littérature"),
        _L("shaping", "Method", "定方法", "方法", "Método", "Methode", "Méthode"),
        _L("doing", "Data", "收数据", "データ収集", "Datos", "Daten", "Données"),
        _L("doing", "Analysis", "分析", "分析", "Análisis", "Analyse", "Analyse"),
        _L("doing", "Writing", "写作", "執筆", "Redacción", "Schreiben", "Rédaction"),
        _L("doing", "Revision", "修改", "改稿", "Revisión", "Überarbeitung", "Révision"),
        _L("done", "Submit / publish", "投稿 / 发表", "投稿・公開", "Enviar / publicar", "Einreichen / veröffentlichen", "Soumettre / publier"),
    ],
    "writing": [
        _L("shaping", "Topic and readers", "主题和读者", "テーマと読者", "Tema y lectores", "Thema und Leser", "Sujet et lecteurs"),
        _L("shaping", "Outline", "大纲", "アウトライン", "Esquema", "Gliederung", "Plan"),
        _L("doing", "First draft", "初稿", "初稿", "Primer borrador", "Erster Entwurf", "Premier jet"),
        _L("doing", "Revision", "修改", "改稿", "Revisión", "Überarbeitung", "Révision"),
        _L("doing", "Check sources", "核对引用", "出典の確認", "Revisar fuentes", "Quellen prüfen", "Vérifier les sources"),
        _L("done", "Final", "定稿发布", "完成稿", "Versión final", "Endfassung", "Version finale"),
    ],
    "video": [
        _L("shaping", "Topic", "选题", "テーマ", "Tema", "Thema", "Sujet"),
        _L("shaping", "Script", "脚本", "台本", "Guion", "Skript", "Script"),
        _L("doing", "Shoot / material", "拍摄 / 素材", "撮影・素材", "Grabar / material", "Dreh / Material", "Tournage / matière"),
        _L("doing", "Edit", "剪辑", "編集", "Edición", "Schnitt", "Montage"),
        _L("doing", "Subtitles and voice", "字幕配音", "字幕と音声", "Subtítulos y voz", "Untertitel und Ton", "Sous-titres et voix"),
        _L("done", "Publish", "发布", "公開", "Publicar", "Veröffentlichen", "Publication"),
    ],
    "skill": [
        _L("shaping", "Goal and method", "定目标和方法", "目標と方法", "Meta y método", "Ziel und Methode", "Objectif et méthode"),
        _L("shaping", "Baseline", "摸底", "現状把握", "Punto de partida", "Standortbestimmung", "Point de départ"),
        _L("doing", "Foundations", "打基础", "基礎", "Fundamentos", "Grundlagen", "Fondamentaux"),
        _L("doing", "Practice", "练习", "練習", "Práctica", "Üben", "Pratique"),
        _L("doing", "Real use", "实战", "実践", "Uso real", "Praxis", "Mise en pratique"),
        _L("done", "Test", "达标测试", "到達テスト", "Prueba", "Test", "Test"),
    ],
    "trip": [
        _L("shaping", "Destination and dates", "目的地和日期", "行き先と日程", "Destino y fechas", "Ziel und Daten", "Destination et dates"),
        _L("shaping", "Budget", "定预算", "予算", "Presupuesto", "Budget", "Budget"),
        _L("doing", "Book", "订机票酒店", "予約", "Reservar", "Buchen", "Réserver"),
        _L("doing", "Itinerary", "排行程", "旅程", "Itinerario", "Reiseplan", "Itinéraire"),
        _L("doing", "Prepare", "出行准备", "準備", "Preparar", "Vorbereiten", "Préparer"),
        _L("done", "Leave", "出发", "出発", "Salida", "Abreise", "Départ"),
    ],
    "job": [
        _L("shaping", "Direction", "定方向", "方向性", "Dirección", "Richtung", "Direction"),
        _L("shaping", "CV and portfolio", "简历和作品集", "履歴書とポートフォリオ", "CV y portafolio", "Lebenslauf und Portfolio", "CV et portfolio"),
        _L("doing", "Apply", "投递", "応募", "Postular", "Bewerben", "Candidater"),
        _L("doing", "Interview", "面试", "面接", "Entrevistas", "Vorstellungsgespräche", "Entretiens"),
        _L("done", "Offer", "拿到 offer", "内定", "Oferta", "Zusage", "Offre"),
    ],
    "other": [
        _L("shaping", "Think it through", "想清楚", "よく考える", "Pensarlo bien", "Durchdenken", "Bien réfléchir"),
        _L("shaping", "Try a version", "试一版", "試しに作る", "Probar una versión", "Eine Version probieren", "Essayer une version"),
        _L("doing", "Make it", "做出来", "作り上げる", "Hacerlo", "Umsetzen", "Le faire"),
        _L("doing", "Polish", "打磨", "仕上げ", "Pulir", "Feinschliff", "Peaufiner"),
        _L("done", "Hand it over", "交出去", "届ける", "Entregarlo", "Übergeben", "Le livrer"),
    ],
}

#: The `kind` a project had before 0.1.56 → the template it starts from.
KIND_TO_TEMPLATE = {"software": "app", "research": "research", "design": "website", "general": "other"}


def lang_of(lang: str | None) -> str:
    base = (lang or "en").split("-")[0].lower()
    return base if base in LANGS else "en"


def draft(template: str, finish_line: str = "", lang: str | None = None) -> list[dict]:
    """The deterministic draft (§3.1): the template's levels in the user's language, the
    finish line as the last level's clear condition. Works without any model."""
    key = template if template in TEMPLATES else "other"
    language = lang_of(lang)
    levels = [{"name": names[language], "band": band, "description": "", "clear_condition": "",
               "habit": False, "checkpoints": []} for band, names in TEMPLATES[key]]
    if finish_line.strip():
        levels[-1]["clear_condition"] = finish_line.strip()[:400]
    return levels
