-- Canonical roster (spec 00 §2). Runs at boot after the migrations.
-- ON CONFLICT DO NOTHING: edits made in /admin are never overwritten by a restart.
-- Values marked VERIFY in the spec are seeded as written there and flagged in people.notes.

insert into people (id, display_name, jira_account_id, slack_id, role, niche, skip_expert_review, active, app_role, notes) values
  ('zindzy',    'Zindzy Gracia',            '70121:064c601e-cbf1-4550-8d17-8fea2b338118', 'U02A60PF739', 'writer', 'exercise',  false, true, null, null),
  ('eve',       'Eve Chalicha',             '712020:51b52722-9eb1-4aa8-8b6d-527b045f3913', 'U02BABJ64DN', 'writer', 'exercise',  false, true, null, null),
  ('jeremy',    'Jeremy Mukhwana',          '712020:4e42fbfd-ec2b-414f-99d4-41dfb6faa417', 'U02ALU6SQSF', 'writer', 'both',      false, true, null, 'VERIFY niche: Byline Board says exercise'),
  ('nderitu',   'Samuel Nderitu Munuhe',    '712020:4e7281a8-604f-46bd-9f0e-61aa6a42030b', 'U02AZB589JM', 'writer', 'any',       false, true, null, null),
  ('eva',       'Eva De Angelis',           '6348b6fe94b0b260830778d6',                    null,          'writer', 'nutrition', true,  true, null, null),
  ('rubiolo',   'Maria Lourdes Rubiolo',    '712020:44ae3ce5-c8c9-43b3-b106-63585b9a2edf', null,          'writer', 'nutrition', true,  true, null, null),
  ('anoshia',   'Anoshia Riaz',             '70121:fb24c986-30fc-4274-b096-e53d17aad7a4',  'U058J380M40', 'writer', 'any',       false, true, null, null),
  ('srijoni',   'Srijoni Gupta Roy',        '712020:cd6750f8-c67c-425d-a302-5df85069691b', 'U05RXE73VPX', 'writer', 'any',       false, true, null, null),
  ('stephanie', 'Stephanie Wright',         '712020:502524c1-2ded-482c-92d0-19f23c66eb0a', null,          'writer', 'any',       true,  true, null, null),
  ('giulia',    'Giulia Ralph',             '712020:49c3c2b9-1390-4df0-a4c9-6461502d6d74', null,          'writer', 'both',      true,  true, null, null),
  ('brenda',    'Brenda Peralta',           '612fcdbd9976c30069467dad',                    null,          'writer', 'both',      true,  true, null, null),
  ('natalia',   'Nataliia Lutsiv',          '628756b3bd640f0068afa6a9',                    null,          'writer', 'any',       false, true, null, null),
  ('clare',     'Clare Kamau',              '712020:bff933c8-cc5b-49af-8cd5-adc27df2c921', 'U02AE0M1VPY', 'writer', 'any',       false, true, null, null),
  ('carter',    'Carter Lee',               '712020:78a486c4-c1e4-4bc0-bba9-4676513ecb28', null,          'expert', 'fitness',   false, true, null, 'VERIFY rate: Experts board says $40/h; invoice'),
  ('garett',    'Garett Reid',              '5de4fe878389de0cd335416b',                    null,          'expert', 'fitness',   false, true, null, 'VERIFY rate: $50/h, Upwork'),
  ('angelica',  'Angelica Galvan',          '712020:43ac8bef-1645-465e-9909-5bbb7ee20fa5', null,          'expert', 'nutrition', false, true, null, 'VERIFY rate: $45/h, invoice'),
  ('corrarello','Maria Eugenia Corrarello', '712020:87a66480-0c2d-4444-be68-26bb3afbbd60', null,          'expert', 'nutrition', false, true, null, 'VERIFY rate: "$40–45/h proposed"'),
  ('kelsey',    'Kelsey Butler',            null,                                          null,          'expert', 'nutrition', false, false, null, 'VERIFY Jira accountId and that she is active'),
  ('colette',   'Z. Colette Edwards',       null,                                          null,          'expert', null,        false, true, null, 'VERIFY Jira accountId'),
  ('amanda',    'Amanda Pasko',             null,                                          null,          'expert', null,        false, false, null, 'VERIFY accountId and that she is active'),
  ('tim',       'Tim Jones',                '70121:f5089ddd-2808-4286-a217-02dd8bda85e9',  null,          'proofreader', null,   false, true, null, 'VERIFY rate (Upwork)'),
  ('yuliia_k',  'Yuliia Koreniuk',          '712020:b345726f-fe25-4239-a7dc-7322d7dbc2ae', 'U0AHVPJ0QKA', 'publisher', null,     false, true, null, null),
  ('oksana',    'Oksana Pidlisna',          '712020:7cf474f8-6ae6-439f-8d54-f6a1e3143066', null,          'designer', null,      false, true, null, null),
  ('karina',    'Karina Sorvachova',        '712020:3584bb79-f831-407e-a40a-02e8084953d5', null,          'designer', null,      false, true, null, 'VERIFY role: designer or content manager'),
  ('polina',    'Polina Klieshcheva',       null,                                          'U07AN6WBZ0F', 'researcher', null,    false, true, null, 'VERIFY Jira accountId'),
  ('vladyslav', 'Vladyslav Betsun',         '712020:0d312ff6-23a7-4fa4-b5a1-b57be36d9f75', 'U0BNYBLCD63', 'manager', null,       false, true, 'owner', null),
  ('volodymyr', 'Volodymyr',                null,                                          'U017H7SSK24', 'stakeholder', null,   false, true, 'viewer', 'SEO/GEO lead. VERIFY Jira accountId'),
  ('yuliia_h',  'Yuliia Horetska',          null,                                          'U07A90HSQ5A', 'finance', null,       false, true, 'finance', null),
  -- former contributors (Editorial Load)
  ('alexis_schofield',  'Alexis Schofield',  null, null, 'writer', null, false, false, null, 'former'),
  ('sachini_akuretiya', 'Sachini Akuretiya', null, null, 'writer', null, false, false, null, 'former'),
  ('kristen_fleming',   'Kristen Fleming',   null, null, 'writer', null, false, false, null, 'former'),
  ('kaye_smith',        'Kaye Smith',        null, null, 'writer', null, false, false, null, 'former'),
  ('micky_lal',         'Micky Lal',         null, null, 'writer', null, false, false, null, 'former'),
  ('jared_meacham',     'Jared Meacham',     null, null, 'writer', null, false, false, null, 'former'),
  ('troy_hurst',        'Troy Hurst',        null, null, 'writer', null, false, false, null, 'former')
on conflict (id) do nothing;

-- Jira display names that differ from the canonical name (for parsing free text only; matching uses accountId)
insert into person_aliases (alias, person_id) values
  ('zindzy gracia', 'zindzy'),
  ('evelyn chalicha', 'eve'),
  ('nderitu munuhe', 'nderitu'),
  ('carla eva de angelis', 'eva'),
  ('carla eva de angelis viard', 'eva'),
  ('lic.rubiolo.nutri', 'rubiolo'),
  ('srijoni.guptaroy', 'srijoni'),
  ('sri r', 'srijoni'),
  ('sri r (gupta)', 'srijoni'),
  ('bluegrassnursewright', 'stephanie'),
  ('наталі луців', 'natalia'),
  ('natalia lutsiv', 'natalia'),
  ('maria.eugenia.coaching', 'corrarello'),
  ('kelseykingbutler', 'kelsey'),
  ('anosha riaz', 'anoshia'),
  ('clare camau', 'clare')
on conflict (alias) do nothing;

-- Rates (effective-dated). Seeded only for people who have no rate rows yet.
insert into rates (person_id, kind, amount, amount_max, unit, billing, effective_from, note)
select v.person_id, v.kind, v.amount, v.amount_max, v.unit, v.billing, date '2026-01-01', v.note
from (values
  ('zindzy',    'base', 0.03,  null::numeric, 'word',    'upwork',   null),
  ('eve',       'base', 0.035, null, 'word',    'upwork',   null),
  ('jeremy',    'base', 0.03,  null, 'word',    'upwork',   null),
  ('nderitu',   'base', 0.04,  null, 'word',    'upwork',   null),
  ('eva',       'base', 0.11,  null, 'word',    'invoice',  null),
  ('rubiolo',   'base', 0.10,  null, 'word',    'invoice',  null),
  ('anoshia',   'base', 0.04,  null, 'word',    'upwork',   null),
  ('srijoni',   'base', 0.08,  null, 'word',    'upwork',   null),
  ('stephanie', 'base', 200,   null, 'article', 'invoice',  null),
  ('giulia',    'base', 0.12,  null, 'word',    'invoice',  null),
  ('brenda',    'base', 100,   120,  'article', 'invoice',  null),
  ('natalia',   'base', 0.06,  null, 'word',    'upwork',   null),
  ('clare',     'base', 32.5,  null, 'article', 'upwork',   null),
  ('carter',    'base', 50,    null, 'article', 'invoice',  'VERIFY'),
  ('garett',    'base', 50,    null, 'article', 'upwork',   'VERIFY'),
  ('angelica',  'base', 50,    null, 'article', 'invoice',  'VERIFY'),
  ('corrarello','base', 20,    null, 'article', 'invoice',  'VERIFY'),
  ('kelsey',    'base', 45,    null, 'article', 'invoice',  'VERIFY'),
  ('colette',   'base', 2500,  null, 'month',   'retainer', null),
  ('amanda',    'base', 0.07,  null, 'word',    'invoice',  'VERIFY active'),
  ('polina',    'base', 600,   null, 'month',   'retainer', null)
) as v(person_id, kind, amount, amount_max, unit, billing, note)
where not exists (select 1 from rates r where r.person_id = v.person_id);
