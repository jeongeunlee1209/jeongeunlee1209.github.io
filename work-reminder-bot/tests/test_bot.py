"""완료 기준 기반 테스트: 텔레그램 서버 없이 명령어·알림·보안·영속성 검증."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import Chat, Message, Update

import bot
import db as dbmod
from db import DB, KST


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    path = tmp_path / "bot.db"
    monkeypatch.setattr(bot, "db", DB(f"sqlite:///{path}"))
    return path


def set_now(monkeypatch, dt):
    monkeypatch.setattr(dbmod, "now", lambda: dt)
    monkeypatch.setattr(bot, "now", lambda: dt)


def fake_ctx():
    return SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))


def sent_text(ctx):
    return "".join(c.args[1] for c in ctx.bot.send_message.call_args_list)


# ---------- 시드 ----------
def test_seed_categories_and_tasks():
    names = [c[1] for c in bot.db.categories()]
    assert names == ["Amberg Technologies", "Waites", "Mosaic", "Z+F", "ICOLD/Sisgeo", "사내", "기타"]
    assert len(bot.db.open_tasks()) == 13


# ---------- /add + 별칭 ----------
def test_add_amberg_korean_alias():
    r = bot.run_line("/add 앰버그 테스트 내용")
    assert "[Amberg Technologies] 테스트 내용" in r
    t = bot.db.get_task(14)
    assert t[2] == "Amberg Technologies" and t[3] == "테스트 내용"


@pytest.mark.parametrize("alias,expected", [
    ("웨이츠", "Waites"), ("zf", "Z+F"), ("Z+F", "Z+F"), ("Z + F", "Z+F"), ("아이콜드", "ICOLD/Sisgeo"),
    ("SISGEO", "ICOLD/Sisgeo"), ("Amberg", "Amberg Technologies"), ("슬랙", "사내"), ("ETC", "기타"),
    ("amberg technologies", "Amberg Technologies"),
])
def test_alias_case_and_space_insensitive(alias, expected):
    assert bot.db.find_category(alias)[1] == expected


def test_add_unknown_category_goes_to_etc_with_guide():
    r = bot.run_line("/add 라이카 견적 요청")
    assert "[기타] 라이카 견적 요청" in r
    assert "/cat add 라이카" in r


def test_add_usage_errors():
    assert "사용법" in bot.run_line("/add")
    assert "내용이 없습니다" in bot.run_line("/add 앰버그")


# ---------- /done /edit /move /list ----------
def test_done_multiple_and_invalid():
    r = bot.run_line("/done 1 2 999")
    assert "✅ #1" in r and "✅ #2" in r and "#999 없음" in r
    assert "이미 완료됨" in bot.run_line("/done 1")
    assert len(bot.db.open_tasks()) == 11
    assert "숫자" in bot.run_line("/done abc")


def test_edit_and_move():
    assert "✏️ #1" in bot.run_line("/edit 1 수정된 내용")
    assert bot.db.get_task(1)[3] == "수정된 내용"
    assert "[Waites]" in bot.run_line("/move 1 웨이츠")
    assert bot.db.get_task(1)[2] == "Waites"
    assert "찾을 수 없습니다" in bot.run_line("/move 1 없는카테고리")
    assert "#999 없음" in bot.run_line("/edit 999 x")


def test_list_all_and_by_category():
    r = bot.run_line("/list")
    assert "미완료 13건" in r and "📁 Mosaic" in r
    r = bot.run_line("/list zf")
    assert "📁 Z+F" in r and "Mosaic" not in r
    assert "찾을 수 없습니다" in bot.run_line("/list 없음")


def test_global_unique_numbers():
    ids = [t[0] for t in bot.db.open_tasks()]
    assert len(ids) == len(set(ids))


# ---------- /cat /alias ----------
def test_cat_add_and_alias_apply_immediately():
    r = bot.run_line("/cat add Leica 라이카,leica")
    assert "Leica" in r
    assert "[Leica]" in bot.run_line("/add 라이카 데모 요청")
    assert "레이카" in bot.run_line("/alias leica 레이카")
    assert "[Leica]" in bot.run_line("/add 레이카 두번째")
    assert "Leica: " in bot.run_line("/cat")


def test_cat_add_duplicate_and_alias_conflict():
    assert "이미 존재" in bot.run_line("/cat add 앰버그 x")
    r = bot.run_line("/alias 웨이츠 zf")
    assert "다른 카테고리에서 사용 중" in r
    assert bot.db.find_category("zf")[1] == "Z+F"


# ---------- 여러 줄 ----------
@pytest.mark.asyncio
async def test_multiline_summary():
    ctx = fake_ctx()
    text = "/add 웨이츠 브라켓 재발송\n/done 1 2\n\n/list zf\n잘못된 줄"
    upd = SimpleNamespace(effective_message=SimpleNamespace(text=text))
    await bot.on_message(upd, ctx)
    out = sent_text(ctx)
    assert "4개 명령 처리 결과" in out
    assert "[Waites] 브라켓 재발송" in out and "✅ #1" in out and "📁 Z+F" in out
    assert "명령어가 아닙니다" in out


def test_unknown_command_and_botname_suffix():
    assert "알 수 없는 명령어" in bot.run_line("/foo")
    assert "명령어 안내" in bot.run_line("/help@wipco_todo_bot")


# ---------- 알림 ----------
@pytest.mark.asyncio
async def test_morning_alert_dates_and_repeat_mark(monkeypatch):
    base = datetime(2026, 10, 15, 10, 0, tzinfo=KST)
    set_now(monkeypatch, base)
    bot.db.add_task(1, "오늘 등록")  # #14
    set_now(monkeypatch, base + timedelta(days=7, hours=-1))  # 10/22 09:00
    ctx = fake_ctx()
    await bot.morning_job(ctx)
    out = sent_text(ctx)
    assert "오늘의 할 일" in out and "📁 Amberg Technologies" in out
    assert "#14 오늘 등록 (10/15 등록) 🔁" in out


@pytest.mark.asyncio
async def test_morning_no_repeat_mark_before_7_days(monkeypatch):
    base = datetime(2026, 10, 15, 10, 0, tzinfo=KST)
    set_now(monkeypatch, base)
    bot.db.add_task(1, "최근 항목")
    set_now(monkeypatch, base + timedelta(days=6))
    ctx = fake_ctx()
    await bot.morning_job(ctx)
    assert "#14 최근 항목 (10/15 등록)\n" in sent_text(ctx)


@pytest.mark.asyncio
async def test_evening_alert_today_done_only(monkeypatch):
    set_now(monkeypatch, datetime(2026, 10, 14, 16, 0, tzinfo=KST))
    bot.run_line("/done 1")  # 어제 완료 → 제외
    set_now(monkeypatch, datetime(2026, 10, 15, 10, 0, tzinfo=KST))
    bot.run_line("/done 2 3")
    set_now(monkeypatch, datetime(2026, 10, 15, 17, 0, tzinfo=KST))
    ctx = fake_ctx()
    await bot.evening_job(ctx)
    out = sent_text(ctx)
    done_part = out.split("⏳")[0]
    assert "#2" in done_part and "#3" in done_part and "#1 " not in done_part
    assert "오늘 완료 2건 / 남은 항목 10건" in out


@pytest.mark.asyncio
async def test_long_message_is_split():
    for i in range(300):
        bot.db.add_task(1, f"긴 항목 {i} " + "가" * 30)
    ctx = fake_ctx()
    await bot.morning_job(ctx)
    calls = ctx.bot.send_message.call_args_list
    assert len(calls) > 1 and all(len(c.args[1]) <= 4096 for c in calls)


@pytest.mark.asyncio
async def test_schedule_weekdays_mon_to_fri():
    from telegram.ext import Application
    app = Application.builder().token("123456:TEST").build()
    await app.job_queue.start()
    try:
        for d in bot.ALERT_DAYS:  # 0=월 ... 4=금 각각 단독 스케줄 시 해당 요일 09:00에 실행되는지
            ptb_day = (d + 1) % 7
            assert ptb_day in bot.PTB_DAYS
            job = app.job_queue.run_daily(bot.morning_job, bot.MORNING_TIME, days=(ptb_day,))
            nt = job.next_t.astimezone(KST)
            assert nt.weekday() == d and (nt.hour, nt.minute) == (9, 0)
    finally:
        await app.job_queue.stop(wait=False)


def test_default_schedule_config():
    assert (bot.MORNING_TIME.hour, bot.EVENING_TIME.hour) == (9, 17)
    assert bot.ALERT_DAYS == (0, 1, 2, 3, 4)


# ---------- 보안 ----------
def _update(chat_id, text="/list"):
    msg = Message(message_id=1, date=datetime.now(KST), chat=Chat(chat_id, "private"), text=text)
    return Update(update_id=1, message=msg)


def test_only_allowed_chat_id_is_handled():
    from telegram.ext import MessageHandler, filters
    h = MessageHandler(filters.Chat(chat_id=bot.CHAT_ID) & filters.UpdateType.MESSAGE & filters.TEXT, bot.on_message)
    assert h.check_update(_update(111))
    assert not h.check_update(_update(222))


# ---------- 영속성 ----------
def test_data_persists_after_restart(fresh_db):
    bot.run_line("/cat add Leica 라이카")
    bot.run_line("/add 라이카 재시작 테스트")
    bot.run_line("/done 1")
    restarted = DB(f"sqlite:///{fresh_db}")  # 재시작 시뮬레이션
    assert restarted.find_category("라이카")[1] == "Leica"
    assert restarted.find_by_contact("나씨야")[0][1] == "Z+F"
    assert len(restarted.open_tasks()) == 13  # 시드 재삽입 없음 (13 - 1 + 1)
    assert restarted.get_task(1)[5] is not None


# ---------- 담당자 이름 ----------
@pytest.mark.parametrize("text", ["/add 나씨야 견적 회신 확인", "/add Naciye quote follow-up",
                                  "/add 견적 관련 마티아스에게 메일", "/add MATHIAS 데모 일정"])
def test_contact_name_routes_to_company(text):
    r = bot.run_line(text)
    assert "[Z+F]" in r and "담당자" in r
    assert bot.db.get_task(14)[3] == text.removeprefix("/add ")


def test_category_first_word_wins_over_contact():
    assert "[Waites]" in bot.run_line("/add 웨이츠 마티아스 소개 메일")


def test_person_command_and_conflict():
    assert "등록" in bot.run_line("/person 앰버그 Felix,펠릭스")
    assert "[Amberg Technologies]" in bot.run_line("/add 펠릭스 화상회의 링크 전달")
    assert "이미 등록됨" in bot.run_line("/person 웨이츠 마티아스")
    assert "👤" in bot.run_line("/cat")


def test_contacts_from_two_companies_go_to_etc():
    bot.run_line("/person 앰버그 펠릭스")
    r = bot.run_line("/add 펠릭스 마티아스 공동 미팅")
    assert "[기타]" in r and "여러 회사" in r


@pytest.mark.parametrize("text,company", [
    ("/add 피터에게 브라켓 발송 알림", "Waites"), ("/add Peter monthly call", "Waites"),
    ("/add Sabina 판매 예측 송부", "Mosaic"), ("/add lynn 여신 한도 회신", "Mosaic"),
    ("/add Dylan 운송장 확인", "Mosaic"),
])
def test_seed_contacts_waites_mosaic(text, company):
    assert f"[{company}]" in bot.run_line(text)
