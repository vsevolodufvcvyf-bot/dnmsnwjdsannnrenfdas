import io
import logging

from Utils.log_redact import install, redact

GOLDEN = "0123456789abcdef0123456789abcdef"
TG_TOKEN = "123456789:AAHfakeTokenValue_abcdefghijklmnopqrstu"


def _capture(logger_name: str, *args, exc: bool = False) -> str:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
    install(handler)
    parent = logging.getLogger(logger_name.split(".")[0])
    parent.setLevel(logging.DEBUG)
    parent.addHandler(handler)
    try:
        log = logging.getLogger(logger_name)
        if exc:
            try:
                raise RuntimeError(f"boom api_key=supersecret123 golden_key={GOLDEN}")
            except RuntimeError:
                log.debug("TRACEBACK", exc_info=True)
        else:
            log.info(*args)
    finally:
        parent.removeHandler(handler)
    return buf.getvalue()


def test_child_logger_is_redacted():
    out = _capture("FPC.Confirm", "panel add: api_key=abcdef1234567890")
    assert "abcdef1234567890" not in out
    assert "api_key=***" in out


def test_args_formatting_is_redacted():
    out = _capture("FunPayAPI.account", "cookie golden_key=%s", GOLDEN)
    assert GOLDEN not in out


def test_telegram_token_in_url():
    out = _capture("TGBot", f"Max retries exceeded with url: /bot{TG_TOKEN}/getUpdates")
    assert "AAHfakeTokenValue" not in out
    assert "123456789:***" in out


def test_traceback_is_redacted():
    out = _capture("FPC.Autoback", exc=True)
    assert "supersecret123" not in out
    assert GOLDEN not in out
    assert "RuntimeError" in out


def test_card_keeps_last_four_digits():
    assert redact("карта 2200 1234 5678 9012") == "карта ****9012"


def test_plain_business_text_untouched():
    text = "Заказ #ABCD1234 выдан, цена 1 500 ₽, лот 12345, keywords = накрутка"
    assert redact(text) == text


def test_real_logger_config_writes_redacted_file():
    from Utils.logger import LOGGER_NAMES, configure_logging
    before = {name: list(logging.getLogger(name).handlers) for name in LOGGER_NAMES + ["TeleBot"]}
    listener = configure_logging()
    try:
        logging.getLogger("FPC.AutoSMM").warning("panel: key=%s token=%s", "secretkey12345", TG_TOKEN)
    finally:
        listener.stop()
        for name, handlers in before.items():
            logging.getLogger(name).handlers = handlers
    text = open("logs/log.log", encoding="utf-8").read()
    assert "secretkey12345" not in text
    assert "AAHfakeTokenValue" not in text
    assert "panel: key=***" in text


def test_prefixed_keys():
    assert "sk-or-v1-abcdef1234567890" not in redact("key sk-or-v1-abcdef1234567890")
    assert "AIzaSyA1234567890abcdefghij" not in redact("AIzaSyA1234567890abcdefghij")
