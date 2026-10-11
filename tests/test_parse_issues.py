import logging
import time


def test_report_skipped_warns_once_and_records(caplog):
    from FunPayAPI import account as acc
    acc.PARSE_ISSUES.clear()
    acc._PARSE_WARNED.clear()
    with caplog.at_level(logging.DEBUG, logger="FunPayAPI.account"):
        acc._report_skipped("заказы в продажах", 3, 10)
        acc._report_skipped("заказы в продажах", 4, 10)
        acc._report_skipped("заказы в продажах", 0, 10)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "поменял вёрстку" in warnings[0].getMessage()
    ts, skipped, total = acc.PARSE_ISSUES["заказы в продажах"]
    assert (skipped, total) == (4, 10)


def test_clinic_shows_recent_parse_issues():
    from FunPayAPI import account as acc
    from plugins.clinic import parse_issue_lines
    acc.PARSE_ISSUES.clear()
    acc.PARSE_ISSUES["лоты в профиле"] = (time.time(), 2, 5)
    acc.PARSE_ISSUES["старое"] = (time.time() - 3 * 86400, 1, 1)
    lines = parse_issue_lines()
    assert len(lines) == 1 and "2 из 5" in lines[0]
