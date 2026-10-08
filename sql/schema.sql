-- =====================================================================
-- Hospital Bid Radar — Supabase (PostgreSQL) schema
-- 실행: Supabase SQL Editor 에 통째로 붙여넣기 (재실행 안전: IF NOT EXISTS)
-- =====================================================================

-- ---------- 공통 ----------
create or replace function set_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------- hospitals : 병원 마스터 ----------
create table if not exists hospitals (
  id             bigint generated always as identity primary key,
  name           text        not null,
  name_norm      text        not null unique,          -- 공백/법인표기 제거·소문자 (upsert 키)
  inst_code      text,                                  -- 나라장터 기관코드 (제공 시)
  hospital_type  text,                                  -- 상급종합병원/대학병원/의료원/보훈병원/적십자병원/국립병원/종합병원/병원
  region         text,                                  -- 시도 (추정, 수동 보정 가능)
  is_active      boolean     not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists idx_hospitals_type   on hospitals (hospital_type);
create index if not exists idx_hospitals_region on hospitals (region);
drop trigger if exists trg_hospitals_updated on hospitals;
create trigger trg_hospitals_updated before update on hospitals
  for each row execute function set_updated_at();

-- ---------- competitors : 경쟁사 마스터 ----------
create table if not exists competitors (
  id         bigint generated always as identity primary key,
  name       text    not null unique,                   -- GC, CSL, JW, SK플라즈마 ...
  aliases    text[]  not null default '{}',             -- 낙찰/계약 업체명 매칭용 별칭
  is_own     boolean not null default false,            -- 자사 여부
  is_active  boolean not null default true,
  created_at timestamptz not null default now()
);

-- ---------- bids : 입찰공고 ----------
create table if not exists bids (
  id              bigint generated always as identity primary key,
  bid_key         text        not null unique,          -- 공고번호-차수
  bid_ntce_no     text        not null,
  bid_ntce_ord    text        not null default '00',
  title           text        not null,
  hospital_id     bigint      not null references hospitals(id) on delete restrict,
  inst_name       text        not null,                 -- 원본 기관명
  bid_date        date,                                 -- 공고일
  deadline        timestamptz,                          -- 입찰 마감
  open_date       date,                                 -- 개찰일
  budget          numeric(18,0),                        -- 배정예산
  est_price       numeric(18,0),                        -- 추정가격
  bid_method      text,
  contract_method text,
  url             text,
  is_pharma       boolean     not null default false,   -- 의약품 관련 여부 (제목 키워드)
  product_tags    text[]      not null default '{}',
  raw             jsonb,                                -- API 원본 (재처리용)
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists idx_bids_hospital_date on bids (hospital_id, bid_date desc);
create index if not exists idx_bids_deadline      on bids (deadline);
create index if not exists idx_bids_ntce_no       on bids (bid_ntce_no);
create index if not exists idx_bids_pharma_date   on bids (bid_date desc) where is_pharma;
drop trigger if exists trg_bids_updated on bids;
create trigger trg_bids_updated before update on bids
  for each row execute function set_updated_at();

-- ---------- awards : 낙찰정보 ----------
create table if not exists awards (
  id            bigint generated always as identity primary key,
  award_key     text        not null unique,            -- 공고번호-차수-사업자번호
  bid_ntce_no   text        not null,
  bid_ntce_ord  text        not null default '00',
  title         text,
  hospital_id   bigint      not null references hospitals(id) on delete restrict,
  inst_name     text        not null,
  winner_name   text        not null,
  winner_biz_no text,
  competitor_id bigint      references competitors(id) on delete set null,
  award_amount  numeric(18,0),
  award_rate    numeric(8,3),                           -- 낙찰률(%)
  award_date    date,
  is_pharma     boolean     not null default false,
  product_tags  text[]      not null default '{}',
  raw           jsonb,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists idx_awards_hospital_date on awards (hospital_id, award_date desc);
create index if not exists idx_awards_competitor    on awards (competitor_id, award_date desc);
create index if not exists idx_awards_ntce_no       on awards (bid_ntce_no);
create index if not exists idx_awards_date          on awards (award_date desc);
drop trigger if exists trg_awards_updated on awards;
create trigger trg_awards_updated before update on awards
  for each row execute function set_updated_at();

-- ---------- contracts : 계약정보 ----------
create table if not exists contracts (
  id                 bigint generated always as identity primary key,
  contract_key       text        not null unique,       -- 통합계약번호-차수
  contract_no        text        not null,
  title              text,
  hospital_id        bigint      not null references hospitals(id) on delete restrict,
  inst_name          text        not null,
  vendor_name        text,
  vendor_biz_no      text,
  competitor_id      bigint      references competitors(id) on delete set null,
  contract_amount    numeric(18,0),
  contract_date      date,
  start_date         date,
  end_date           date,
  end_date_estimated boolean     not null default false, -- API 가 종료일을 주지 않아 추정한 경우 true
  is_pharma          boolean     not null default false,
  product_tags       text[]      not null default '{}',
  raw                jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists idx_contracts_hospital_end on contracts (hospital_id, end_date);
create index if not exists idx_contracts_end_pharma   on contracts (end_date) where is_pharma;
create index if not exists idx_contracts_competitor   on contracts (competitor_id);
drop trigger if exists trg_contracts_updated on contracts;
create trigger trg_contracts_updated before update on contracts
  for each row execute function set_updated_at();

-- ---------- users : 사용자 (Microsoft Entra ID 로그인, RBAC) ----------
create table if not exists users (
  id              bigint generated always as identity primary key,
  email           text    not null unique,              -- 회사 이메일 (소문자)
  name            text,
  role            text    not null default 'viewer' check (role in ('viewer','sales','manager','admin')),
  personal_email  text,                                 -- Daily Report 추가 수신
  is_active       boolean not null default true,
  report_enabled  boolean not null default true,
  phone           text,                                 -- 알림톡 수신 휴대폰번호(개인정보, 본인 입력)
  kakao_opt_in    boolean not null default false,       -- 알림톡 수신 동의
  kakao_opt_in_at timestamptz,
  last_login_at   timestamptz,
  created_at      timestamptz not null default now()
);

-- ---------- subscriptions : 관심병원/알림 구독 ----------
create table if not exists subscriptions (
  id          bigint generated always as identity primary key,
  user_id     bigint not null references users(id) on delete cascade,
  hospital_id bigint references hospitals(id) on delete cascade,   -- NULL = 전체 병원
  alert_types text[] not null default '{NEW_BID,CONTRACT_EXPIRY,COMPETITOR_AWARD}',
  channel     text   not null default 'email',
  created_at  timestamptz not null default now()
);
create unique index if not exists uq_subscriptions_user_hospital
  on subscriptions (user_id, coalesce(hospital_id, 0), channel);
create index if not exists idx_subscriptions_hospital on subscriptions (hospital_id);

-- ---------- opportunity_scores : 일별 점수 스냅샷 ----------
create table if not exists opportunity_scores (
  id             bigint generated always as identity primary key,
  hospital_id    bigint not null references hospitals(id) on delete cascade,
  score_date     date   not null,
  score          numeric(5,1) not null check (score between 0 and 100),
  components     jsonb  not null,                       -- {expiry, market, competition, pattern, frequency}
  days_to_expiry integer,
  est_amount     numeric(18,0),
  reasons        jsonb  not null default '[]',
  detail         jsonb  not null default '{}',
  created_at     timestamptz not null default now(),
  unique (hospital_id, score_date)
);
create index if not exists idx_scores_date_score on opportunity_scores (score_date desc, score desc);

-- ---------- alerts : 이벤트 알림 (중복 방지 dedup_key) ----------
create table if not exists alerts (
  id            bigint generated always as identity primary key,
  alert_type    text   not null check (alert_type in ('NEW_BID','CONTRACT_EXPIRY','COMPETITOR_AWARD')),
  hospital_id   bigint references hospitals(id) on delete cascade,
  dedup_key     text   not null unique,                 -- 예: NEW_BID:2026...-00 / EXP:key:30
  title         text   not null,
  message       text,
  severity      text   not null default 'normal' check (severity in ('normal','high')),
  delivered_to  jsonb  not null default '[]',
  dispatched_at timestamptz,                            -- NULL = 미발송
  created_at    timestamptz not null default now()
);
create index if not exists idx_alerts_pending on alerts (id) where dispatched_at is null;
create index if not exists idx_alerts_hospital on alerts (hospital_id, created_at desc);

-- ---------- email_reports : 메일 발송 이력 (멱등성 키: report_date + recipient) ----------
create table if not exists email_reports (
  id          bigint generated always as identity primary key,
  report_date date   not null,
  user_id     bigint references users(id) on delete set null,
  recipient   text   not null,
  subject     text   not null,
  body_html   text,
  summary     jsonb,
  status      text   not null check (status in ('sent','dry_run','failed')),
  error       text,
  sent_at     timestamptz,
  created_at  timestamptz not null default now(),
  unique (report_date, recipient)
);
create index if not exists idx_email_reports_user on email_reports (user_id, report_date desc);

-- ---------- pipeline_runs : 수집/분석 실행 이력 (운영 모니터링) ----------
create table if not exists pipeline_runs (
  id          bigint generated always as identity primary key,
  job         text   not null,
  status      text   not null check (status in ('success','failed')),
  started_at  timestamptz not null,
  finished_at timestamptz,
  fetched     integer not null default 0,
  kept        integer not null default 0,
  upserted    integer not null default 0,
  error       text,
  created_at  timestamptz not null default now()
);
create index if not exists idx_runs_job_started on pipeline_runs (job, started_at desc);

-- ---------- 분석 View ----------
create or replace view v_contract_expiry as
select c.id, c.hospital_id, h.name as hospital, c.vendor_name, c.contract_amount,
       c.end_date, (c.end_date - current_date) as d_day, c.end_date_estimated
from contracts c join hospitals h on h.id = c.hospital_id
where c.is_pharma and c.end_date is not null and c.end_date >= current_date;

create or replace view v_competitor_share_yearly as
select extract(year from a.award_date)::int as year,
       coalesce(k.name, '기타') as competitor,
       count(*) as award_count,
       sum(a.award_amount) as award_amount
from awards a left join competitors k on k.id = a.competitor_id
where a.is_pharma and a.award_date is not null
group by 1, 2;

-- ---------- 보안 (RLS) ----------
-- 앱은 서버(Streamlit/배치)에서 Secret(service_role) key 로만 접근한다.
-- RLS 를 켜고 정책을 만들지 않으면 anon/authenticated 키로는 어떤 행도 읽을 수 없다.
alter table hospitals          enable row level security;
alter table competitors        enable row level security;
alter table bids               enable row level security;
alter table awards             enable row level security;
alter table contracts          enable row level security;
alter table users              enable row level security;
alter table subscriptions      enable row level security;
alter table opportunity_scores enable row level security;
alter table alerts             enable row level security;
alter table email_reports      enable row level security;
alter table pipeline_runs      enable row level security;
-- View 도 호출자 권한으로 평가되게 (PG15+)
alter view v_contract_expiry        set (security_invoker = true);
alter view v_competitor_share_yearly set (security_invoker = true);
