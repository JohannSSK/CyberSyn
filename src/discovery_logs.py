"""Bounded, offline parsing of structured network metadata. No network client."""

import csv
import io
import ipaddress
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

MAX_LOG_LINES = 2000
MAX_LOG_BYTES = 192 * 1024
DATA_SIGNALS = ("client_data", "source_code", "contracts", "hr_data", "financial",
                "credentials", "large_upload", "general")
SENSITIVE_SIGNALS = frozenset(DATA_SIGNALS[:6])
ALIASES = {
    "time": ("timestamp", "time", "date"),
    "team": ("team", "department", "group"),
    "actor": ("user", "actor", "src_ip", "client_ip"),
    "host": ("url", "domain", "host", "destination"),
    "method": ("method",),
    "bytes_sent": ("bytes_sent", "bytes", "request_bytes"),
    "signal": ("data_category", "data_signal", "classification"),
}
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.ASCII)
TEAM = re.compile(r"[\w .-]{1,64}\Z")
ACTOR = re.compile(r"[\w.@+-]{1,64}\Z")
UNSAFE_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]")
METHODS = frozenset("GET HEAD POST PUT DELETE CONNECT OPTIONS TRACE PATCH DNS PROPFIND REPORT".split())
UPLOAD_METHODS = {"POST", "PUT", "PATCH"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
DATE_TOKEN = r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?)?"
EPOCH = r"\d{9,11}(?:\.\d{1,9})?"
TIMESTAMP = re.compile(rf"^(?P<time>{DATE_TOKEN}|{EPOCH})(?:\s+|$)")
SQUID = re.compile(rf"^(?P<time>{EPOCH})\s+\d+\s+(?P<actor>\S+)\s+\w+/\d+\s+\d+\s+"
                   r"(?P<method>[A-Z]+)\s+(?P<host>\S+)(?:\s+(?P<user>\S+))?(?:\s|$)")
COMBINED = re.compile(r'^\s*(?P<actor>\S+)\s+\S+\s+(?P<user>[^\s\[]+)\s+\[(?P<time>[^\]]+)\]\s+"'
                      r'(?P<method>[A-Z]+)\s+(?P<host>\S+)(?:\s+HTTP/[\d.]+)?"(?:\s|$)')
REQUEST_BYTES = re.compile(r"(?:^|\s)(?:bytes_sent|request_bytes)=([0-9]{1,19})(?=\s|$)", re.I)
SYSLOG_TIME = re.compile(r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<clock>\d\d:\d\d:\d\d)\s")
DNSMASQ = re.compile(r"(?:^|\s)query\[[A-Z0-9]+\]\s+(?P<host>\S+)\s+from\s+(?P<actor>\S+)(?:\s|$)")
BIND = re.compile(r"\bclient\s+(?:@\S+\s+)?(?P<actor>[^#\s]+)#\d+[^\n]*?\bquery:\s+(?P<host>\S+)\s+IN\s+[A-Z0-9]+\b")


class LogFormatError(ValueError):
    """Don't put untrusted fields in error messages."""


def utc_text(when):
    return when.astimezone(timezone.utc).isoformat(timespec="microseconds")


def split_host(value):
    """Return (hostname, port) without looking up the DNS name, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or UNSAFE_TEXT.search(text) or any(c.isspace() for c in text) or "\\" in text:
        return None
    try:
        # An unbracketed IPv6 literal is usable in DNS logs and custom domains.
        if ":" in text and "%" not in text:
            try:
                return ipaddress.IPv6Address(text).compressed, None
            except ValueError:
                pass
        parts = urlsplit(text if re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:)?//", text) else "//" + text)
        if parts.scheme not in ("", "http", "https", "dns") or not parts.hostname:
            return None
        authority = parts.netloc.rsplit("@", 1)[-1]
        if not re.fullmatch(r"(?:\[[0-9a-fA-F:.]+\]|[^:\[\]]+)(?::[0-9]{1,5})?", authority):
            return None
        host, port = parts.hostname.removesuffix("."), parts.port
        if port == 0 or "%" in host:
            return None
        try:
            return ipaddress.ip_address(host).compressed, port
        except ValueError:
            if ":" in host:  # not an IPv6 address
                return None
        host = host.encode("idna").decode("ascii").lower()
        if len(host) <= 253 and all(LABEL.fullmatch(part) for part in host.split(".")):
            return host, port
    except (ValueError, UnicodeError):
        pass
    return None


def effective_host(value, host=None):
    """Include the transport's default port for matching, not for log storage."""
    host = host or split_host(value)
    if host and host[1] is None:
        scheme, _, _ = value.strip().lower().partition("://")
        return host[0], {"http": 80, "https": 443}.get(scheme)
    return host


def host_text(host):
    name, port = host
    return name if port is None else f"[{name}]:{port}" if ":" in name else f"{name}:{port}"


def _date(value, now):
    if not value or value == "-":
        return utc_text(now)
    if re.fullmatch(EPOCH, value):
        return utc_text(datetime.fromtimestamp(float(value), timezone.utc))
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        # Common proxy access log timestamp, independent of the server locale.
        m = re.fullmatch(r"(\d\d)/([A-Za-z]{3})/(\d{4}):([\d:]{8}) ([+-]\d{4})", value)
        if not m:
            raise
        day, month, year, clock, offset = m.groups()
        dt = datetime.fromisoformat(f"{year}-{MONTHS.index(month.title()) + 1:02d}-{day}T{clock}{offset}")
    return utc_text(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _syslog_date(line, now):
    m = SYSLOG_TIME.match(line)
    if not m:
        return None
    month = MONTHS.index(m["month"]) + 1
    dt = datetime.fromisoformat(f"{now.year}-{month:02d}-{int(m['day']):02d}T{m['clock']}").replace(tzinfo=timezone.utc)
    # A December entry imported in January belongs to the previous year.
    if dt > now + timedelta(days=1):
        dt = dt.replace(year=dt.year - 1)
    return dt.isoformat()


def _plain_fields(line, now):
    for pattern in (SQUID, COMBINED):
        m = pattern.match(line)
        if m:
            values = m.groupdict()
            values["actor"] = values["user"] if values["user"] not in (None, "-") else values["actor"]
            # Their positional byte field is usually the *response* size. Use
            # a request-size extension if present, never infer uploads from it.
            size = REQUEST_BYTES.search(line, m.end())
            values["bytes_sent"] = size[1] if size else ""
            return values
    stamp = TIMESTAMP.match(line)
    time = stamp["time"] if stamp else None
    for pattern in (DNSMASQ, BIND):
        m = pattern.search(line)
        if m:
            return {**m.groupdict(), "time": time or _syslog_date(line, now), "method": "DNS"}
    fields = (line[stamp.end():] if stamp else line).split()
    # Simple exports: [timestamp] actor METHOD dest [request-bytes]
    # or [timestamp] actor [query] dest for DNS.
    if len(fields) == 2:
        actor, host = fields
        return {"time": time, "actor": actor, "method": "DNS", "host": host}
    if len(fields) in (3, 4):
        actor, method, host = fields[:3]
        if method.lower() in ("query", "dns"):
            method = "DNS"
        return {"time": time, "actor": actor, "method": method, "host": host,
                "bytes_sent": fields[3] if len(fields) == 4 else ""}
    raise ValueError


def _csv_fields(content):
    reader = csv.reader(io.StringIO(content, newline=""), strict=True)
    header = [value.strip().lower() for value in next(reader, [])]
    if len(header) != len(set(header)):
        raise ValueError
    columns = {}
    for field, aliases in ALIASES.items():
        alias = next((name for name in aliases if name in header), None)
        if alias is not None:
            columns[field] = header.index(alias)
    if "host" not in columns:
        raise ValueError
    for row in reader:
        if not row:
            continue
        if len(row) != len(header):
            raise ValueError
        yield {field: row[index] for field, index in columns.items()}


def _normalise(fields, now):
    get = lambda key: (fields.get(key) or "").strip()
    destination = get("host")
    host = split_host(destination)
    if host is None:
        raise ValueError
    team, actor = get("team") or "Unassigned", get("actor") or "-"
    if not TEAM.fullmatch(team):
        raise ValueError
    if not ACTOR.fullmatch(actor):
        if not re.fullmatch(r"[0-9a-fA-F:.]{1,64}", actor):
            raise ValueError
        actor = ipaddress.ip_address(actor).compressed
    method = get("method").upper() or "DNS"
    if method not in METHODS:
        raise ValueError
    size = get("bytes_sent")
    if size not in ("", "-") and not re.fullmatch(r"[0-9]{1,19}", size):
        raise ValueError
    size = 0 if size in ("", "-") else int(size)
    if size >= 2**63:
        raise ValueError
    signal = get("signal").lower()
    if signal not in DATA_SIGNALS:
        signal = "large_upload" if method in UPLOAD_METHODS and size >= 4096 else "general"
    return {"observed_at": _date(get("time"), now), "team": team, "actor": actor,
            "host": host_text(host), "destination": effective_host(destination, host),
            "method": method, "bytes_sent": size, "data_signal": signal}


def parse_logs(content, now):
    """Return only allowlisted metadata; no raw rows, paths or payload columns."""
    if not isinstance(content, str) or not content.strip() or UNSAFE_TEXT.search(content):
        raise LogFormatError("Enter non-empty UTF-8 log text.")
    try:
        length = len(content.encode("utf-8"))
    except UnicodeError:
        raise LogFormatError("Enter non-empty UTF-8 log text.") from None
    lines = content.removeprefix("\ufeff").splitlines()
    if length > MAX_LOG_BYTES or len(lines) > MAX_LOG_LINES:
        raise LogFormatError("Import at most 2,000 lines and 192 KiB at a time.")
    content = content.removeprefix("\ufeff").lstrip(" \t\r\n")
    if not content:
        raise LogFormatError("Enter non-empty UTF-8 log text.")
    first = content.splitlines()[0]
    header_words = {word.strip(' \t\r"').lower() for word in first.split(",")}
    csv_like = bool(header_words.intersection(ALIASES["host"])) or "," in first.split(" ", 1)[0]
    try:
        fields = _csv_fields(content) if csv_like else (_plain_fields(line, now) for line in lines if line.strip())
        return [_normalise(row, now) for row in fields]
    except (csv.Error, ValueError, OverflowError, OSError):
        raise LogFormatError("Malformed logs. Use a CSV header or supported proxy or DNS lines.") from None


def sample_logs(now):
    """Service destinations are real catalogue domains; every actor and record is synthetic."""
    rows = (
        ("Sales", "chat.deepseek.com", "client_data"), ("Legal", "grok.com", "contracts"),
        ("HR", "character.ai", "hr_data"), ("Engineering", "api2.cursor.sh", "source_code"),
        ("Finance", "api.openai.com", "financial"), ("Sales", "perplexity.ai", "client_data"),
        ("Legal", "claude.ai", "general"), ("HR", "people.example", "general"),
        ("Engineering", "api.groq.com", "source_code"), ("Finance", "api.deepseek.com", "financial"),
        ("Sales", "chat.deepseek.com", "client_data"), ("Legal", "api.cohere.com", "contracts"),
        ("HR", "gemini.google.com", "general"), ("Engineering", "api.githubcopilot.com", "source_code"),
        ("Finance", "ledger.example", "general"), ("Sales", "chatgpt.com", "general"),
        ("Legal", "perplexity.ai", "client_data"), ("HR", "grok.com", "hr_data"),
        ("Engineering", "127.0.0.1:11434", "general"), ("Finance", "api.together.xyz", "general"),
        ("Sales", "crm.example", "general"), ("Legal", "chat.mistral.ai", "general"),
        ("Engineering", "huggingface.co", "general"), ("HR", "openrouter.ai", "general"),
        ("Finance", "api.x.ai", "credentials"),
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(("timestamp", "team", "actor", "destination", "method", "bytes_sent", "data_signal"))
    for i, (team, host, signal) in enumerate(rows):
        writer.writerow((utc_text(now - timedelta(hours=3 + 6 * i)), team, f"192.0.2.{10 + i}", host,
                         "GET" if signal == "general" else "POST", 600 if signal == "general" else 4200 + i * 105, signal))
    return out.getvalue()
