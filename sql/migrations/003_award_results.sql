-- 낙찰·유찰을 한 테이블(awards)에 저장: 결과 구분 + 투찰업체 수 추가 (재실행 안전)
alter table awards alter column winner_name drop not null;
alter table awards add column if not exists result_status text not null default '낙찰';
alter table awards add column if not exists bidder_count integer;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'awards_result_status_check') then
    alter table awards add constraint awards_result_status_check check (result_status in ('낙찰','유찰'));
  end if;
end $$;
create index if not exists idx_awards_status_date on awards (result_status, award_date desc);
