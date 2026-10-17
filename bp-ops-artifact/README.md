# BP Ops (artifact)

Live, read-only artifact version of BP Ops: https://claude.ai/artifact/Qbi4sUEABfngYaWUirKFcR

Reads Jira BP through the viewer's Atlassian connector (`searchJiraIssuesUsingJql`, `getJiraIssue`) and never
writes to Jira. Tabs: Flow, Review, Load, Publish, Assign. The artifact's database keeps exclusions, overrides,
publishing batches and Slack nudge drafts (one draft per writer, ticket set and day).

The full app with Spend, Daily report, Pipeline and Admin is in `../bp-ops/`. Rules are ported from the same specs
(`../bp-ops/docs/specs/`); keep the two in step when a rule changes.
