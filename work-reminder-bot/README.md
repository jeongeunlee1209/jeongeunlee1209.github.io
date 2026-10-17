# 업무 리마인드 텔레그램 봇

거래처(카테고리)별 할 일을 관리하고, 평일 09:00 / 17:00(KST)에 알림을 보내는 개인용 봇입니다.

## 파일 구성
| 파일 | 설명 |
|---|---|
| `bot.py` | 명령어 처리, 정기 알림(JobQueue), 헬스체크 서버 |
| `db.py` | SQLite / PostgreSQL 저장소, 초기 카테고리·할 일 시드 |
| `.env.example` | 환경변수 예시 (`.env`로 복사해서 사용) |
| `Dockerfile` | 컨테이너 배포용 |

## 1. BotFather로 봇 만들기
1. 텔레그램에서 **@BotFather** 검색 → 대화 시작 → `/newbot`
2. 봇 표시 이름 입력 (예: `WIPCO 업무 리마인더`)
3. 봇 사용자명 입력 — 반드시 `bot`으로 끝나야 함 (예: `wipco_todo_bot`)
4. 발급된 **토큰**(`123456789:ABC...`)을 복사 → `.env`의 `BOT_TOKEN`에 입력
   - 토큰은 비밀번호와 같으므로 외부에 공유하지 마세요. 유출 시 BotFather에서 `/revoke`
5. (선택) `/setcommands` → 봇 선택 → 아래 붙여넣기 (입력창 자동완성용)
   ```
   add - 할 일 추가
   done - 완료 처리
   list - 미완료 조회
   edit - 내용 수정
   move - 카테고리 변경
   cat - 카테고리 목록/추가
   alias - 별칭 추가
   help - 도움말
   ```

## 2. 내 chat_id 확인
1. 만든 봇과 대화방을 열고 아무 메시지(예: `hi`)를 보냄
2. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates` 접속
3. 결과의 `"chat":{"id":123456789,...}` 숫자가 chat_id → `.env`의 `ALLOWED_CHAT_ID`에 입력
   - 대안: 텔레그램에서 **@userinfobot**에게 메시지를 보내면 내 ID를 알려줌

## 3. 로컬 실행 (테스트용)
```bash
cp .env.example .env        # 토큰, chat_id 입력
pip install -r requirements.txt
python bot.py
```
- `DATABASE_URL`을 비우면 `data/bot.db`(SQLite)에 저장됩니다.
- 첫 실행 시 초기 카테고리 7개와 할 일 13개가 자동 등록됩니다(최초 1회만).

## 4. 명령어
```
/add <카테고리|별칭> <내용>        예) /add 앰버그 화상회의 자료 송부
/done <번호> [번호 ...]            예) /done 3 5 7
/list  |  /list <카테고리|별칭>
/edit <번호> <새 내용>
/move <번호> <카테고리|별칭>
/cat  |  /cat add <이름> <별칭1,별칭2>   예) /cat add Leica 라이카,leica
/alias <카테고리|별칭> <별칭>       예) /alias zf 지앤에프
/person <카테고리|별칭> <이름1,이름2>  예) /person 앰버그 Felix,펠릭스
/pri <번호> [번호 ...]             우선 지정/해제 (토글)
/week                             이번 주 요약
/help
```
- 별칭은 대소문자·띄어쓰기를 무시합니다 (`Z + F` = `zf`).
- 카테고리를 못 찾으면 입력 전체를 `기타`에 저장하고 새 카테고리 생성 방법을 안내합니다.
- 첫 단어가 카테고리가 아니면 내용 속 **담당자 이름**으로 회사를 판별합니다 (예: `/add 나씨야 견적 회신` → Z+F). 초기 등록: Z+F — Naciye, 나씨야, Mathias, 마티아스 / Waites — Peter, 피터 / Mosaic — Sabina, Lynn, Dylan (`db.py`의 `SEED_CONTACTS`에서 추가 가능)
- 내용 앞에 `!`를 붙이면 우선 항목(❗)으로 등록되고, 알림·목록 맨 위 `🔥 우선 처리`에 표시됩니다 (예: `/add zf !견적 회신`).
- 여러 줄로 보내면 줄 단위로 모두 처리 후 결과를 한 번에 응답합니다.
- 허용된 chat_id 외의 메시지는 응답 없이 무시합니다.

### 공휴일 · 주간 요약
- 한국 공휴일(설·추석·대체공휴일 포함, `holidays` 라이브러리 기준)에는 알림을 보내지 않습니다. 끄기: `SKIP_HOLIDAYS=false`
- 주의 마지막 근무일 오후 알림 뒤에 **주간 요약**(카테고리별 완료/남음, 신규 등록, 7일 이상 경과 건수)을 별도 메시지로 보냅니다. 금요일이 공휴일이면 목요일에 발송. 끄기: `WEEKLY_SUMMARY=false`
- 정부가 임시로 지정하는 공휴일은 라이브러리 반영이 늦을 수 있습니다.

## 5. 알림 테스트 (1분 뒤로 설정)
`.env`에서 시간을 현재+1분, +2분으로 바꾸고 주말에도 울리도록 요일을 전체로 설정 후 재시작:
```
MORNING_TIME=14:31
EVENING_TIME=14:32
ALERT_DAYS=0,1,2,3,4,5,6
```
테스트 후 `09:00` / `17:00` / `0,1,2,3,4`로 원복.

## 6. 완료 기준 체크리스트
- [ ] `/add 앰버그 테스트 내용` → `[Amberg Technologies]`에 저장
- [ ] `/add 웨이츠 ...`, `/add zf ...`, `/add 아이콜드 ...` → 각각 올바른 카테고리
- [ ] `/cat add`, `/alias` 직후 새 별칭으로 `/add` 가능
- [ ] 여러 줄 명령어 → 모두 처리 + 요약 응답
- [ ] 오전 알림(미완료 목록, 등록일, 7일 경과 🔁) / 오후 알림(완료·미완료·요약) 수신
- [ ] 다른 계정에서 보낸 명령은 무시
- [ ] 재시작·재배포 후 데이터 유지

## 7. Docker 실행
```bash
docker build -t work-reminder-bot .
docker run -d --name todo-bot --env-file .env -v $(pwd)/data:/app/data --restart unless-stopped work-reminder-bot
```
- SQLite 사용 시 `-v` 볼륨(영구 디스크)이 있어야 데이터가 유지됩니다.

## 8. 무료 호스팅 배포
> 호스팅 + DB 조합은 비교 후 선택하여 이 섹션을 채울 예정입니다.

배포 시 공통 사항:
- 환경변수 `BOT_TOKEN`, `ALLOWED_CHAT_ID`, (`DATABASE_URL`)를 호스팅 설정 화면에 등록 (`.env`는 업로드 금지)
- 영구 디스크가 없는 호스팅 → 무료 PostgreSQL의 `DATABASE_URL` 사용
- 호스팅이 웹 포트 응답을 요구하면 `PORT` 환경변수 설정 → `/` 경로에 `ok` 응답
- 봇은 polling 방식이므로 **같은 토큰으로 동시에 2곳에서 실행하면 충돌**합니다. 배포 전 로컬 실행을 종료하세요.

## 9. 자동 테스트
```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q tests
```
텔레그램 서버 없이 명령어·알림·보안·데이터 유지를 검증합니다 (54개).
