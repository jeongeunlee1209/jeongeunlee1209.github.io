"""업무 리마인드 텔레그램 봇 (python-telegram-bot v21, JobQueue)."""
import logging
import os
import threading
from datetime import datetime, time
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from db import DB, DEFAULT_CATEGORY, KST, now

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["ALLOWED_CHAT_ID"])
db = DB(os.getenv("DATABASE_URL", "sqlite:///data/bot.db"))


def _parse_time(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m, tzinfo=KST)


MORNING_TIME = _parse_time(os.getenv("MORNING_TIME", "09:00"))
EVENING_TIME = _parse_time(os.getenv("EVENING_TIME", "17:00"))
ALERT_DAYS = tuple(int(d) for d in os.getenv("ALERT_DAYS", "0,1,2,3,4").split(","))  # 0=월 ... 6=일
WEEKDAY_KO = "월화수목금토일"

HELP = """📖 명령어 안내
/add <카테고리|별칭> <내용> : 할 일 추가
/done <번호> [번호 ...] : 완료 처리
/list : 미완료 전체 조회
/list <카테고리|별칭> : 해당 카테고리만 조회
/edit <번호> <새 내용> : 내용 수정
/move <번호> <카테고리|별칭> : 카테고리 변경
/cat : 카테고리·별칭 목록
/cat add <카테고리명> <별칭1,별칭2,...> : 카테고리 추가
/alias <카테고리|별칭> <별칭> : 별칭 추가
/help : 도움말

※ 여러 줄로 명령어를 보내면 순서대로 모두 처리합니다."""


# ---------- 포맷 ----------
def fmt_task(t, with_date=True) -> str:
    tid, _, _, content, created, _ = t
    if not with_date:
        return f"  #{tid} {content}"
    c = datetime.fromisoformat(created)
    repeat = " 🔁" if (now().date() - c.date()).days >= 7 else ""
    return f"  #{tid} {content} ({c.month}/{c.day} 등록){repeat}"


def fmt_grouped(tasks, with_date=True) -> str:
    lines, current = [], None
    for t in tasks:
        if t[2] != current:
            current = t[2]
            lines.append(f"\n📁 {current}")
        lines.append(fmt_task(t, with_date))
    return "\n".join(lines).lstrip("\n")


def _ids(text: str):
    return [int(x.lstrip("#")) for x in text.replace(",", " ").split()]


# ---------- 명령어 (문자열 인자 → 응답 문자열) ----------
def cmd_add(args: str) -> str:
    parts = args.split(maxsplit=1)
    if not parts:
        return "사용법: /add <카테고리|별칭> <내용>"
    cat = db.find_category(parts[0])
    if cat:
        if len(parts) < 2:
            return "내용이 없습니다. 사용법: /add <카테고리|별칭> <내용>"
        tid = db.add_task(cat[0], parts[1])
        return f"➕ #{tid} [{cat[1]}] {parts[1]}"
    # 일치하는 카테고리 없음 → 첫 단어 포함 전체를 '기타'에 저장
    etc = db.find_category(DEFAULT_CATEGORY)
    tid = db.add_task(etc[0], args)
    return (f"➕ #{tid} [{etc[1]}] {args}\n"
            f"⚠️ '{parts[0]}' 카테고리를 찾지 못해 '{DEFAULT_CATEGORY}'에 저장했습니다.\n"
            f"새 카테고리로 만들려면: /cat add {parts[0]} <별칭1,별칭2>\n"
            f"이후 이동: /move {tid} {parts[0]}")


def cmd_done(args: str) -> str:
    try:
        ids = _ids(args)
    except ValueError:
        return "번호는 숫자로 입력해 주세요. 예: /done 3 5"
    if not ids:
        return "사용법: /done <번호> [번호 ...]"
    out = []
    for tid in ids:
        t = db.get_task(tid)
        if not t:
            out.append(f"❓ #{tid} 없음")
        elif t[5]:
            out.append(f"☑️ #{tid} 이미 완료됨")
        else:
            db.mark_done(tid)
            out.append(f"✅ #{tid} [{t[2]}] {t[3]}")
    return "\n".join(out)


def cmd_list(args: str) -> str:
    if args:
        cat = db.find_category(args)
        if not cat:
            return f"❓ '{args}' 카테고리를 찾을 수 없습니다. (/cat 으로 확인)"
        tasks = db.open_tasks(cat[0])
        return fmt_grouped(tasks) if tasks else f"[{cat[1]}] 미완료 항목이 없습니다."
    tasks = db.open_tasks()
    return f"📋 미완료 {len(tasks)}건\n\n{fmt_grouped(tasks)}" if tasks else "미완료 항목이 없습니다. 🎉"


def cmd_edit(args: str) -> str:
    parts = args.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].lstrip("#").isdigit():
        return "사용법: /edit <번호> <새 내용>"
    tid = int(parts[0].lstrip("#"))
    if not db.get_task(tid):
        return f"❓ #{tid} 없음"
    db.edit_task(tid, parts[1])
    return f"✏️ #{tid} → {parts[1]}"


def cmd_move(args: str) -> str:
    parts = args.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].lstrip("#").isdigit():
        return "사용법: /move <번호> <카테고리|별칭>"
    tid = int(parts[0].lstrip("#"))
    if not db.get_task(tid):
        return f"❓ #{tid} 없음"
    cat = db.find_category(parts[1])
    if not cat:
        return f"❓ '{parts[1]}' 카테고리를 찾을 수 없습니다. (/cat 으로 확인)"
    db.move_task(tid, cat[0])
    return f"🔀 #{tid} → [{cat[1]}]"


def cmd_cat(args: str) -> str:
    if not args:
        lines = ["🗂 카테고리 · 별칭"]
        for _, name, aliases in db.categories():
            lines.append(f"• {name}: {', '.join(aliases)}")
        return "\n".join(lines)
    sub, _, rest = args.partition(" ")
    if sub.lower() != "add":
        return "사용법: /cat 또는 /cat add <카테고리명> <별칭1,별칭2,...>"
    name, _, alias_text = rest.strip().partition(" ")
    if not name:
        return "사용법: /cat add <카테고리명> <별칭1,별칭2,...>"
    aliases = [a.strip() for a in alias_text.split(",") if a.strip()]
    try:
        _, failed = db.add_category(name, aliases)
    except ValueError as e:
        return f"⚠️ {e}"
    msg = f"🆕 카테고리 '{name}' 추가 (별칭: {', '.join(aliases) or '없음'})"
    if failed:
        msg += f"\n⚠️ 다른 카테고리에서 사용 중이라 제외된 별칭: {', '.join(failed)}"
    return msg


def cmd_alias(args: str) -> str:
    cat_text, _, alias_text = args.partition(" ")
    aliases = [a.strip() for a in alias_text.split(",") if a.strip()]
    if not cat_text or not aliases:
        return "사용법: /alias <카테고리|별칭> <별칭>"
    cat = db.find_category(cat_text)
    if not cat:
        return f"❓ '{cat_text}' 카테고리를 찾을 수 없습니다. (/cat 으로 확인)"
    ok = [a for a in aliases if db.add_alias(cat[0], a)]
    bad = [a for a in aliases if a not in ok]
    msg = f"🏷 [{cat[1]}] 별칭 추가: {', '.join(ok)}" if ok else ""
    if bad:
        msg += f"\n⚠️ 다른 카테고리에서 사용 중: {', '.join(bad)}"
    return msg.strip()


COMMANDS = {
    "add": cmd_add, "done": cmd_done, "list": cmd_list, "edit": cmd_edit, "move": cmd_move,
    "cat": cmd_cat, "alias": cmd_alias, "help": lambda _: HELP, "start": lambda _: HELP,
}


def run_line(line: str) -> str:
    if not line.startswith("/"):
        return f"⚠️ 명령어가 아닙니다: {line}"
    head, _, args = line.partition(" ")
    name = head[1:].split("@")[0].lower()
    fn = COMMANDS.get(name)
    if not fn:
        return f"⚠️ 알 수 없는 명령어: /{name} (/help 참고)"
    try:
        return fn(args.strip())
    except Exception as e:  # 한 줄 실패가 나머지 처리를 막지 않도록
        log.exception("command failed: %s", line)
        return f"❌ 처리 오류: {line} ({e})"


# ---------- 전송 ----------
async def send(bot, text: str):
    """텔레그램 4096자 제한 대응: 줄 단위로 나눠 전송."""
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 4000:
            await bot.send_message(CHAT_ID, chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await bot.send_message(CHAT_ID, chunk)


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = [l.strip() for l in (update.effective_message.text or "").splitlines() if l.strip()]
    results = [run_line(l) for l in lines]
    if len(results) == 1:
        reply = results[0]
    else:
        reply = f"📋 {len(results)}개 명령 처리 결과\n\n" + "\n\n".join(
            f"{i}) {line}\n{r}" for i, (line, r) in enumerate(zip(lines, results), 1))
    await send(ctx.bot, reply)


# ---------- 정기 알림 ----------
def _today_label() -> str:
    n = now()
    return f"{n.month}/{n.day}({WEEKDAY_KO[n.weekday()]})"


async def morning_job(ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.open_tasks()
    body = fmt_grouped(tasks) if tasks else "미완료 항목이 없습니다. 🎉"
    await send(ctx.bot, f"☀️ {_today_label()} 오늘의 할 일 ({len(tasks)}건)\n\n{body}")


async def evening_job(ctx: ContextTypes.DEFAULT_TYPE):
    end = now()
    done = db.done_between(end.replace(hour=0, minute=0, second=0), end)
    remaining = db.open_tasks()
    text = (f"🌙 {_today_label()} 업무 마감 정리\n\n"
            f"✅ 오늘 완료한 항목\n{fmt_grouped(done, with_date=False) if done else '  없음'}\n\n"
            f"⏳ 미완료 항목\n{fmt_grouped(remaining) if remaining else '  없음 🎉'}\n\n"
            f"━━━━━━━━━━\n오늘 완료 {len(done)}건 / 남은 항목 {len(remaining)}건")
    await send(ctx.bot, text)


# ---------- 헬스체크 (PORT가 지정된 호스팅용) ----------
def start_health_server(port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("health server on :%s", port)


def main():
    if os.getenv("PORT"):
        start_health_server(int(os.environ["PORT"]))
    app = Application.builder().token(BOT_TOKEN).build()
    # 허용된 chat_id의 새 텍스트 메시지만 처리 (그 외는 무시)
    app.add_handler(MessageHandler(
        filters.Chat(chat_id=CHAT_ID) & filters.UpdateType.MESSAGE & filters.TEXT, on_message))
    app.job_queue.run_daily(morning_job, MORNING_TIME, days=ALERT_DAYS, name="morning")
    app.job_queue.run_daily(evening_job, EVENING_TIME, days=ALERT_DAYS, name="evening")
    log.info("bot started: morning=%s evening=%s days=%s", MORNING_TIME, EVENING_TIME, ALERT_DAYS)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
