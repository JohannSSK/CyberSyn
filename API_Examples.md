# CyberSyn JSON API

All endpoints below are **POST**, with `Content-Type: application/json`. The route registry is [`includes/constants.json`](includes/constants.json). Accounts, identifiers, keys, and event data in these examples are synthetic; substitute values actually returned by your gateway.

## Authentication conventions

- **Browser:** `Api.post()` sends same-origin credentials, `X-CyberSyn-Request: 1` and `X-CyberSyn-Session: cookie`. Login/create sets an HttpOnly, SameSite=Lax, Path=/ cookie (`cybersyn_admin` or `cybersyn_member`, seven days). Cookie-authenticated requests require the custom request header; a supplied `Origin` must match the gateway. Use HTTPS; `Secure` is set on HTTPS or with `CYBERSYN_COOKIE_SECURE=1`. Browser-mode session responses omit the bearer value. The browser stores only non-secret identity/display metadata.
- **API clients:** you may ignore cookies and pass the returned `session_token` explicitly. Admin actions generally call this field `token`; settings/overrides call the approval `admin_token`. An explicit invalid token does not become a valid session simply because a cookie exists.
- **Member body:** in the history/action tables below, merge the listed fields into `{"Parent_id":"1","Employee_id":"2","session_token":"<member>"}`. Omit `session_token` when using the member cookie. An administrator cannot read a member's chat history with an administrator credential.
- Login, account creation and settings return **strings** for `Parent_id`/`Employee_id`. Chat IDs and roster `id`s are numbers. Positive digit strings are accepted as IDs; booleans are not. Zero is reserved for the workspace-default settings row.
- Ordinary success responses commonly include `"error":false,"error_message":"NULL"` (the literal string). Login and model discovery have their own shapes. Examples below show response fields rather than every field where indicated. Validation failures are `400`, expired/invalid credentials `401`, CSRF or closed signup `403`, missing chats `404`, and duplicate usernames `409`. Repeated failed credential operations return `429` and `Retry-After`. Bodies over the configured limit return `413`.

## 1. `POST /api/admin/login`

Request: `{"username":"owner","password":"<exact password>"}`. Success (`200`, API client):

```json
{"success":true,"Parent_id":"1","username":"owner","reason":"NULL","session_token":"<admin>"}
```

Both an unknown username and an incorrect password return `401`:

```json
{"success":false,"Parent_id":"NULL","reason":"Invalid username or password."}
```

## 2. `POST /api/admin`

**Create:** `{"method":"add","username":"owner","password":"Example pass 123"}` → `201`:

```json
{"error":false,"Parent_id":"1","username":"owner","session_token":"<admin>","error_message":"NULL"}
```

Bootstrap is open **only while there are zero administrators**. For another account supply `signup_token` matching `CYBERSYN_ADMIN_SIGNUP_TOKEN`, a current admin session/one-time approval, or explicitly enable open signup. The first-run check and insert are atomic. New passwords for *both roles* must contain at least eight characters, a letter and a digit (maximum 256). Usernames are limited to 64 characters. Leading and trailing password spaces are significant. Existing accounts need not change passwords to sign in.

**Remove:** `{"method":"remove","username":"owner","password":"<exact password>"}` → `{"error":false,"Parent_id":"1","error_message":"NULL"}`. Unknown users and wrong passwords receive the same `401`. Account rows, all workspace sessions, chats, settings, Shadow AI policy and imported discovery events are deleted together. Statistics and audit events are retained.

### Approval and administrator lifecycle

| Endpoint | Request example | Result |
|---|---|---|
| `POST /api/admin/approve` | `{"Parent_id":"1","username":"owner","password":"<password>","scope":"once"}` | Login success shape with `admin_token` instead of `session_token`; no session cookie for `once`. Omitting `scope` means `once`. If supplied, `Parent_id` must match. |
| `POST /api/admin/password` | `{"token":"<admin or once>","current_password":"<current>","new_password":"Another pass 123"}` | `200` ordinary success. Revokes **all** admin sessions and approvals; sign in again. |
| `POST /api/admin/session` | `{"token":"<admin>"}` or `{}` with admin cookie | `{"success":true,"Parent_id":"1","username":"owner"}` or `401 {"success":false}`. |
| `POST /api/admin/logout` | `{"token":"<token to revoke>"}`; browser `{}` | `{"success":true}`. Browser `{ "scope":"page" }` locks the page grant without ending a primary admin session. |
| `POST /api/admin/team/list` | `{"token":"<admin or page>"}` | `members`, e.g. `[{"id":2,"username":"member_demo","created_at":"2026-11-18 12:00:00"}]`; used by the removal picker. |
| `POST /api/admin/employee/override/check` | `{"Parent_id":"1","admin_token":"<admin or page>"}` | `{"error":false,"allowed":true,"error_message":"NULL"}` for a live workspace page/session grant. Does not consume or unlock a write grant. |

A **once** grant expires after five minutes and is atomically consumed on use; reuse cannot authorise a second write. A **page** grant (`scope:"page"`) lasts at most 15 minutes and grants read-only roster, statistics, settings and Shadow AI access, not policy changes or overrides. Browser mode sets a separate HttpOnly `cybersyn_page` cookie; API clients receive `admin_token`. “Lock now” revokes the grant on the server. Approval tokens cannot evict a primary login session.

For administrator reads including Shadow AI, the explicit token takes precedence, then `cybersyn_admin`, then `cybersyn_page`. An invalid credential does not fall back to a different identity. Successful administrator login, creation or deletion revokes the page grant presented by that browser and clears its page cookie.

## 3. `POST /api/admin/employee`

**Add** (workspace administrator):

```json
{"method":"add","Parent_id":"1","token":"<admin>","username":"member_demo","password":"Example staff 123"}
```

`201 {"error":false,"Employee_id":"2","error_message":"NULL"}`. A member inherits a **copy** of workspace defaults, including the encrypted connection key. A duplicate username in the same workspace returns `409`.

**Offboard** (UI: `/delete-member`):

```json
{"method":"remove","Parent_id":"1","token":"<admin or once>","username":"member_demo","admin_password":"<administrator password>"}
```

Both a workspace admin credential **and** the administrator's current password are required. The member's password is neither requested nor accepted as confirmation. `200` ordinary success; their sessions, settings and chats are deleted in one transaction, not their audit/statistics records.

## 4. `POST /api/admin/employee/login`

Sign in directly with `{"workspace":"owner","username":"member_demo","password":"<exact member password>"}`.
`workspace` is the administrator's username (1–64 characters), not an administrator credential. Legacy clients can use `"Parent_id":"1"` **instead** of `workspace`. With neither field, the only workspace is selected automatically; with multiple workspaces the server returns `400` (`"Enter your workspace name to sign in."`). A missing workspace name match, zero administrator accounts, an unknown member or a wrong password uses the same generic `401` and dummy password verification for missing accounts. Password whitespace is significant.

A fresh member receives:

```json
{
  "error": false, "Parent_id": "1", "Employee_id": "2", "username": "member_demo",
  "session_token": "<member>", "chats": [], "chat_id": null, "CHAT_LOGS": [], "error_message": "NULL",
  "settings": {
    "Parent_id": "1", "Employee_id": "2", "check1": true, "check2": true, "check3": true, "block_code": false,
    "action_check1": "block", "action_check2": "block", "action_check3": "block", "action_code": "allow",
    "restore_redactions": false, "API_KEY": "", "API_KEY_MASK": "", "MODEL_NAME": "gpt-4o-mini", "PROVIDER": "auto", "API_BASE": ""
  }
}
```

Returning members get their chat list and latest chat/messages. On success, the browser's primary admin cookie and page grant are **revoked and cleared**, not passed into the member workspace. Unknown member/wrong password: `401` with `error`, `Employee_id:"NULL"`, `CHAT_LOGS:[]`, and `error_message:"Invalid employee username or password."`.

| Endpoint | Additional fields | Result |
|---|---|---|
| `POST /api/admin/employee/account` | `{"action":"username","current_password":"<current>","new_username":"member_demo_2"}` | Success with `username`. Existing names in the workspace return `409`. |
| `POST /api/admin/employee/account` | `{"action":"password","current_password":"<current>","new_password":"New staff pass 321"}` | Revokes every prior member session. Returns a new `session_token` (refreshed HttpOnly cookie for browsers). |
| `POST /api/admin/employee/logout` | `{"session_token":"<member>"}` or `{}` with cookie | Revokes this session and clears the cookie; ordinary success. |

## 5. `POST /api/admin/employee/settings`

**Read**: use the member body for your own settings, or use a workspace administrator session or page grant. **Write**: include a workspace administrator session or an `approval_once` and the fields to change. A page grant never authorises writes. A member cannot read or write the workspace default (`Employee_id:0`) with their member session alone.

```json
{"Parent_id":"1","Employee_id":"2","admin_token":"<once>","action_check1":"redact","action_check2":"warn","action_code":"allow","restore_redactions":true}
```

Response, assuming a previously saved connection:

```json
{
  "Parent_id": "1", "Employee_id": "2", "check1": true, "check2": true, "check3": true, "block_code": false,
  "action_check1": "redact", "action_check2": "warn", "action_check3": "block", "action_code": "allow",
  "restore_redactions": true, "API_KEY": "", "API_KEY_MASK": "****7890", "MODEL_NAME": "gpt-4o-mini", "PROVIDER": "openai", "API_BASE": ""
}
```

- `action_check1` (Personal & Greek IDs), `action_check2` (Confidential context) and `action_code` (Proprietary source code) accept `allow`, `warn`, `redact`, or `block`. `action_check3` (Prompt injection) accepts `allow`, `warn`, or `block`; `redact` is a `400`. By default the first three rules block and the code rule allows.
- Legacy `check1`/`check2`/`check3`/`block_code` still accept booleans: `false` is `allow`; `true` is `block`. If both forms are supplied, the corresponding action wins. Read booleans are `true` for any action other than `allow`.
- `restore_redactions` is a boolean, off by default. It restores only exact request-local placeholders in the immediate reply, never in saved history.
- `Employee_id:0` reads/updates the template for **future** members. `also_default:true` also saves the submitted checks to that template. When saving connection settings, it copies the resulting connection as a unit (provider, base, model and encrypted key), so the new destination never inherits a different default key. No other existing member changes.
- `API_KEY:""` means **keep** the saved secret; `CLEAR_API_KEY:true` means **delete** it. `API_BASE:""` clears the custom base. Nonempty bases can contain paths, not credentials, query strings or fragments. The API never returns the encrypted blob or the plaintext key; keys shorter than eight characters are masked completely.

### Discovery

| Endpoint | Request | Result |
|---|---|---|
| `POST /api/admin/employee/providers` | Member session (or primary administrator session) | `{"providers":[…],"message":null}`. Entries carry `key`, `label` and, for named providers, hints and key/base requirements. |
| `POST /api/admin/employee/models` | Member session plus optional `{"provider":"groq","API_KEY":"<pasted key>"}` or `API_BASE` | `{"models":["groq/example"],"provider":"groq","provider_label":"Groq","message":null}` (model names vary). |

With no pasted key, discovery uses the saved provider/base/key. A changed destination requires workspace admin approval; a new HTTP base must first be saved. Auto only probes the service matching a recognized prefix. For ambiguous keys, **choose the provider before entering the key**. Unknown formats return `400` without probing unrelated providers. A provider refusal returns `502` with `models:[]`, `message`, and `tried`. Redirects across origins lose all provider authentication headers.

## 6. `POST /api/admin/employee/chat`

**6A — ordinary prompt:** send the member body plus `{"prompt":"What is the capital of Greece?"}`. The server uses the **saved** checks, model, key and base. Per-request policy fields, provider, model and keys do not override saved settings. Precedence is block → warn → redact → allow. A new chat is created only after a successful answer:

```json
{"error":false,"blocked":false,"warned":false,"redacted":false,"action":"allow","reply_message":"Athens.","error_message":"NULL","block_info":"NULL","chat_id":7,"message_id":"c88a9b82a35e28a0"}
```

**6B — code review in an existing chat:** with this member’s code blocking off, code alone is not a reason for refusal:

```json
{"Parent_id":"1","Employee_id":"2","session_token":"<member>","chat_id":7,"prompt":"Review this function:\n\ndef total(items):\n    return sum(items)"}
```

With this member's code blocking on, the context scanner can return `computer source code`. In either case, enabled secret/PII and injection checks still inspect the prompt.

**6C — blocked:** HTTP `200` with `error:false`, `blocked:true`, `action:"block"`, `reply_message:"NULL"`, a reason and `block_info`. For a local check, `block_info` includes the stage, cause, line (1-based), start/end offsets (0-based, end exclusive), snippet and match list. Evidence is returned only to the sender and not logged. A denied destination returns `stage:"policy"`, `main_cause:"UNAPPROVED_AI_TOOL"` and `tool_name`, without prompt evidence. A failed, invalid or timed-out enabled scanner returns `503` and no provider call.

**6D — warned:** HTTP `200` with `error:false`, `blocked:false`, `warned:true`, `redacted:false`, `action:"warn"`, `reply_message:"NULL"`, `block_info:"NULL"` and `error_message` explaining the pause. Example `warn_info`:

```json
{"stage":"check1","main_cause":"EMAIL","line":1,"start_offset":0,"end_offset":26,"snippet":"member-demo@client.example","matches":[{"stage":"check1","cause":"EMAIL","line":1,"start_offset":0,"end_offset":26,"snippet":"member-demo@client.example"}],"will_redact":false}
```

Nothing is sent or saved to a chat on a pause. To proceed, send the request again with `confirm_warn:true` (a boolean, not a string). All current enabled checks run again; any block still wins, and applicable redaction is never skipped. The audit records only the warning and confirmation metadata.

**6E — redacted:** HTTP `200` with the following shape (illustrative model reply):

```json
{
  "error": false, "blocked": false, "warned": false, "redacted": true, "action": "redact",
  "reply_message": "The address is [EMAIL_1].", "redacted_prompt": "Review [EMAIL_1]",
  "redaction_info": {"count": 1, "categories": ["EMAIL"], "placeholders": ["[EMAIL_1]"], "restored": false},
  "chat_id": 7, "message_id": "c88a9b82a35e28a0", "error_message": "NULL", "block_info": "NULL"
}
```

`count` is the number of replaced spans (including repeats); `placeholders` lists distinct tokens. The provider receives only the sanitized prompt. History contains that prompt, the unrestored reply, `redacted:true` and safe `redaction_info`. If local restoration substituted any exact tokens, the immediate `reply_message` contains the restored text and its receipt has `restored:true`. The map is never sent, saved or logged; reopening the chat cannot restore those values.

**6F — approved exception:** send `{"prompt":"<reviewed text>","bypass":true,"admin_token":"<fresh once grant>"}` with the member body. A live workspace admin session also works, but a page grant does not. Missing or replayed approval returns `401`. Approval can release a tool or local block; saved redact rules still apply. The audit records the approval, not the prompt or matches.

**6G — other errors:** no saved key for a provider that needs one → `400`; provider error → `502` without the library exception or key; a missing or foreign chat (including deletion during a provider call) → `404`.

## Chat history and regeneration

Each request below needs the **member body**. Edits affect local history only; if a saved redaction rule detects private spans, the edit stores a sanitized prompt. Regeneration applies the same tool and prompt policies, including the `warn`, `block`, `redact` and `allow` envelopes, without changing the saved exchange when paused or blocked. Ordinary successful mutations include `error:false,error_message:"NULL"`.

| Endpoint | Additional fields | Success fields |
|---|---|---|
| `POST /api/admin/employee/chats` | `{}` | `chats`: newest first, each with numeric `id`, `title`, `updated_at`, `created_at`, `exchanges`. |
| `POST /api/admin/employee/chats/open` | `{"chat_id":7}` | `chat:{id,title,messages}`. A message has string `id`, `prompt`, `answer`, `created_at`, `blocked`, `edited` and, when sanitized, `redacted:true` and safe `redaction_info`. |
| `POST /api/admin/employee/chats/rename` | `{"chat_id":7,"title":"Code review"}` | `chat_id:7,title:"Code review"`. Whitespace is normalized; an empty title is `400`. |
| `POST /api/admin/employee/chats/delete` | `{"chat_id":7}` | `deleted:7`. Removing history does not remove statistics. |
| `POST /api/admin/employee/chats/search` | `{"query":"total"}` | `results:[{chat_id,chat_title,message_id,prompt,answer,created_at,excerpt},…]`. Only the caller's chats; empty query → `[]`. |
| `POST /api/admin/employee/chats/message/edit` | `{"chat_id":7,"message_id":"<id>","text":"Review the sum."}` | `messages`: updated list (edited message has `edited:true,edited_at`). |
| `POST /api/admin/employee/chats/message/delete` | `{"chat_id":7,"message_id":"<id>"}` | `messages`: remaining messages. Missing messages return `404`. |
| `POST /api/admin/employee/chat/regenerate` | `{"chat_id":7,"message_id":"<id>"}` with optional `prompt`, `confirm_warn`, `bypass`, `admin_token` | Same send envelope; on success includes updated `messages` (history-safe, even when `reply_message` is locally restored). If `prompt` is provided it is screened as a draft and saved only after a successful answer; otherwise the stored prompt is re-screened. |

## `POST /api/admin/team`

`{"token":"<admin or page grant>"}` (or an authorized browser cookie). Returns `admin`, `members`, `stats:{members,sent,blocked,overrides,block_rate}`, `stages`, `reasons`, `trend`, `timeline`, `days` and ordinary success fields. No raw chat history. By default the timeline contains metadata only. Optional previews of ordinary sends, regenerations and edits are controlled by `CYBERSYN_LOG_PROMPT_PREVIEW`; **blocked, warned, redacted and overridden sends never log their text**.

## Shadow AI discovery and policy

### `POST /api/admin/shadow-ai`

Read-only, using the administrator session or `approval_page` (`token`/`admin_token` for API clients). An optional `Parent_id` must match the credential. Example filter:

```json
{"Parent_id":"1","days":7,"status":"unapproved","team":"Sales","data_signal":"client_data"}
```

`days` is `7` (default), `30`, or `0` for all. Omit `status`, `team` or `data_signal` (or send `""`) for all values. Returns:

- `inventory`: every catalog and workspace-defined tool, with `tool_key`, `name`, `vendor`, `category`, `domains`, `provider_key`, `risk_score`, `risk_level`, `hosting`, `training_policy`, `gdpr_summary`, `default_status`, `status`, `custom`, `note`, `updated_at`, `updated_by`. Unverified custom training terms are `null`. Scores are baseline assessments, not GDPR certifications.
- `summary`: `total_events`, `tools_discovered`, `unapproved_tools_active`, `unapproved_events`, `client_data_to_unapproved`, `sensitive_data_to_unapproved`. Sensitive counts include client data, source code, contracts, HR, financial and credential tags, not inferred `large_upload` alone.
- `by_team`: matching team rows, ranked by client data and then other risk counts. Each has `team`, `total_events`, `unapproved_events`, `client_data_to_unapproved`, `sensitive_data_to_unapproved` and distinct `unapproved_tools` names. `teams` lists available team filters.
- `events`: up to 200 matching rows, latest first, including only `id`, `observed_at`/`imported_at` (UTC ISO-8601), `team`, `actor`, `host`, `tool_key`, `tool_name`, `method`, `bytes_sent`, `data_signal` and live `status`, `risk_score`, `risk_level`. Summary counts are not capped by the events display limit.

### `POST /api/admin/shadow-ai/policy`

Requires `Parent_id` and either the primary administrator cookie/session or an atomic, single-use approval (`admin_token` or `token`). Member sessions and page grants are rejected. Example bodies (include `Parent_id` in each):

```json
{"Parent_id":"1","tool_key":"openai","status":"restricted","note":"Use the reviewed API connection only."}
```

```json
{"Parent_id":"1","method":"add","domain":"assistant.example:8443","name":"Synthetic assistant","status":"unapproved"}
```

```json
{"Parent_id":"1","method":"remove","tool_key":"custom:assistant.example:8443"}
```

`method` defaults to `update`. Status is `approved`, `restricted`, or `unapproved`; new custom tools default to `unapproved`. Notes are optional, one line, up to 240 characters; omitting the note on update clears it. A custom domain must be a hostname or IP literal with an optional port, not a URL or wildcard. Matching uses hostname label boundaries, not substring search. HTTP(S) URLs use their effective port when a policy entry is port-specific. Overlapping catalog or custom entries return `409`. Success returns `inventory` and the updated `tool` (or `null` on removal). Older events for a removed custom domain remain visible as unapproved. A custom API base that is not classified in the inventory is not blocked by this policy.

### `POST /api/admin/shadow-ai/import`

Same write credentials as policy changes. Send exactly one operation:

```json
{"Parent_id":"1","content":"time,department,src_ip,destination,method,request_bytes,classification\n2026-11-18T14:00:00Z,Sales,192.0.2.14,assistant.example:8443,POST,6800,client_data"}
```

- `{"Parent_id":"1","sample":true}` appends a synthetic 25-row sample anchored to the last seven days; `{"Parent_id":"1","clear":true}` clears discovery rows in that workspace only, not policies.
- CSV alias groups: `timestamp/time/date`, `team/department/group`, `user/actor/src_ip/client_ip`, `url/domain/host/destination` (required), `method`, `bytes_sent/bytes/request_bytes`, `data_category/data_signal/classification`. Other columns are discarded. Data signals: `client_data`, `source_code`, `contracts`, `hr_data`, `financial`, `credentials`, `large_upload`, `general`.
- Plain text supports `[timestamp] actor METHOD host [request-bytes]`, native Squid, absolute-URL combined proxy logs, and DNS dnsmasq/BIND or `[timestamp] actor query host` lines. Use UTC/ISO-8601 for synthetic timestamps (optional; missing timestamps use import time). Squid and combined proxy positional reply sizes are not upload evidence; use a `request_bytes=N` or `bytes_sent=N` extension. Absent a recognized tag, an upload method and at least 4,096 request bytes infer `large_upload`; otherwise `general`.
- Bounds: 2,000 physical lines and 192 KiB of UTF-8 text per import. Malformed or binary content returns `400` without partially persisting an import. Only allowlisted metadata is stored; scheme, credentials, paths, queries, fragments and prompt columns are dropped. The parser never resolves or contacts destinations.
- Returns `lines_scanned` (nonblank data records, excluding the CSV header), `ai_events_added`, `non_ai_ignored`, `events_cleared`, and a refreshed unfiltered seven-day `summary`. Imports append; repeated imports are not deduplicated.

## Known gaps

- Only prompts submitted through this gateway are screened. No interception of other AI sites, multi-turn provider memory or OpenAI-compatible proxy is implied.
- Screeners are heuristics plus local models, not proof of confidentiality or of source-code ownership. Code policy blocks recognized source, not a particular licence. Missing models fail closed.
- A saved key is currently required even for the Ollama chat/discovery routes. Discovery pins validated socket addresses; completion uses an administrator-approved base and LiteLLM's transport. Restrict network egress on shared or cloud gateways.
- SQLite chat content is not encrypted. Protect the data volume and backups. Audit events/statistics survive offboarding; deleting rows is not secure erasure from backups. Explicit preview opt-in exposes ordinary prompt/edit prefixes on the admin timeline.
- Shadow AI reports supplied logs and current workspace policy, not live interception or proof of what was disclosed. Restricted tools can be used through the screened gateway; direct-access findings rely on the source of the uploaded logs.
