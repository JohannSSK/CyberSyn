"""Workspace AI service inventory, offline discovery and outbound tool policy."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint

from auth import admin_from_token
from block_log import record_activity
from config import DB_FILE, ROUTES
from db import get_db
from discovery_logs import (DATA_SIGNALS, SENSITIVE_SIGNALS, TEAM, UNSAFE_TEXT, LogFormatError,
                            effective_host, host_text, parse_logs, sample_logs, split_host, utc_text)
from errors import ApiError
from providers import BY_KEY, normalise_model
from web import ok, require_body, to_int

STATUSES = ("approved", "restricted", "unapproved")
MAX_EVENTS = 200
shadow_api = Blueprint("shadow_api", __name__)


def risk_level(score):
    return "critical" if score >= 85 else "high" if score >= 65 else "medium" if score >= 35 else "low"


def _tool(key, name, vendor, category, domains, score, hosting, training, rationale, status,
          provider_key=None):
    return {"tool_key": key, "name": name, "vendor": vendor, "category": category, "domains": domains.split(),
            "provider_key": provider_key if provider_key else (key if key in BY_KEY else None),
            "risk_score": score, "risk_level": risk_level(score), "hosting": hosting,
            "training_policy": training, "gdpr_summary": rationale, "default_status": status}


# Baseline assessments, not compliance certifications. Paid, API and consumer
# terms differ; the rationale identifies what an administrator should verify.
CATALOGUE = (
    _tool("openai", "OpenAI / ChatGPT", "OpenAI", "assistant", "chatgpt.com chat.openai.com api.openai.com", 48,
          "US / EU DPA", "api_no_web_opt_out", "API and business data are not used for training by default; review retention and consumer controls.", "approved"),
    _tool("anthropic", "Anthropic / Claude", "Anthropic", "assistant", "claude.ai api.anthropic.com", 44,
          "US / EU DPA", "api_no_web_opt_out", "Commercial and consumer terms differ; verify retention and cross-border transfers for the account in use.", "approved"),
    _tool("gemini", "Google Gemini", "Google", "assistant", "gemini.google.com generativelanguage.googleapis.com", 55,
          "US / EU DPA", "api_no_web_opt_out", "Paid API and consumer or unpaid services have different data terms; verify which tier is enabled.", "approved"),
    _tool("copilot", "Microsoft / GitHub Copilot", "Microsoft / GitHub", "coding", "copilot.microsoft.com githubcopilot.com api.githubcopilot.com", 69,
          "US / EU DPA", "opt_out_only", "Business and individual controls differ; verify policies for code snippets and telemetry.", "unapproved"),
    _tool("deepseek", "DeepSeek", "DeepSeek", "assistant", "chat.deepseek.com api.deepseek.com", 91,
          "Non-EU", "trains_by_default", "The hosted service describes processing in China; assess transfers and retention before use.", "unapproved"),
    _tool("xai", "xAI Grok", "xAI", "assistant", "grok.com x.ai api.x.ai", 82,
          "Non-EU", "opt_out_only", "Consumer and API data controls differ; verify training settings and the transfer basis.", "unapproved"),
    _tool("perplexity", "Perplexity", "Perplexity", "search", "perplexity.ai api.perplexity.ai", 76,
          "Non-EU", "opt_out_only", "Consumer and enterprise data controls differ; assess the handling of search queries and uploads.", "unapproved"),
    _tool("mistral", "Mistral AI", "Mistral AI", "assistant", "chat.mistral.ai api.mistral.ai", 37,
          "EU", "api_no_web_opt_out", "EU-based vendor; check account-specific data location, retention and training terms.", "approved"),
    _tool("cohere", "Cohere", "Cohere", "assistant", "coral.cohere.com api.cohere.com api.cohere.ai", 53,
          "Non-EU", "opt_out_only", "Confirm the deployment region and the account's training and logging controls.", "restricted"),
    _tool("openrouter", "OpenRouter", "OpenRouter", "gateway", "openrouter.ai", 72,
          "Varies by provider", "opt_out_only", "Requests may reach multiple downstream providers; check routing and each provider's retention terms.", "restricted"),
    _tool("groq", "Groq", "Groq", "gateway", "groq.com api.groq.com", 54,
          "Non-EU", "never", "Check account-specific logging exceptions, processing region and contractual terms.", "restricted"),
    _tool("together", "Together AI", "Together AI", "gateway", "together.ai api.together.xyz", 59,
          "Non-EU", "never", "Check regional processing and the retention terms of the selected inference product.", "restricted"),
    _tool("huggingface", "Hugging Face", "Hugging Face", "model_hub", "huggingface.co hf.space", 71,
          "Varies by provider", "opt_out_only", "Spaces and inference providers can have different operators and data handling.", "unapproved"),
    _tool("cursor", "Cursor", "Anysphere", "coding", "cursor.sh api2.cursor.sh cursor.com", 78,
          "Non-EU", "opt_out_only", "Review Privacy Mode and subprocessors before sending repositories or code fragments.", "unapproved"),
    _tool("character_ai", "Character.AI", "Character.AI", "assistant", "character.ai", 88,
          "Non-EU", "trains_by_default", "Consumer chat terms allow use to improve the service; do not assume enterprise controls.", "unapproved"),
    _tool("ollama", "Ollama (local)", "Ollama", "local", "localhost:11434 127.0.0.1:11434 [::1]:11434", 10,
          "On-premise", "never", "This entry covers loopback inference only; verify that cloud features are disabled.", "approved"),
)
CATALOGUE_BY_KEY = {tool["tool_key"]: tool for tool in CATALOGUE}


def inventory(db, parent_id):
    rows = {row["tool_key"]: row for row in db.execute("SELECT * FROM AI_TOOL_POLICY WHERE Parent_id=?", (parent_id,))}
    tools = [(tool, rows.get(key)) for key, tool in CATALOGUE_BY_KEY.items()]
    for key, row in sorted(rows.items()):
        if row["domain"]:
            tools.append((_tool(key, row["name"], "Workspace-defined", "gateway", row["domain"], 75,
                                "Not verified", None, "Workspace-defined domain. Verify hosting, retention and training terms before approving.",
                                "unapproved", "custom"), row))
    return [dict(tool, custom=bool(row and row["domain"]), status=row["status"] if row else tool["default_status"],
                 note=row["note"] if row else "", updated_at=row["updated_at"] if row else None,
                 updated_by=row["updated_by"] if row else None) for tool, row in tools]


def _domain_match(host, pattern):
    name, port = host
    domain, required_port = pattern
    if required_port is not None and port != required_port:
        return False
    return name == domain or ("." in domain and not domain.replace(".", "").isdigit() and name.endswith("." + domain))


class ToolDomains:
    """A domain index reused across the rows of one import."""

    def __init__(self, tools):
        self.patterns = [(split_host(domain), tool) for tool in tools for domain in tool["domains"]]

    def find(self, host):
        if host:
            return next((tool for pattern, tool in self.patterns if _domain_match(host, pattern)), None)
        return None

    def overlaps(self, host):
        for pattern, _ in self.patterns:
            name, port = host
            domain, required_port = pattern
            if port is not None and required_port is not None and port != required_port:
                continue
            if _domain_match((name, required_port), pattern) or _domain_match((domain, port), host):
                return True
        return False


def resolved_provider(provider, model):
    """Model namespaces for legacy Auto; explicit connections take precedence."""
    if provider and provider != "auto":
        return provider
    name = normalise_model(model).lower()
    prefix, slash, _ = name.partition("/")
    if slash:
        return {"together_ai": "together", "cohere_chat": "cohere", "ollama_chat": "ollama",
                "text-completion-openai": "openai"}.get(prefix, prefix)
    for family, key in (("gpt-", "openai"), ("chatgpt-", "openai"), ("o1", "openai"),
                        ("o3", "openai"), ("o4", "openai"), ("deepseek-", "deepseek"),
                        ("grok-", "xai"), ("mistral-", "mistral"), ("command-", "cohere"),
                        ("sonar", "perplexity")):
        if name.startswith(family):
            return key
    return None


def unapproved_destination(db, parent_id, provider, api_base, model):
    tools = inventory(db, parent_id)
    named = resolved_provider(provider, model)
    host_tool = ToolDomains(tools).find(effective_host(api_base))
    if host_tool and host_tool["status"] == "unapproved":
        return host_tool
    # "custom" is a connection type, not a vendor — classify it by host only.
    return next((tool for tool in tools if named and named != "custom" and
                 named in (tool["provider_key"], tool["tool_key"]) and tool["status"] == "unapproved"), None)


def _access(data, db, *, page=False):
    parent_id = to_int(data.get("Parent_id"))
    if "Parent_id" in data and parent_id is None:
        raise ApiError("'Parent_id' must be a positive integer.", 400)
    # Reads (like TEAM) may infer scope from the credential. Require explicit
    # workspace scope on writes, including writes with a primary cookie.
    if not page and parent_id is None:
        raise ApiError("'Parent_id' must be a positive integer.", 400)
    admin = admin_from_token(DB_FILE, data.get("admin_token", data.get("token")),
                             parent_id=parent_id, page=page, consume=not page, con=db)
    if admin is None:
        raise ApiError("Your session has ended. Sign in again." if page else
                       "This Shadow AI change requires administrator approval.", 401)
    return admin


def _filters(data):
    days = data.get("days", 7)
    if isinstance(days, str) and days in ("0", "7", "30"):
        days = int(days)
    if type(days) is not int or days not in (0, 7, 30):
        raise ApiError("Choose a window of 7 days, 30 days or all time.", 400)
    status, team, signal = (data.get(key, "") for key in ("status", "team", "data_signal"))
    if (status not in ("", *STATUSES) or signal not in ("", *DATA_SIGNALS) or
            not isinstance(team, str) or (team and not TEAM.fullmatch(team))):
        raise ApiError("Invalid Shadow AI filter.", 400)
    return days, status, team, signal


def _counts():
    return dict(total_events=0, unapproved_events=0, client_data_to_unapproved=0, sensitive_data_to_unapproved=0)


def _count(bucket, event, status):
    bucket["total_events"] += 1
    if status == "unapproved":
        bucket["unapproved_events"] += 1
        bucket["client_data_to_unapproved"] += event["data_signal"] == "client_data"
        bucket["sensitive_data_to_unapproved"] += event["data_signal"] in SENSITIVE_SIGNALS


def _discovery(db, pid, tools, filters, now):
    days, status, team, signal = filters
    where, args = ["Parent_id=?"], [pid]
    if days:
        where.extend(("observed_at>=?", "observed_at<=?"))
        args.extend((utc_text(now - timedelta(days=days)), utc_text(now)))
    if team:
        where.append("team=?")
        args.append(team)
    if signal:
        where.append("data_signal=?")
        args.append(signal)
    rows = db.execute("SELECT id, observed_at, team, actor, host, tool_key, tool_name, method, bytes_sent, "
                      "data_signal, imported_at FROM DISCOVERY_EVENTS WHERE " + " AND ".join(where) +
                      " ORDER BY observed_at DESC, id DESC", args)
    by_key = {tool["tool_key"]: tool for tool in tools}
    summary, by_team, names = _counts(), defaultdict(_counts), defaultdict(set)
    discovered, unapproved, events = set(), set(), []
    for row in rows:
        key, name, team_name = row["tool_key"], row["tool_name"], row["team"]
        # A removed custom domain loses its approval, not its historical events.
        live = by_key.get(key)
        current, score = (live["status"], live["risk_score"]) if live else ("unapproved", 75)
        if status and current != status:
            continue
        discovered.add(key)
        if current == "unapproved":
            unapproved.add(key)
            names[team_name].add(name)
        _count(summary, row, current)
        _count(by_team[team_name], row, current)
        if len(events) < MAX_EVENTS:
            events.append(dict(row, status=current, risk_score=score, risk_level=risk_level(score)))
    ranked = [dict(counts, team=label, unapproved_tools=sorted(names[label])) for label, counts in by_team.items()]
    ranked.sort(key=lambda row: (-row["client_data_to_unapproved"], -row["sensitive_data_to_unapproved"],
                                 -row["unapproved_events"], -row["total_events"], row["team"]))
    summary.update(tools_discovered=len(discovered), unapproved_tools_active=len(unapproved))
    return dict(summary=summary, by_team=ranked, events=events)


@shadow_api.post(ROUTES["SHADOW_AI"])
def shadow_list():
    data = require_body()
    db = get_db()
    with db:
        db.execute("BEGIN")
        admin = _access(data, db, page=True)
        pid = admin["id"]
        tools = inventory(db, pid)
        result = _discovery(db, pid, tools, _filters(data), datetime.now(timezone.utc))
        teams = [row[0] for row in db.execute("SELECT DISTINCT team FROM DISCOVERY_EVENTS WHERE Parent_id=? ORDER BY team", (pid,))]
    return ok(inventory=tools, teams=teams, **result)


def _short_text(value, limit, message, *, required=False):
    if (not isinstance(value, str) or len(value) > limit or UNSAFE_TEXT.search(value) or
            any(c in value for c in "\r\n\t") or (required and not value.strip())):
        raise ApiError(message, 400)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ApiError(message, 400) from None
    return value.strip()


def _custom_domain(value):
    error = "Enter a hostname, optionally with a port, without a scheme, path or wildcard."
    text = _short_text(value, 261, error, required=True)
    host = split_host(text)
    if not host or any(ch in text for ch in "/@?#*"):
        raise ApiError(error, 400)
    name, _ = host
    if "." not in name and ":" not in name and name != "localhost":
        raise ApiError(error, 400)
    return host


@shadow_api.post(ROUTES["SHADOW_AI_POLICY"])
def shadow_policy():
    data = require_body()
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        admin = _access(data, db)
        pid = admin["id"]
        tools = inventory(db, pid)
        method = data.get("method", "update")
        key = data.get("tool_key")
        if method == "add":
            host = _custom_domain(data.get("domain"))
            domain = host_text(host)
            if ToolDomains(tools).overlaps(host):
                raise ApiError("That domain overlaps an existing AI tool.", 409)
            name = _short_text(data.get("name", domain), 80, "Tool name must contain 1 to 80 characters.", required=True)
            key = "custom:" + domain
        elif method in ("update", "remove"):
            tool = next((item for item in tools if item["tool_key"] == key), None)
            if tool is None:
                raise ApiError("That AI tool was not found.", 404)
            if method == "remove" and not tool["custom"]:
                raise ApiError("Only workspace-defined tools can be removed.", 400)
            domain = tool["domains"][0] if tool["custom"] else None
            name = tool["name"] if tool["custom"] else None
        else:
            raise ApiError("Choose an AI tool policy operation: update, add or remove.", 400)
        if method == "remove":
            db.execute("DELETE FROM AI_TOOL_POLICY WHERE Parent_id=? AND tool_key=?", (pid, key))
        else:
            status = data.get("status", "unapproved" if method == "add" else None)
            if status not in STATUSES:
                raise ApiError("Choose approved, restricted or unapproved.", 400)
            note = _short_text(data.get("note", ""), 240, "Policy notes must fit on one line of at most 240 characters.")
            db.execute("INSERT INTO AI_TOOL_POLICY (Parent_id, tool_key, status, note, updated_at, updated_by, domain, name) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(Parent_id, tool_key) DO UPDATE SET "
                       "status=excluded.status, note=excluded.note, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                       (pid, key, status, note, utc_text(datetime.now(timezone.utc)), admin["username"], domain, name))
        # Deliberately omit arbitrary names and notes from the audit trail.
        record_activity(DB_FILE, pid, 0, "shadow_policy", f"{method}: {'custom' if domain else key}", con=db)
        updated = inventory(db, pid)
    return ok(tool=next((item for item in updated if item["tool_key"] == key), None), inventory=updated)


@shadow_api.post(ROUTES["SHADOW_AI_IMPORT"])
def shadow_import():
    data = require_body()
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        admin = _access(data, db)
        pid = admin["id"]
        if (any(key in data and not isinstance(data[key], bool) for key in ("sample", "clear")) or
                sum(("content" in data, data.get("sample") is True, data.get("clear") is True)) != 1):
            raise ApiError("Choose log content, sample or clear.", 400)
        now = datetime.now(timezone.utc)
        tools = inventory(db, pid)
        scanned = added = cleared = 0
        if data.get("clear"):
            cleared = db.execute("DELETE FROM DISCOVERY_EVENTS WHERE Parent_id=?", (pid,)).rowcount
            record_activity(DB_FILE, pid, 0, "shadow_clear", f"{cleared} events", con=db)
        else:
            try:
                rows = parse_logs(sample_logs(now) if data.get("sample") else data["content"], now)
            except LogFormatError as exc:
                raise ApiError(str(exc), 400) from None
            scanned = len(rows)
            domains = ToolDomains(tools)
            for row in rows:
                tool = domains.find(row["destination"])
                if tool is None:
                    continue
                db.execute("INSERT INTO DISCOVERY_EVENTS (Parent_id, observed_at, team, actor, host, tool_key, "
                           "tool_name, method, bytes_sent, data_signal, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (pid, row["observed_at"], row["team"], row["actor"], row["host"], tool["tool_key"], tool["name"],
                            row["method"], row["bytes_sent"], row["data_signal"], utc_text(now)))
                added += 1
            record_activity(DB_FILE, pid, 0, "shadow_import", f"{added} AI events / {scanned} rows", con=db)
        summary = _discovery(db, pid, tools, (7, "", "", ""), now)["summary"]
    return ok(lines_scanned=scanned, ai_events_added=added, non_ai_ignored=scanned - added, events_cleared=cleared, summary=summary)
