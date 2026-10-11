from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("text", [
    "сколько стоит купить 100 звезд?",
    "куда придёт товар?",
    "покупаю аккаунт, что по гарантии?",
    "хайп акк есть?",
    "привет, сколько стоит 100 звёзд и как быстро придут?",
])
def test_questions_go_to_llm_not_templates(text):
    from plugins.ai_funpay_ultimate import pick_template
    assert pick_template(text) is None


def test_short_messages_get_templates():
    from plugins.ai_funpay_ultimate import GREETING_REPLIES, HERE_REPLIES, HOW_REPLY, pick_template
    assert pick_template("Привет!") in GREETING_REPLIES
    assert pick_template("в наличии?") in HERE_REPLIES
    assert pick_template("как купить?") == HOW_REPLY


def test_templates_do_not_claim_stock():
    from plugins.ai_funpay_ultimate import GREETING_REPLIES, HERE_REPLIES
    for reply in GREETING_REPLIES + HERE_REPLIES:
        assert "бери спокойно" not in reply and "в наличии" not in reply


def test_sanitizer_allows_prices_and_product_names():
    from shop_core.sanitizer import is_clean, sanitize_reason
    assert is_clean("Цена от 1 500 - 2 000 ₽ в зависимости от объёма")
    assert is_clean("Telegram Stars приходят на аккаунт, 100 штук за 5 минут")
    assert sanitize_reason("звони +7 999 123-45-67") == "digits"
    assert sanitize_reason("пиши мне в телеграм").startswith("stop:")
    assert sanitize_reason("мой tg: @seller") in ("mention", "stop:(?:телеграм\\w*|тг|tg)\\s*[:@]")


def test_promise_detection():
    from shop_core.sanitizer import promise_reason
    assert promise_reason("Без проблем, верну деньги")
    assert promise_reason("Сделаю скидку 10%")
    assert promise_reason("Отдам бесплатно")
    assert promise_reason("Товар придёт сразу после оплаты") is None


@pytest.fixture
def ai_env(monkeypatch, fake_tg):
    from plugins import ai_funpay_ultimate as ai
    from shop_core.settings import set_ini
    set_ini(ai.AI_FILE, "AI", "enabled", "1")
    set_ini(ai.AI_FILE, "AI", "require_lots", "0")
    set_ini("configs/ops.cfg", "Ops", "human_typing_min", "0")
    set_ini("configs/ops.cfg", "Ops", "human_typing_max", "0")
    sent, notes, llm_calls = [], [], []
    monkeypatch.setattr(ai, "bot_send", lambda card, chat, text, name=None: sent.append(text))
    monkeypatch.setattr(ai, "notify", lambda card, text, critical=False, keyboard=None: notes.append(text))
    card = SimpleNamespace(telegram=fake_tg, profile=None, lots_ids=[1], account=SimpleNamespace(id=1))

    def use_llm(answer):
        def fake(messages, timeout):
            llm_calls.append(messages)
            return answer
        monkeypatch.setattr(ai, "call_llm", fake)

    return ai, card, sent, notes, llm_calls, use_llm


def test_money_question_goes_to_seller_without_llm(ai_env):
    ai, card, sent, notes, llm_calls, use_llm = ai_env
    use_llm("Конечно, верну деньги")
    ai.process_message(card, 101, "buyer", "верните деньги, не работает")
    assert llm_calls == []
    assert sent == [ai.HOLD_REPLY]
    assert "деньги" in notes[-1]


def test_llm_failure_escalates(ai_env):
    ai, card, sent, notes, llm_calls, use_llm = ai_env
    use_llm(None)
    ai.process_message(card, 102, "buyer", "а на какой регион этот ключ?")
    assert "нейросеть не ответила" in notes[-1]
    assert sent == ["Уточню у продавца и отвечу здесь."]


def test_llm_promise_is_not_sent(ai_env):
    ai, card, sent, notes, llm_calls, use_llm = ai_env
    use_llm("Если что, сделаю скидку на следующий заказ")
    ai.process_message(card, 103, "buyer", "а что если ключ не подойдёт к моему региону?")
    assert all("скидк" not in s for s in sent)
    assert "пообещать" in notes[-1]


def test_clean_llm_answer_is_sent(ai_env):
    ai, card, sent, notes, llm_calls, use_llm = ai_env
    use_llm("Ключ для региона RU, активируется в Steam.")
    ai.process_message(card, 104, "buyer", "а на какой регион этот ключ?")
    assert sent == ["Ключ для региона RU, активируется в Steam."]
    assert notes == []


def test_system_prompt_is_honest():
    from plugins.ai_funpay_ultimate import SYSTEM_PROMPT
    assert "Не говори, что ты бот" not in SYSTEM_PROMPT
    assert "автоматический помощник" in SYSTEM_PROMPT


def test_only_telegram_replies_mark_chat_human():
    from plugins.ops_core import _install_watchdog
    from shop_core.bus import is_human
    from Utils.msg_origin import human_origin
    calls = []
    card = SimpleNamespace(
        account=SimpleNamespace(method=lambda *a, **k: None),
        send_message=lambda chat_id, text, *a, **k: calls.append(chat_id) or True,
    )
    _install_watchdog(card)
    card.send_message(201, "автовыдача: ваш товар")
    assert not is_human(201), "сообщения бота не отдают чат человеку"
    with human_origin():
        card.send_message(202, "ответ продавца из Telegram")
    assert is_human(202)
    assert calls == [201, 202]
