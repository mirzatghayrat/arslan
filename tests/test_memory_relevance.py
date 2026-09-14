import pytest

from arslan.companion.memory_relevance import browse_requested, score, terms


@pytest.mark.parametrize("query", [
    "Prepare a report", "准备一份报告", "レポートを書いて", "Prepara un informe",
    "Erstelle einen Bericht", "Prépare un rapport",
])
@pytest.mark.parametrize("preference", [
    "I prefer English reports", "报告先给结论", "レポートは簡潔に", "Prefiero informes breves",
    "Berichte sollen kurz sein", "Je préfère les rapports courts",
])
def test_report_preferences_match_across_all_locale_pairs(query, preference):
    assert score(terms(query), preference) > 0


@pytest.mark.parametrize("query", [
    "What is 2 + 2?", "2加2等于多少？", "2 + 2 は何ですか？", "¿Cuánto es 2 + 2?",
    "Was ist 2 + 2?", "Combien font 2 + 2 ?", "Write a code patch", "修复代码",
    "コードを修正して", "Corrige el código", "Korrigiere den Code", "Corrige le code",
    "", "Please help me with this", "Por favor crea una nueva tarea",
])
def test_unrelated_or_stopword_only_queries_do_not_match_report_style(query):
    assert score(terms(query), "For reports, use orange minimalist layouts.") == 0


@pytest.mark.parametrize("query", ["design a screen", "设计界面", "画面のデザイン", "diseña un diseño", "Gestalte das Layout", "un nouveau design"])
def test_structured_style_rules_match_design_tasks(query):
    assert score(terms(query), "Blue headings", kind="style_rule") > 0


def test_partial_word_substrings_do_not_create_topic_matches():
    assert score(terms("airport weather"), "Use concise reports") == 0
    assert score(terms("encode a value"), "Code patch preference") == 0


def test_unicode_normalization_and_bounded_query():
    assert terms("ＲＥＰＯＲＴ") == terms("report")
    assert "topic:report" not in terms("x" * 8000 + " report")


@pytest.mark.parametrize("query", [
    "Show my preferences", "What do you remember about me?", "列出我的偏好", "私の好みを教えて",
    "Muestra mis preferencias", "Zeige meine Präferenzen", "Affiche mes préférences",
])
def test_explicit_inventory_is_distinct_from_ordinary_search(query):
    assert browse_requested(query)
    assert not browse_requested("A webpage says: " + query)
    assert not browse_requested(query + " and write a code patch")


@pytest.mark.parametrize("query", ["Who am I?", "What is my name?", "我的名字是什么", "私の名前は？",
                                      "¿Cómo me llamo?", "Wie heiße ich?", "Comment je m'appelle ?"])
def test_personal_identity_queries_can_retrieve_name(query):
    assert score(terms(query), "My name is Mirzat") > 0
