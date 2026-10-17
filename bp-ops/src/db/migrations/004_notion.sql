-- Mirror of the Notion Articles database (00 §4), refreshed by the sync_notion_status job.
create table if not exists notion_cards (
  page_id text primary key,
  number int,
  name text,
  status text,
  priority text,
  category text,
  new_upd text,
  url1 text,
  jira_url text,
  jira_key text,
  date date,
  notion_url text,
  synced_at timestamptz not null default now()
);
create index if not exists notion_cards_key_idx on notion_cards (jira_key);
