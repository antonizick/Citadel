from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class InterestType(str, Enum):
    term = "term"
    person = "person"
    technology = "technology"
    company = "company"
    event = "event"
    other = "other"


class ScheduleType(str, Enum):
    manual = "manual"
    interval = "interval"
    weekly = "weekly"
    cron = "cron"


class OutputType(str, Enum):
    report = "report"
    email = "email"
    sms = "sms"
    slack = "slack"
    discord = "discord"


class ScheduleConfig(BaseModel):
    type: str = "interval"
    interval_value: int = 1
    interval_unit: str = "days"  # minutes, hours, days, weeks
    run_time: str = "09:00"      # HH:MM UTC
    days_of_week: List[int] = [] # 0=Mon … 6=Sun
    cron_expression: str = ""


class OutputConfig(BaseModel):
    types: List[str] = ["report"]
    email_recipients: List[str] = []
    sms_numbers: List[str] = []
    slack_webhook: Optional[str] = None
    discord_webhook: Optional[str] = None
    report_format: str = "markdown"


class InterestCreate(BaseModel):
    name: str
    description: str = ""
    type: str = "term"
    keywords: List[str] = []
    tags: List[str] = []
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    active: bool = True


class InterestUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    schedule: Optional[ScheduleConfig] = None
    output: Optional[OutputConfig] = None
    active: Optional[bool] = None


class Interest(InterestCreate):
    id: str
    created_at: str
    updated_at: str
    last_run: Optional[str] = None
    next_run: Optional[str] = None


DEFAULT_RESOURCE_PROMPT = """NEVER start with a Data Coverage Notice
ALWAYS put the Stories Extractable from Provided Results at the very top.
If there are Data Coverage Concerns or Notices, put those after-underneath the stories

Your source is [ SOURCE ]
Parse the full source provided (It may be a web page, RSS feed, XML file, Twitter or X account). Extract every item published in the last 48 hours (use any available date field and filter strictly to items from the past 48 hours as of right now). Ignore older items. For each significant/recent story, output in this exact format:

Title
[Exact title from the Source]

Executive Summary
[Concise overview based on the full article content]

Technical Details (as applicable)
[Any vulnerabilities, malware, attack techniques, tools, code snippets, or technical specifics mentioned in the full article]

Known IOCs (as applicable)
[List any Indicators of Compromise (IPs, domains, hashes, filenames, C2 servers, etc.). If none are mentioned, write "None disclosed." If this is a cyber security matter include this section; if not, omit it entirely]

Impact / Conclusion
[Clear assessment of affected sectors, organizations, potential damage, risk level, or broader implications]

Instructions for best results:
- If the Source is only a short teaser, automatically follow the <link> URL to the full article and read the complete page content before summarizing.
- Prioritize the most important/recent stories (aim for 8–15 top stories max; skip minor or repetitive ones).
- Focus especially on technical depth, IOCs, exploits, and real-world business/security impact.
- Use today's date and time as the cutoff for the 48-hour window.

Link
[HTML link direct to story details]

ALWAYS put the Stories Extractable from Provided Results at the very top.
If there are Data Coverage Concerns or Notices, put those after the stories — place a horizontal divider, then a heading "Data Coverage Notice" with a caution icon and articulate the data coverage issues."""


class ResourceOutputConfig(BaseModel):
    types: List[str] = []
    email_recipients: List[str] = []
    sms_numbers: List[str] = []
    slack_webhook: Optional[str] = None
    discord_webhook: Optional[str] = None
    report_format: str = "markdown"


class ResourceCreate(BaseModel):
    name: str
    source: str = ""
    type: str = "website"
    prompt: str = DEFAULT_RESOURCE_PROMPT
    tags: List[str] = []
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    output: ResourceOutputConfig = Field(default_factory=ResourceOutputConfig)
    active: bool = True


class ResourceUpdate(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    type: Optional[str] = None
    prompt: Optional[str] = None
    tags: Optional[List[str]] = None
    schedule: Optional[ScheduleConfig] = None
    output: Optional[ResourceOutputConfig] = None
    active: Optional[bool] = None


class Resource(ResourceCreate):
    id: str
    created_at: str
    updated_at: str
    last_run: Optional[str] = None
    next_run: Optional[str] = None


class SummaryReportCreate(BaseModel):
    name: str
    description: str = ""
    tags: List[str] = []
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    active: bool = True


class SummaryReportUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    schedule: Optional[ScheduleConfig] = None
    output: Optional[OutputConfig] = None
    active: Optional[bool] = None


class SummaryReport(SummaryReportCreate):
    id: str
    created_at: str
    updated_at: str
    last_run: Optional[str] = None
    next_run: Optional[str] = None


class LLMSettings(BaseModel):
    provider: str = "anthropic"
    api_key: str = ""
    model: str = "claude-sonnet-4-6"


class EmailSettings(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = ""
    use_tls: bool = True


class SMSSettings(BaseModel):
    provider: str = "twilio"
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""


class SlackSettings(BaseModel):
    default_webhook: str = ""


class DiscordSettings(BaseModel):
    default_webhook: str = ""


class SearchSettings(BaseModel):
    provider: str = "duckduckgo"
    max_results: int = 10
    serpapi_key: str = ""
    brave_api_key: str = ""


class AppSettings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    sms: SMSSettings = Field(default_factory=SMSSettings)
    slack: SlackSettings = Field(default_factory=SlackSettings)
    discord: DiscordSettings = Field(default_factory=DiscordSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    system_state: str = ""
    default_resource_prompt: str = ""
