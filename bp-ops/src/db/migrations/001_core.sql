-- Core schema (spec 05 §6). Idempotent: safe to run on every boot.

-- people & money ------------------------------------------------------------
create table if not exists people (
  id text primary key,
  display_name text not null,
  email text,
  jira_account_id text unique,
  slack_id text,
  role text check (role in ('writer','expert','proofreader','publisher','designer','manager','researcher',
                            'stakeholder','finance')),
  niche text,
  skip_expert_review bool not null default false,
  active bool not null default true,
  app_role text check (app_role in ('owner','viewer','finance','designer')),
  notes text
);
create unique index if not exists people_email_uq on people (lower(email)) where email is not null;

create table if not exists person_aliases (
  alias text primary key,
  person_id text not null references people on delete cascade
);

create table if not exists rates (
  id bigserial primary key,
  person_id text not null references people on delete cascade,
  kind text not null default 'base',          -- base | review_fee
  amount numeric not null,
  amount_max numeric,
  unit text not null check (unit in ('word','article','hour','month')),
  currency text not null default 'USD',
  billing text check (billing in ('upwork','invoice','retainer','internal')),
  effective_from date not null default date '2026-01-01',
  effective_to date,
  note text
);
create index if not exists rates_person_idx on rates (person_id, kind, effective_from);

-- jira mirror -----------------------------------------------------------------
create table if not exists tickets (
  jira_key text primary key,
  key_num int,
  summary text not null default '',
  status text,
  issue_type text,
  type text check (type in ('new','update')),
  created_at timestamptz,
  updated_at timestamptz,
  author_id text,
  expert_id text,
  proofreader_id text,
  managers text[] not null default '{}',
  participants text[] not null default '{}',
  word_min int,
  word_max int,
  category_detected text,
  doc_url text,
  live_url text,
  entered_ready_at timestamptz,
  entered_published_at timestamptz,
  synced_at timestamptz,
  raw jsonb
);
create index if not exists tickets_status_idx on tickets (status);
create index if not exists tickets_author_idx on tickets (author_id);

create table if not exists comments (
  id text primary key,
  jira_key text not null references tickets on delete cascade,
  author_account_id text,
  author_name text,
  created_at timestamptz not null,
  body_md text not null default '',
  links text[] not null default '{}',
  mentions text[] not null default '{}'   -- accountIds mentioned in the comment
);
create index if not exists comments_key_idx on comments (jira_key, created_at);

create table if not exists status_transitions (
  jira_key text not null references tickets on delete cascade,
  at timestamptz not null,
  from_status text,
  to_status text not null,
  by_account_id text,
  primary key (jira_key, at, to_status)
);
create index if not exists st_to_idx on status_transitions (to_status, at);

-- changes to the people fields (Author, Expert, Proofreader, Request participants), from the changelog
create table if not exists field_changes (
  jira_key text not null references tickets on delete cascade,
  at timestamptz not null,
  field_id text not null,
  from_value text,
  to_value text,
  primary key (jira_key, at, field_id)
);

-- workflow state (ported from artifact databases) ------------------------------
create table if not exists settings (
  key text primary key,
  value jsonb not null
);
create table if not exists exclusions (
  jira_key text primary key,
  title text,
  at timestamptz not null default now(),
  by text
);
create table if not exists overrides (
  jira_key text primary key,
  category text check (category in ('fitness','nutrition')),
  expert_id text,
  auto_slack bool
);
create table if not exists expert_asks (
  jira_key text primary key,
  at timestamptz not null
);

-- every action the app takes or proposes ------------------------------------------
create table if not exists actions (
  id bigserial primary key,
  kind text not null,
  jira_key text,
  payload jsonb not null default '{}',
  state text not null check (state in ('proposed','confirmed','sent','failed','cancelled')),
  proposed_by text,
  confirmed_by text,
  created_at timestamptz not null default now(),
  executed_at timestamptz,
  error text,
  idempotency_key text unique
);
create table if not exists outbound_messages (
  id bigserial primary key,
  channel text not null,                 -- slack_dm | slack_channel | jira_comment
  recipient text not null,
  template text not null,
  body text not null,
  ticket_keys text[] not null default '{}',
  idempotency_key text not null unique,  -- ← kills the duplicate-nudge bug
  state text not null check (state in ('draft','sent','failed','cancelled')),
  created_at timestamptz not null default now(),
  created_by text,
  sent_at timestamptz,
  external_ts text
);
create index if not exists outbound_recipient_idx on outbound_messages (recipient, sent_at);

-- publishing ----------------------------------------------------------------------
create table if not exists batches (
  id text primary key,
  n int not null,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  post_at timestamptz,
  message_id bigint,
  archived bool not null default false
);
create table if not exists batch_items (
  batch_id text not null references batches on delete cascade,
  jira_key text not null,
  position int not null,
  primary key (batch_id, jira_key)
);

-- spend ------------------------------------------------------------------------------
create table if not exists spend_months (
  month date primary key,
  status text not null check (status in ('open','closed')),
  closed_at timestamptz,
  closed_by text
);
create table if not exists spend_lines (
  id bigserial primary key,
  month date not null references spend_months,
  person_id text,
  category text not null check (category in ('writing','review','proofreading','research','design','other')),
  source text not null check (source in ('jira_auto','fixed','manual')),
  jira_keys text[] not null default '{}',
  amount numeric not null default 0,
  amount_max numeric,
  unpriced int not null default 0,
  note text,
  updated_at timestamptz not null default now()
);
create index if not exists spend_lines_month_idx on spend_lines (month, source);

-- ops ----------------------------------------------------------------------------------
create table if not exists job_runs (
  id bigserial primary key,
  job text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running',   -- running | ok | failed | skipped | skipped_budget
  rows int,
  units_used int,
  error text
);
create index if not exists job_runs_job_idx on job_runs (job, started_at desc);

create table if not exists audit_log (
  id bigserial primary key,
  at timestamptz not null default now(),
  actor text,
  action text not null,
  target text,
  detail jsonb not null default '{}'
);
create index if not exists audit_log_at_idx on audit_log (at desc);

create table if not exists report_lines (
  id bigserial primary key,
  day date not null,
  text text not null,
  created_by text,
  created_at timestamptz not null default now()
);

create table if not exists import_issues (
  id bigserial primary key,
  at timestamptz not null default now(),
  source text not null,
  ref text,
  problem text not null,
  detail jsonb not null default '{}'
);
