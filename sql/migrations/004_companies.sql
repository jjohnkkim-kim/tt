-- 회사(멀티테넌트)와 회사별 관심 제품 (재실행 안전). 기존 데이터는 건드리지 않는다.
create table if not exists companies (
  id           bigint generated always as identity primary key,
  name         text   not null,
  company_type text   not null default '제약사',
  own_aliases  text[] not null default '{}',          -- 자사로 인식할 표기명(낙찰·계약업체 이름과 비교)
  created_at   timestamptz not null default now()
);
create unique index if not exists uq_companies_name on companies (lower(name));

create table if not exists company_products (
  id             bigint generated always as identity primary key,
  company_id     bigint not null references companies(id) on delete cascade,
  name           text   not null,                      -- 제품명
  ingredient     text,                                 -- 성분명
  product_group  text,                                 -- 제품군
  manufacturer   text,
  insurance_code text,                                 -- 보험코드
  atc_code       text,
  keywords       text[] not null default '{}',         -- 동의어·다른 표기
  created_at     timestamptz not null default now(),
  unique (company_id, name)
);
create index if not exists idx_company_products_company on company_products (company_id);

alter table users add column if not exists company_id bigint references companies(id) on delete set null;
create index if not exists idx_users_company on users (company_id);

-- 특정 회사를 '자사'로 고정하던 기본값 제거 (자사는 이제 회사 설정의 표기명으로 판단)
update competitors set is_own = false where is_own;
