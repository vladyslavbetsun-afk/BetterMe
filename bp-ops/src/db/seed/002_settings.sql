-- Default settings. ON CONFLICT DO NOTHING keeps whatever was changed in /admin.
insert into settings (key, value) values
  ('jira_writes_enabled',       'false'),
  ('slack_send_enabled',        'false'),
  ('notion_writes_enabled',     'false'),
  ('review_automation_enabled', 'false'),
  ('review_automation_dry_run', 'true'),
  ('review.windowDays',         '3'),
  ('review.noteMode',           '"internal"'),
  ('review.autoSlackSince',     'null'),
  ('pipeline.auto_close',       'false'),
  ('publish.batch_size',        '4'),
  ('holidays',                  '[]'),
  ('performance.baseline_date', '"2026-08-20"'),
  ('report.send_time',          '"17:00"')
on conflict (key) do nothing;
