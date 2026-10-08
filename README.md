# 📡 Hospital Bid Radar

제약회사 영업·BD·경영진을 위한 **AI 기반 병원 입찰 영업 기회 발굴 플랫폼**.
나라장터(조달청) 입찰공고·낙찰·계약 데이터를 매일 수집해 병원 단위로 분석하고,
**Opportunity Score · Next Action · 이메일 Daily Report · 즉시 알림 · AI Copilot** 으로
"어느 병원을, 언제, 무엇을 하러 가야 하는가" 를 시스템이 먼저 알려줍니다 (Push 중심).

> 전체 설계(아키텍처·ERD·데이터 흐름·Azure·보안·운영·로드맵)는 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** 참고.

## 빠른 시작 (키 없이 데모 실행)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                      # AUTH_DISABLED=true, 데이터는 가상 데모
streamlit run app.py
```
Supabase 가 설정되지 않으면 **가상 데모 데이터**(난수 생성, 실제 나라장터 정보 아님)로 모든 화면·리포트·Copilot 이 동작합니다.

## 실데이터로 전환

1. **Supabase**: 프로젝트 생성 → SQL Editor 에 [`sql/schema.sql`](sql/schema.sql) 실행 → `.env` 에 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`(서버 전용 Secret key) 입력
2. **나라장터**: 공공데이터포털(data.go.kr)에서 *조달청 나라장터 공공데이터개방표준서비스* 활용신청 → `.env` 의 `SERVICE_KEY`
3. 수집: `python scripts/run_pipeline.py --job all --days 30` (최초 백필은 `--start 2025-01-01 --end 2025-12-31`)
4. (선택) `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` → Copilot 자유 질의, 리포트 AI 브리핑
5. (선택) 메일: `SMTP_*` 설정 후 `MAIL_DRY_RUN=false`. 그 전에는 `outbox/` 에 HTML 로 저장됩니다.
6. 운영 로그인: `.streamlit/secrets.toml.example` 참고해 Microsoft Entra ID 연결, `AUTH_DISABLED=false`

> ⚠ **API 필드명 확인 필요**: 나라장터 응답 필드는 [`hbr/collectors/g2b.py`](hbr/collectors/g2b.py)(오퍼레이션/파라미터)와
> [`hbr/etl/normalize.py`](hbr/etl/normalize.py)(필드 후보)에 모여 있습니다. 실제 키로 1회 호출해 응답 필드와 다르면 이 두 파일만 수정하면 됩니다.
> 자동 테스트는 모의 응답 기준입니다.

## 화면

| 화면 | 권한 | 내용 |
|---|---|---|
| Dashboard | viewer+ | KPI 6종, Opportunity TOP 10(+점수 구성·추천 Action), 낙찰 추이 |
| 입찰공고 | viewer+ | 검색/필터/정렬, 다운로드(sales+), 관심기관 등록 |
| 낙찰정보 | viewer+ | 병원·기업·지역·연도별, 경쟁사 비교(점유율) |
| 계약정보 | viewer+ | D-7/30/60/90/180 만료, 월별 규모 |
| 병원 상세 | viewer+ | 입찰·낙찰 이력, 계약, 공급사, 점수, 예상 재입찰 시점 |
| 경쟁사 | sales+ | GC·CSL·JW·SK플라즈마·기타: 최근 수주/병원별/지역별/연도별/점유율 |
| AI Copilot | sales+ | 도구호출 기반 채팅(읽기 전용) |
| 설정 | 전체 / admin | 수신설정·관심병원 / 사용자·파이프라인·메일 |

## 자동화 (GitHub Actions)

| 워크플로 | 시각(KST) | 동작 |
|---|---|---|
| `daily-pipeline` | 06:00 | 입찰→낙찰→계약 수집 → 점수 → 알림 생성 (논리 단계 06:00/06:10/06:20/07:00/07:30 을 한 잡에서 **순차** 실행) |
| `daily-report` | 07:40 기동 → 08:00 발송 | 개인화 Daily Report (회사+개인 메일), 중복 발송 방지 |
| `instant-alerts` | 평일 09~20시 30분마다 | 신규 입찰 수집 → 알림 → 구독자 메일 |
| `ci` | push/PR | pytest, 비밀 파일 커밋 차단 |

(선택) Teams 채널 알림: 채널 > 워크플로 > "웹후크 요청을 받으면 채널에 게시" 로 URL 을 발급해 `TEAMS_WEBHOOK_URL` 에 설정 (설정 > 메일 탭에서 테스트 전송).

(선택) Slack 채널 알림: Slack 앱 > Incoming Webhooks 로 발급한 URL 을 `SLACK_WEBHOOK_URL` 에 설정 (Teams 와 동시 사용 가능).

(선택) 카카오톡 알림톡: Solapi + 카카오 비즈채널 + 승인된 템플릿이 필요합니다 (`.env.example` 의 `SOLAPI_*`/`KAKAO_*`, 절차는 docs/ARCHITECTURE.md). 사용자가 설정 화면에서 번호 입력·수신 동의한 경우에만 발송됩니다.

필요한 GitHub Secrets: `SOLAPI_API_KEY/SECRET, KAKAO_PF_ID/SENDER/TPL_ALERT/TPL_REPORT(선택), SLACK_WEBHOOK_URL(선택), TEAMS_WEBHOOK_URL(선택), SERVICE_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM` / Variable: `APP_BASE_URL`.
GitHub cron 은 수 분~수십 분 지연될 수 있어 정시성이 중요하면 Azure Container Apps Job(`infra/deploy-azure.sh`)을 사용하세요.

## 개발

```bash
pip install -r requirements-dev.txt && pytest -q       # 103개 테스트 (스키마-코드 정합성, 모든 화면 스모크 포함)
```

## 보안 원칙
`.env`·`secrets.toml` 은 `.gitignore` + CI 차단. DB 는 RLS 활성(정책 없음 → anon 키 접근 불가), 서버만 Secret key 사용.
Microsoft Entra ID(단일 테넌트) 로그인 + 도메인 제한 + RBAC(viewer<sales<manager<admin), 다운로드·Copilot 은 sales 이상.
