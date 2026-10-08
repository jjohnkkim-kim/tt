-- 알림 조건(사용자별) + 알림 이벤트 확장 (재실행 안전)
alter table alerts add column if not exists payload jsonb not null default '{}';        -- 제목·낙찰업체·마감일 등 조건 판단용 정보

alter table alerts drop constraint if exists alerts_alert_type_check;
alter table alerts add constraint alerts_alert_type_check check (alert_type in
  ('NEW_BID','DEADLINE','AWARD','FAILED','REBID','CONTRACT_EXPIRY','COMPETITOR_AWARD'));

create table if not exists alert_rules (
  id             bigint generated always as identity primary key,
  user_id        bigint not null unique references users(id) on delete cascade,
  types          text[] not null default '{NEW_BID,DEADLINE,AWARD,FAILED,REBID,CONTRACT_EXPIRY}',
  deadline_days  int[]  not null default '{7,3,1}',                                      -- 마감 임박을 알릴 D-day
  scope          text   not null default 'all' check (scope in ('all','mine')),            -- all=전체, mine=내 관심제품 또는 관심병원
  min_match      text   not null default 'MEDIUM' check (min_match in ('HIGH','MEDIUM','LOW')),
  exclude_own    boolean not null default true,                                           -- 내 회사 낙찰은 제외
  email_enabled  boolean not null default true,
  updated_at     timestamptz not null default now()
);
