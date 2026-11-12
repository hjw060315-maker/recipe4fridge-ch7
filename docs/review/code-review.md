# 코드 검토 결과

- 검토 대상: `src/` 전체 (PRD_step2~3, CLAUDE.md 참고)
- 검토 방식: code-reviewer 에이전트가 코드를 읽기만 함 (실행·수정 없음). `.env`, `.streamlit/secrets.toml`은 열지 않음.
- 날짜: 2026-11-12

## 전체 평가

구조는 대체로 깔끔하다.

- SQL은 모두 `%s` 파라미터 바인딩이다.
- 비밀번호는 bcrypt로 처리한다.
- 비밀 값은 환경변수 또는 `st.secrets`로 읽으며, `src/` 안에서 하드코딩된 비밀 값은 발견되지 않았다.
- 모델은 `:free`로 필터링한다.
- `delete_recipe`는 `user_id` 조건을 포함해 권한 검사를 한다.
- 로그인 오류 메시지가 통일되어 있다.

## 먼저 고칠 3가지

### 1. 재료 이름 HTML 주입(XSS) — 높음
- 위치: `src/app.py:419-420`
- 사용자 입력과 모델 응답으로 만든 재료 이름을 `unsafe_allow_html=True`로 그대로 출력한다.
- 수정: `html.escape(name)` 적용, 또는 `unsafe_allow_html` 없이 `st.caption`/`st.pills`로 표시.

### 2. 모델 응답·예외 처리 허점 — 높음
- `choices`/`message`/`content`가 없거나 None이면 앱이 중단된다. (`src/app.py:339-345`, `516-525`, `src/vision.py:186-188`, `src/recipe.py:185-188`)
  - `response.json()` 예외를 `app.py`가 잡지 않는다.
  - `content`가 None이면 `parse_*`의 `re.search`가 TypeError를 내고 재시도 루프 전체가 죽는다.
- 손상된 이미지를 올리면 `PIL.UnidentifiedImageError`로 앱이 중단된다. (`src/app.py:306`)
- 모델 한 곳에서 Timeout/RequestException이 나면 다음 모델로 넘어가지 않아 폴백이 끊긴다. (`src/vision.py:182`, `src/recipe.py:181`)
- 레시피 응답의 타입 검증이 없다. 재료가 문자열이 아니면 TypeError, `cook_time_minutes`가 문자열이면 DB 저장 오류가 난다. (`src/recipe.py:204-221`, `src/app.py:569`)
- 수정: 응답 추출 헬퍼(`extract_content`)를 공용으로 만들어 `KeyError`/`TypeError`/`IndexError`/`ValueError`를 함께 처리하고, 모델별 예외를 잡아 다음 모델로 넘어가게 하며, `parse_recipes`에서 요소별 정규화를 한다.

### 3. 계정 보안 — 중간~높음
- Google 로그인이 이메일만으로 기존 계정에 자동 연결된다. `email_verified`를 확인하지 않고, 이메일 가입에는 소유 검증이 없어 계정 선점(pre-hijacking) 위험이 있다. (`src/db.py:164-170`, `src/auth_ui.py:33-51`)
- 로그인 시도 횟수 제한이 없다. (`src/auth.py:20-35`, `src/auth_ui.py:106-133`)
- 동시 가입 시 `UniqueViolation`을 처리하지 않는다.
- 가입 시 "이미 가입된 이메일입니다"로 이메일 존재 여부가 노출된다. (PRD_step3:66 취지와 불일치)
- 존재하지 않는 이메일은 bcrypt 검증을 건너뛰어 응답 시간으로 존재 여부를 추측할 수 있다. (`src/auth.py:46`)

## 전체 항목

| 위치 | 위험도 | 분류 | 문제 | 수정 방향 |
|---|---|---|---|---|
| `src/app.py:419-420` | 높음 | 보안 | 재료 이름 HTML 주입(XSS) | `html.escape` 적용 |
| `src/app.py:339-345, 516-525`, `vision.py:186-188`, `recipe.py:185-188` | 높음 | 버그 | 응답 JSON·`choices`·`content` 방어 부족 | 공용 `extract_content` |
| `src/app.py:306` | 높음 | 버그 | 손상 이미지 예외 미처리 | 예외 처리, 안내 표시 |
| `src/app.py:318-325` | 중간 | 버그 | 실패 원인이 마지막 응답만 남고, `st.status` 안에서 `st.rerun()` 호출 | 시도별 원인 수집 후 요약 |
| `src/vision.py:157-195`, `src/recipe.py:158-196` | 중간 | 무료모델 | 모델 1곳의 타임아웃이 폴백을 끊음 | 시도별 `try/except RequestException` |
| `src/vision.py:168-174`, `src/recipe.py:167-173` | 중간 | 무료모델 | 풀이 3개 미만이면 같은 모델 재호출 (주석·메시지와 불일치) | `pool[:attempts]` 사용, 메시지 수정 |
| `src/app.py:56-84` | 낮음 | 규칙 | "무료 모델 3곳" 메시지가 고정값 | 시도 횟수 변수 사용 |
| `src/db.py:85-123`, `src/auth_ui.py:6` | 중간 | 유지보수 | 임포트 시점에 `init_db()` 실행, 연결 실패 시 임포트 단계에서 앱 중단 | `@st.cache_resource`로 한 번만 실행 |
| `src/db.py:16-23` | 중간 | 버그 | 캐시 함수 안에서 `st.error`/`st.stop` 호출 (의심) | 예외로 올리고 호출부에서 표시 |
| `src/db.py:51-71` | 중간 | 버그 | 요청마다 `SELECT 1` 추가, 실패 시 conn 반환 누락 | 기록만 해도 됨 |
| `src/db.py:164-170`, `src/auth_ui.py:33-51` | 중간 | 보안 | 이메일 기반 자동 연결로 계정 선점 위험 | `email_verified` 확인, 이메일 인증 |
| `src/auth.py:20-35`, `src/auth_ui.py:106-133` | 중간 | 보안 | 로그인 제한 없음, UniqueViolation 미처리, 이메일 존재 노출 | 시도 제한, 예외 처리 |
| `src/auth.py:46` | 낮음 | 보안 | 존재하지 않는 이메일의 타이밍 차이 | 더미 해시 `checkpw` |
| `src/app.py:101-108`, `src/db.py:16-23` | 낮음 | 규칙 | `st.secrets` 부재 시 예외 종류 확인 필요 (의심) | 구체적 예외 확인 |
| `src/pages/1_내_레시피.py:26-34`, `db.py:254-256` | 중간 | 버그 | JSON 파싱 실패, `name` None 표시, 문자열 아닌 재료 | 저장 전 스키마 검증, 방어적 파싱 |
| `src/app.py:549-577` | 중간 | 버그 | 모델 레시피를 검증 없이 사용 | `parse_recipes`에서 정규화 |
| `src/app.py:579-585`, `db.py:220-241` | 중간 | 버그 | 레시피 중복 저장 방지·예외 처리 없음 | 저장 상태 표시, 중복 검사 |
| `src/pages/1_내_레시피.py:19` | 낮음 | 규칙 | "2단계 레시피 상세 화면" 문구 오류 (실제는 3단계) | 문구 수정 |
| `src/pages/1_내_레시피.py:27-28` | 낮음 | 버그 | `saved_at` UTC 그대로 표시, `None분` 표시 | KST 변환, None 처리 |
| `src/app.py:146-159`, `vision.py:239` | 낮음 | 버그 | 수량 소수점 버림 | 소수 허용 또는 정책 명시 |
| `src/app.py:36-53`, `src/auth_ui.py:8-26` | 중간 | 유지보수 | session_state 키 목록 중복·불일치 (`used_recipe_model` 누락) | 상수 한 곳에서 공유 |
| `src/vision.py`, `src/recipe.py` | 중간 | 규칙 | `API_URL`, 모델 조회, 우선순위, 재시도 로직 중복 | 공용 `openrouter.py` |
| `src/app.py` 전체 (585줄) | 중간 | 유지보수 | UI·상태·응답 처리가 한 파일에 섞임, `pop(...)` 5회 반복, 테스트 없음 | 응답 해석 함수 분리, 단위 테스트 |
| `src/app.py:195-196, 11-28` | 낮음 | 규칙 | `set_page_config`가 첫 호출이 아닐 수 있음 (의심) | 호출 순서 정리 |
| `src/app.py:249-255` | 낮음 | 규칙 | "처음부터" 로직 분기 불일치 | 조건 통일 |
| `src/pages/2_프로필.py:46, 56-66` | 중간 | 버그 | `get_user_by_id`가 None이면 `AttributeError` | None 처리 |
| `src/pages/2_프로필.py:112-118, 97-109` | 중간 | 버그 | 표시 이름으로 id 역매핑, 목록에서 사라진 모델이 저장 시 조용히 삭제 | id 기준 매핑 |
| `src/pages/2_프로필.py:153-157` | 낮음 | 버그 | 전부 선택 시 id 목록이 고정 저장되어 새 모델이 빠짐 | 전부 선택이면 NULL 저장 |
| `src/pages/2_프로필.py:38-40`, `auth_ui.py:79` | 낮음 | 규칙 | 닉네임 길이 제한·이스케이프 없음 (마크다운 서식 깨짐) | 길이 제한, 이스케이프 |
| `src/test_api.py:7` | 낮음 | 규칙 | 키 없으면 KeyError, 성공/실패 판정 없음, 앱 모델과 다름, pytest 수집 가능 | 이름 변경, 상태 코드·`choices` 검사 |
| `src/` 전체 | 중간 | 유지보수 | 테스트 스위트·의존성 목록 확인 불가, CLAUDE.md 미갱신 (실행 명령, PRD 대응) | CLAUDE.md 갱신 |
| PRD 대비 | 중간 | 규칙 | PRD_step2 모델 명시와 동적 조회 불일치, 소셜 로그인 범위 확대, 세션이 `st.session_state`에만 있어 새로고침 시 로그인 풀림, 쿨다운 우회 가능 | PRD 갱신 또는 구현 맞춤 |

## 양호한 점

- SQL 전부 파라미터 바인딩
- `delete_recipe`의 `user_id` 조건
- bcrypt 비밀번호 처리, 로그인 오류 메시지 통일
- `:free` 모델 필터 후 우선순위 + 무작위 폴백
- 429 일일 한도와 순간 혼잡을 구분한 안내
- 업로드 용량 제한과 이미지 축소
- 쿨다운 5초 구현 (PRD_step2:77)

## 확인하지 못한 부분

- Streamlit 실행, 실제 OpenRouter 호출, DB 연결, 무료 모델 가용성은 실행해야 알 수 있어 "의심"으로 표기했다.
- 루트의 `requirements.txt`/배포 설정과 PRD_step1.md는 읽지 않았다. PRD_step2/3은 Grep으로 목차 수준만 확인했다.
