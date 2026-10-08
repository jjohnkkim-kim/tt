-- 요금제: 회사별 플랜 (재실행 안전). 결제 연동 전이라 관리자가 직접 바꾼다.
alter table companies add column if not exists plan text not null default 'free';
alter table companies add column if not exists plan_until date;           -- 이 날짜가 지나면 free 로 본다 (비우면 기한 없음)
do $$ begin
  alter table companies add constraint companies_plan_check check (plan in ('free','pro','team'));
exception when duplicate_object then null; end $$;
-- 이 마이그레이션 이전에 만들어진 회사는 기존 이용을 막지 않도록 team 으로 둔다 (새 회사는 free 로 시작)
update companies set plan = 'team' where plan = 'free' and plan_until is null and created_at < now();
