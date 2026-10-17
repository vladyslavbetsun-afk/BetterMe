-- Flow module derived tables (spec 04 §5). tickets and status_transitions live in 001.

create table if not exists stage_durations (
  jira_key text not null references tickets on delete cascade,
  stage text not null,
  entered_at timestamptz not null,
  exited_at timestamptz,
  business_days real,
  primary key (jira_key, stage, entered_at)
);
create index if not exists stage_durations_stage_idx on stage_durations (stage, exited_at);

create table if not exists flow_daily (
  date date not null,
  stage text not null,
  wip int not null default 0,
  inflow int not null default 0,
  outflow int not null default 0,
  primary key (date, stage)
);

create table if not exists qa_checks (
  jira_key text primary key,
  checked_at timestamptz not null default now(),
  live_updated_on date,
  live_h1 text,
  http_status int,
  mismatch bool,
  note text
);
