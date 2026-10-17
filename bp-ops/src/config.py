"""Constants from docs/specs/00-shared-reference.md §1 plus environment configuration.

When this file and the legacy artifacts disagree, the spec wins.
"""

import os
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Brussels")

# --- Jira (00 §1) ---------------------------------------------------------------
JIRA_SITE = os.environ.get("JIRA_BASE_URL", "https://newsiteam.atlassian.net").rstrip("/")
JIRA_CLOUD_ID = "657e24cd-f643-4482-aba5-7e848607df28"
PROJECT = "BP"
ISSUE_TYPE_ARTICLE = "10596"
REQUEST_TYPE_FIELD = "customfield_11100"
REQUEST_TYPE_ARTICLE = "110"

STATUSES = ["Open", "Text", "Review", "Proofreading", "Ready", "Published"]
ACTIVE = ["Text", "Review", "Proofreading"]

TRANSITIONS = {"Text": "11", "Review": "21", "Proofreading": "31", "Ready": "41"}  # Published: look up each time

F_MANAGERS = "customfield_11709"
F_AUTHOR = "customfield_11710"
F_EXPERT = "customfield_11711"
F_PROOFREADER = "customfield_11712"
F_PARTICIPANTS = "customfield_11208"
F_SUBHEADINGS = "customfield_11717"
F_ADDITIONAL_KEYWORDS = "customfield_11718"
F_LINKED_ARTICLES = "customfield_11719"
F_FAQS = "customfield_11720"
F_TOPIC_TAGS = "customfield_11726"
PEOPLE_FIELDS = [F_AUTHOR, F_EXPERT, F_PROOFREADER, F_PARTICIPANTS]

SYNC_FIELDS = ["summary", "status", "issuetype", "created", "updated", "comment",
               F_MANAGERS, F_AUTHOR, F_EXPERT, F_PROOFREADER, F_PARTICIPANTS]


def ticket_url(key: str) -> str:
    return f"{JIRA_SITE}/browse/{key}"


# --- People referenced by rules (accountIds, 00 §2) ---------------------------------
OWNER_ACCOUNT_ID = os.environ.get("OWNER_ACCOUNT_ID", "712020:0d312ff6-23a7-4fa4-b5a1-b57be36d9f75")  # Vladyslav
TIM_ACCOUNT_ID = "70121:f5089ddd-2808-4286-a217-02dd8bda85e9"
YULIIA_K_ACCOUNT_ID = "712020:b345726f-fe25-4239-a7dc-7322d7dbc2ae"
OKSANA_ACCOUNT_ID = "712020:7cf474f8-6ae6-439f-8d54-f6a1e3143066"
KARINA_ACCOUNT_ID = "712020:3584bb79-f831-407e-a40a-02e8084953d5"
# Comments by these people are images and live links; ignore them when deciding workflow steps (00 §1)
IGNORED_COMMENTERS = {OKSANA_ACCOUNT_ID, YULIIA_K_ACCOUNT_ID}
IMAGE_POSTERS = {OKSANA_ACCOUNT_ID, KARINA_ACCOUNT_ID}

# --- Slack (00 §3) --------------------------------------------------------------------
SLACK_TEAM_ID = os.environ.get("SLACK_TEAM_ID", "")  # for deep links; VERIFY in Phase 0
SLACK_VOLODYMYR = "U017H7SSK24"
SLACK_YULIIA_K = "U0AHVPJ0QKA"
SLACK_YULIIA_H = "U07A90HSQ5A"

# --- Notion (00 §4) ----------------------------------------------------------------------
NOTION_DATABASE_URL = "https://app.notion.com/p/betterme-team/1e997cc22a8080a5bef9c9da6dd8d43f"
NOTION_DATA_SOURCE_ID = "1e997cc2-2a80-8086-a8ea-000bcc1073a4"
NOTION_STATUS_FOR = {"Open": "Not started", "Text": "In progress", "Review": "In progress",
                     "Proofreading": "In progress", "Ready": "In progress", "Published": "Done"}

# --- Environment ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost/bpops")
# Comma-separated emails that are always treated as owner (bootstrap before people.email is filled in).
OWNER_EMAILS = {e.strip().lower() for e in os.environ.get("OWNER_EMAILS", "").split(",") if e.strip()}
# Local development only: pretend this email is signed in when no auth header is present.
DEV_USER_EMAIL = os.environ.get("DEV_USER_EMAIL", "").strip().lower()
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"
APP_URL = os.environ.get("APP_URL", "https://bp-ops.exdev.betterme.world")

# Secrets are optional at boot: the app starts without them and shows "not configured" chips (spec 05 §3).
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
AHREFS_API_KEY = os.environ.get("AHREFS_API_KEY", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")


def jira_configured() -> bool:
    from core import jira

    return jira.auth_headers() is not None
