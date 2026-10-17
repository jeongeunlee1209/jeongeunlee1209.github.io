"""저장소 계층: DATABASE_URL이 postgres:// 이면 PostgreSQL, 아니면 SQLite 사용."""
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DEFAULT_CATEGORY = "기타"

SEED_CATEGORIES = [
    ("Amberg Technologies", ["앰버그", "amberg", "엠버그"]),
    ("Waites", ["웨이츠", "waites"]),
    ("Mosaic", ["모자이크", "mosaic"]),
    ("Z+F", ["zf", "z+f", "제트엔에프"]),
    ("ICOLD/Sisgeo", ["아이콜드", "icold", "시스지오", "sisgeo"]),
    ("사내", ["사내", "내부", "대표님", "slack", "슬랙"]),
    (DEFAULT_CATEGORY, ["기타", "etc"]),
]

SEED_CONTACTS = [
    ("Z+F", ["Naciye", "나씨야", "Mathias", "마티아스"]),
    ("Waites", ["Peter", "피터"]),
    ("Mosaic", ["Sabina", "Lynn", "Dylan"]),
]

SEED_TASKS = [
    ("Mosaic", "데모 장비 운송장 번호 확인"),
    ("Mosaic", "웨이즈원 추가 카메라 2대 답변 확인"),
    ("Mosaic", "12개월 판매 예측 작성"),
    ("Mosaic", "여신 한도 전 제품 적용 회신 확인"),
    ("Z+F", "K-GEO 발표 세션 조정 결과 확인"),
    ("Z+F", "MMS 데모 일정(11/2~3) 공유"),
    ("Z+F", "SynCat/SDK 견적 검토 후 대표님 보고"),
    ("Waites", "필리핀 브라켓 발송"),
    ("Waites", "11월 말 행사 비용 산출"),
    ("Waites", "월간 활동 보고서 양식 작성 및 정례 콜 일정 제안"),
    ("ICOLD/Sisgeo", "초록 제출 (10/24 마감)"),
    ("Amberg Technologies", "화상회의 일정 확정"),
    ("Amberg Technologies", "대표님 우한 출장 일정 확인"),
]


def norm(s: str) -> str:
    """별칭 비교용: 공백 제거 + 소문자."""
    return "".join(s.split()).lower()


def now() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


class DB:
    def __init__(self, url: str):
        self.url = url
        self.pg = url.startswith(("postgres://", "postgresql://"))
        if not self.pg:
            self.path = url.removeprefix("sqlite:///")
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._init()

    # ---------- 공통 ----------
    def _conn(self):
        if self.pg:
            import psycopg
            return psycopg.connect(self.url)
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def q(self, sql, params=()):
        if self.pg:
            sql = sql.replace("?", "%s")
        conn = self._conn()  # 무료 클라우드 DB의 유휴 연결 끊김 대비: 매 요청마다 연결
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            conn.commit()
            return rows
        finally:
            conn.close()

    def _init(self):
        pk = "SERIAL PRIMARY KEY" if self.pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        self.q(f"CREATE TABLE IF NOT EXISTS categories (id {pk}, name TEXT NOT NULL UNIQUE)")
        self.q("CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, "
               "category_id INTEGER NOT NULL REFERENCES categories(id))")
        self.q(f"CREATE TABLE IF NOT EXISTS tasks (id {pk}, "
               "category_id INTEGER NOT NULL REFERENCES categories(id), "
               "content TEXT NOT NULL, created_at TEXT NOT NULL, done_at TEXT)")
        self.q("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.q("CREATE TABLE IF NOT EXISTS contacts (name TEXT PRIMARY KEY, display TEXT NOT NULL, "
               "category_id INTEGER NOT NULL REFERENCES categories(id))")
        if not self.q("SELECT 1 FROM meta WHERE key = 'seeded'"):
            for name, aliases in SEED_CATEGORIES:
                if not self.find_category(name):
                    self.add_category(name, aliases)
            for cat, content in SEED_TASKS:
                self.add_task(self.find_category(cat)[0], content)
            self.q("INSERT INTO meta (key, value) VALUES ('seeded', ?)", (now().isoformat(),))
        for cat, names in SEED_CONTACTS:  # 매 시작 시 적용 (이미 있으면 건너뜀) → 목록 추가 시 기존 DB에도 반영
            for n in names:
                self.add_contact(self.find_category(cat)[0], n)

    # ---------- 카테고리 ----------
    def find_category(self, text: str):
        """별칭/이름으로 카테고리 조회 → (id, name) 또는 None."""
        rows = self.q("SELECT c.id, c.name FROM aliases a JOIN categories c ON c.id = a.category_id "
                      "WHERE a.alias = ?", (norm(text),))
        return rows[0] if rows else None

    def add_category(self, name: str, aliases: list[str]):
        """카테고리 추가. 반환: (id, 충돌로 등록 못한 별칭 목록)."""
        if self.find_category(name):
            raise ValueError(f"'{name}'은(는) 이미 존재하는 카테고리/별칭입니다.")
        cid = self.q("INSERT INTO categories (name) VALUES (?) RETURNING id", (name,))[0][0]
        failed = [a for a in [name, *aliases] if a.strip() and not self.add_alias(cid, a) and norm(a) != norm(name)]
        return cid, failed

    def add_alias(self, cid: int, alias: str) -> bool:
        """별칭 추가. 다른 카테고리가 이미 쓰는 별칭이면 False."""
        key = norm(alias)
        owner = self.q("SELECT category_id FROM aliases WHERE alias = ?", (key,))
        if owner:
            return owner[0][0] == cid
        self.q("INSERT INTO aliases (alias, category_id) VALUES (?, ?)", (key, cid))
        return True

    def categories(self):
        """[(id, name, [alias, ...], [담당자, ...]), ...]"""
        cats = self.q("SELECT id, name FROM categories ORDER BY id")
        aliases = self.q("SELECT category_id, alias FROM aliases ORDER BY alias")
        contacts = self.q("SELECT category_id, display FROM contacts ORDER BY display")
        return [(cid, name, [a for c, a in aliases if c == cid], [d for c, d in contacts if c == cid])
                for cid, name in cats]

    # ---------- 담당자(사람 이름) ----------
    def add_contact(self, cid: int, name: str) -> bool:
        """담당자 이름 등록. 다른 카테고리에 이미 있으면 False."""
        key = norm(name)
        owner = self.q("SELECT category_id FROM contacts WHERE name = ?", (key,))
        if owner:
            return owner[0][0] == cid
        self.q("INSERT INTO contacts (name, display, category_id) VALUES (?, ?, ?)", (key, name.strip(), cid))
        return True

    def find_by_contact(self, text: str):
        """내용에 포함된 담당자 이름 검색 → [(category_id, category_name, display), ...] (긴 이름 우선)."""
        key = norm(text)
        rows = self.q("SELECT t.name, c.id, c.name, t.display FROM contacts t "
                      "JOIN categories c ON c.id = t.category_id")
        return [(cid, cname, disp) for n, cid, cname, disp in sorted(rows, key=lambda r: -len(r[0])) if n in key]

    # ---------- 할 일 ----------
    _SELECT = ("SELECT t.id, c.id, c.name, t.content, t.created_at, t.done_at "
               "FROM tasks t JOIN categories c ON c.id = t.category_id ")

    def add_task(self, cid: int, content: str) -> int:
        return self.q("INSERT INTO tasks (category_id, content, created_at) VALUES (?, ?, ?) RETURNING id",
                      (cid, content, now().isoformat()))[0][0]

    def get_task(self, tid: int):
        rows = self.q(self._SELECT + "WHERE t.id = ?", (tid,))
        return rows[0] if rows else None

    def mark_done(self, tid: int):
        self.q("UPDATE tasks SET done_at = ? WHERE id = ? AND done_at IS NULL", (now().isoformat(), tid))

    def edit_task(self, tid: int, content: str):
        self.q("UPDATE tasks SET content = ? WHERE id = ?", (content, tid))

    def move_task(self, tid: int, cid: int):
        self.q("UPDATE tasks SET category_id = ? WHERE id = ?", (cid, tid))

    def open_tasks(self, cid: int | None = None):
        if cid is None:
            return self.q(self._SELECT + "WHERE t.done_at IS NULL ORDER BY c.id, t.id")
        return self.q(self._SELECT + "WHERE t.done_at IS NULL AND c.id = ? ORDER BY t.id", (cid,))

    def done_between(self, start: datetime, end: datetime):
        return self.q(self._SELECT + "WHERE t.done_at >= ? AND t.done_at <= ? ORDER BY c.id, t.id",
                      (start.isoformat(), end.isoformat()))
