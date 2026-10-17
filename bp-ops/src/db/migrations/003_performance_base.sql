-- The part of spec 01's schema that the Phase 3 import needs (October tracker, Slipped Pages Tracker).
-- The rest of spec 01 (GSC tables, aio gap, position checks, summary view) arrives with Phase 4.

create table if not exists articles (
  url text primary key,
  slug text,
  title text,
  category text,
  cohort text check (cohort in ('new','update','refresh_detected','slipped','manual')),
  jira_key text,
  go_live_date date,
  slipped_level text,
  main_keyword text,
  main_keyword_volume int,
  active bool not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists article_events (
  id bigserial primary key,
  url text not null,
  kind text not null,      -- published, updated_on_changed, qa_flag, level_changed, note, progress
  at timestamptz not null default now(),
  payload jsonb not null default '{}'
);
create unique index if not exists article_events_dedupe on article_events (url, kind, at);

create table if not exists ahrefs_page_weekly (
  url text not null,
  week date not null,
  traffic int,
  keywords int,
  top3 int,
  top4_10 int,
  primary key (url, week)
);

create table if not exists ai_citations_weekly (
  target text not null,
  mode text not null,
  week date not null,
  ai_all int, aio int, ai_mode int, chatgpt int, perplexity int, gemini int, copilot int,
  primary key (target, mode, week)
);

create table if not exists page_snapshots (
  url text not null,
  checked_at timestamptz not null default now(),
  updated_on date,
  h1 text,
  has_key_takeaways bool,
  word_count int,
  http_status int,
  primary key (url, checked_at)
);

create table if not exists position_checks (
  url text not null,
  label text not null,
  check_date date,
  keyword text,
  position real,
  in_aio bool,
  traffic int,
  primary key (url, label)
);
