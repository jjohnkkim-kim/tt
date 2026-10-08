-- 기존 DB 용: 알림톡 수신 정보 컬럼 추가 (재실행 안전). 신규 설치는 schema.sql 에 이미 포함.
alter table users add column if not exists phone           text;
alter table users add column if not exists kakao_opt_in    boolean not null default false;
alter table users add column if not exists kakao_opt_in_at timestamptz;
