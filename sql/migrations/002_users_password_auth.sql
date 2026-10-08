-- 기존 DB 용: 이메일 가입 + 관리자 승인 로그인 컬럼 추가 (재실행 안전). 신규 설치는 schema.sql 에 이미 포함.
-- 기존 사용자는 status='approved' 로 유지된다 (Microsoft 로그인 사용자 영향 없음).
alter table users add column if not exists status text not null default 'approved';
alter table users add column if not exists password_hash text;
alter table users add column if not exists failed_attempts integer not null default 0;
alter table users add column if not exists locked_until timestamptz;
alter table users add column if not exists must_change_password boolean not null default false;
alter table users add column if not exists approved_by bigint references users(id) on delete set null;
alter table users add column if not exists approved_at timestamptz;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'users_status_check') then
    alter table users add constraint users_status_check check (status in ('pending','approved','rejected','disabled'));
  end if;
end $$;
