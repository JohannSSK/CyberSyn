# CyberSyn JSON API

All endpoints below are **POST**, with `Content-Type: application/json`. The route registry is [`includes/constants.json`](includes/constants.json). Tokens and identifiers in these examples are placeholders; substitute values actually returned by your gateway.

## Authentication conventions

- **Browser:** `Api.post()` sends same-origin credentials, `X-CyberSyn-Request: 1` and `X-CyberSyn-Session: cookie`. Login/create sets an HttpOnly, SameSite=Lax, Path=/ cookie (`cybersyn_admin` or `cybersyn_member`, seven days). Cookie-authenticated requests require the custom request header; a supplied `Origin` must match the gateway. Use HTTPS; `Secure` is set on HTTPS or with `CYBERSYN_COOKIE_SECURE=1`. Browser-mode session responses omit the bearer value. The browser stores only non-secret identity/display metadata.
- **API clients:** you may ignore cookies and pass the returned `session_token` explicitly. Admin actions generally call this field `token`; settings/overrides call the approval `admin_token`. An explicit invalid token does not become a valid session simply because a cookie exists.
- **Member body:** in the history/action tables below, merge the listed fields into `{"Parent_id":"1","Employee_id":"2","session_token":"<member>"}`. Omit `session_token` when using the member cookie. An administrator cannot read a member's chat history with an administrator credential.
- Login, account creation and settings return **strings** for `Parent_id`/`Employee_id`. Chat IDs and roster `id`s are numbers. Positive digit strings are accepted as IDs; booleans are not. Zero is reserved for the workspace-default settings row.
- Ordinary success responses commonly include `"error":false,"error_message":"NULL"` (the literal string). Login and model discovery have their own shapes. Examples below show response fields rather than every field where indicated. Validation failures are `400`, expired/invalid credentials `401`, denied destinations/CSRF/signup `403`, missing chats `404`, and duplicate usernames `409`. Repeated failed credential operations return `429` and `Retry-After`. Bodies over the configured limit return `413`.

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

**Remove:** `{"method":"remove","username":"owner","password":"<exact password>"}` → `{"error":false,"Parent_id":"1","error_message":"NULL"}`. Unknown users and wrong passwords receive the same `401`. Account rows, all workspace sessions, chats and settings are deleted together. Statistics and audit events are retained.

### Approval and administrator lifecycle

| Endpoint | Request example | Result |
|---|---|---|
| `POST /api/admin/approve` | `{"Parent_id":"1","username":"owner","password":"<password>","scope":"once"}` | Login success shape with `admin_token` instead of `session_token`; no session cookie for `once`. Omitting `scope` means `once`. If supplied, `Parent_id` must match. |
| `POST /api/admin/password` | `{"token":"<admin or once>","current_password":"<current>","new_password":"Another pass 123"}` | `200` ordinary success. Revokes **all** admin sessions and approvals; sign in again. |
| `POST /api/admin/session` | `{"token":"<admin>"}` or `{}` with admin cookie | `{"success":true,"Parent_id":"1","username":"owner"}` or `401 {"success":false}`. |
| `POST /api/admin/logout` | `{"token":"<token to revoke>"}`; browser `{}` | `{"success":true}`. Browser `{ "scope":"page" }` locks the page grant without ending a primary admin session. |
| `POST /api/admin/team/list` | `{"token":"<admin or page>"}` | `members`, e.g. `[{"id":2,"username":"maria","created_at":"2026-11-18 12:00:00"}]`; used by the removal picker. |
| `POST /api/admin/employee/override/check` | `{"Parent_id":"1","admin_token":"<admin or page>"}` | `{"error":false,"allowed":true,"error_message":"NULL"}` for a live workspace page/session grant. Does not consume or unlock a write grant. |

A **once** grant expires after five minutes and is atomically consumed on use; reuse cannot authorise a second write. A **page** grant (`scope:"page"`) lasts at most 15 minutes and grants read-only roster/statistics access, not policy changes or overrides. Browser mode sets a separate HttpOnly `cybersyn_page` cookie; API clients receive `admin_token`. “Lock now” revokes the grant on the server. Approval tokens cannot evict a primary login session.

For team statistics, the member roster and the page-access check, the explicit token takes precedence, then `cybersyn_admin`, then `cybersyn_page`. An invalid credential does not fall back to a different identity. Successful administrator login, creation or deletion revokes the page grant presented by that browser and clears its page cookie.

## 3. `POST /api/admin/employee`

**Add** (workspace administrator):

```json
{"method":"add","Parent_id":"1","token":"<admin>","username":"maria","password":"Example staff 123"}
```

`201 {"error":false,"Employee_id":"2","error_message":"NULL"}`. A member inherits a **copy** of workspace defaults, including the encrypted connection key. A duplicate username in the same workspace returns `409`.

**Offboard** (UI: `/delete-member`):

```json
{"method":"remove","Parent_id":"1","token":"<admin or once>","username":"maria","admin_password":"<administrator password>"}
```

Both a workspace admin credential **and** the administrator's current password are required. The member's password is neither requested nor accepted as confirmation. `200` ordinary success; their sessions, settings and chats are deleted in one transaction, not their audit/statistics records.

## 4. `POST /api/admin/employee/login`

`{"Parent_id":"1","username":"maria","password":"<exact member password>"}`. A fresh member receives:

```json
{"error":false,"Employee_id":"2","username":"maria","session_token":"<member>","chats":[],"chat_id":null,"CHAT_LOGS":[],"settings":{"Parent_id":"1","Employee_id":"2","check1":true,"check2":true,"check3":true,"block_code":false,"API_KEY":"","API_KEY_MASK":"","MODEL_NAME":"gpt-4o-mini","PROVIDER":"auto","API_BASE":""},"error_message":"NULL"}
```

Returning members get their chat list and latest chat/messages. On success, the browser's primary admin cookie and page grant are **revoked and cleared**, not passed into the member workspace. Unknown member/wrong password: `401` with `error`, `Employee_id:"NULL"`, `CHAT_LOGS:[]`, and `error_message:"Invalid employee username or password."`.

| Endpoint | Additional fields | Result |
|---|---|---|
| `POST /api/admin/employee/account` | `{"action":"username","current_password":"<current>","new_username":"maria2"}` | Success with `username`. Existing names in the workspace return `409`. |
| `POST /api/admin/employee/account` | `{"action":"password","current_password":"<current>","new_password":"New staff pass 321"}` | Revokes every prior member session. Returns a new `session_token` (refreshed HttpOnly cookie for browsers). |
| `POST /api/admin/employee/logout` | `{"session_token":"<member>"}` or `{}` with cookie | Revokes this session and clears the cookie; ordinary success. |

## 5. `POST /api/admin/employee/settings`

**Read**: just the member body. **Write**: include an administrator approval and only the fields to change. An admin may target any member of their own workspace. A member without approval cannot change policy or read/write `Employee_id:0`.

```json
{"Parent_id":"1","Employee_id":"2","session_token":"<member>","admin_token":"<once>","block_code":true}
```

Response, assuming a previously saved connection:

```json
{"Parent_id":"1","Employee_id":"2","check1":true,"check2":true,"check3":true,"block_code":true,"API_KEY":"","API_KEY_MASK":"****7890","MODEL_NAME":"gpt-4o-mini","PROVIDER":"openai","API_BASE":""}
```

- `check1`, `check2`, `check3` and `block_code` are booleans. **Block proprietary source code** is independent and off by default. Turning it off allows ordinary code review; it does not disable other checks on that code.
- `Employee_id:0` reads/updates the template for **future** members. `also_default:true` also saves the submitted checks to that template. When saving connection settings, it copies the resulting connection as a unit (provider, base, model and encrypted key), so the new destination never inherits a different default key. No other existing member changes.
- `API_KEY:""` means **keep** the saved secret; `CLEAR_API_KEY:true` means **delete** it. `API_BASE:""` clears the custom base. Nonempty bases can contain paths, not credentials, query strings or fragments. The API never returns the encrypted blob or the plaintext key; keys shorter than eight characters are masked completely.

### Discovery

| Endpoint | Request | Result |
|---|---|---|
| `POST /api/admin/employee/providers` | Member session (or primary administrator session) | `{"providers":[…],"message":null}`. Entries carry `key`, `label` and, for named providers, hints and key/base requirements. |
| `POST /api/admin/employee/models` | Member session plus optional `{"provider":"groq","API_KEY":"<pasted key>"}` or `API_BASE` | `{"models":["groq/example"],"provider":"groq","provider_label":"Groq","message":null}` (model names vary). |

With no pasted key, discovery uses the saved provider/base/key. A changed destination requires workspace admin approval; a new HTTP base must first be saved. Auto only probes the service matching a recognized prefix. For ambiguous keys, **choose the provider before entering the key**. Unknown formats return `400` without probing unrelated providers. A provider refusal returns `502` with `models:[]`, `message`, and `tried`. Redirects across origins lose all provider authentication headers.

## 6. `POST /api/admin/employee/chat`

**6A — ordinary prompt:** send the member body plus `{"prompt":"What is the capital of Greece?"}`. The server uses the **saved** checks, model, key and base. Per-request `check1`, `check2`, `check3`, `block_code` and `MODEL_NAME` do not override them. A new chat is created only after a successful answer:

```json
{"error":false,"blocked":false,"reply_message":"Athens.","error_message":"NULL","block_info":"NULL","chat_id":7,"message_id":"c88a9b82a35e28a0"}
```

**6B — code review in an existing chat:** with this member’s code blocking off, code alone is not a reason for refusal:

```json
{"Parent_id":"1","Employee_id":"2","session_token":"<member>","chat_id":7,"prompt":"Review this function:\n\ndef total(items):\n    return sum(items)"}
```

With this member's code blocking on, the context scanner can return `computer source code`. In either case, enabled secret/PII and injection checks still inspect the prompt.

**6C–E — blocked:** e.g. a synthetic Greek ID (`ΑΒ 123456`), a confidential payroll export or an instruction override. A policy block is **HTTP 200** with `error:false`, `blocked:true`, `reply_message:"NULL"`, an explanation and `block_info`. Example `block_info`:

```json
{"blocked":true,"stage":"check1","main_cause":"GREEK_ID","line":1,"start_offset":0,"end_offset":9,"snippet":"ΑΒ 123456","matches":[{"cause":"GREEK_ID","score":0.95,"line":1,"start_offset":0,"end_offset":9,"snippet":"ΑΒ 123456"}]}
```

Evidence is returned to the sender for editing, not stored as blocked chat content or in the activity/block logs. A failed or timed-out scanner returns `503` without contacting the model.

**6F — approved exception:** send the member body plus `{"prompt":"<reviewed text>","bypass":true,"admin_token":"<fresh once grant>"}`. A live workspace admin session is also accepted. A missing/replayed approval returns `401`. A successful override sends the original text and saves the answered exchange to the member's history. The audit event records the approver, not a prompt preview.

**6G–H — other errors:** a missing saved key returns `400`; a provider error returns `502` without the library exception or key; a `chat_id` not belonging to this member (including a chat deleted during the provider call) returns `404`.

## Chat history and regeneration

Each request below needs the **member body**. Edits modify local history; regeneration screens the stored, possibly edited prompt again. Regeneration returns the same block envelope as a fresh send when blocked. Ordinary successful mutations include `error:false,error_message:"NULL"`.

| Endpoint | Additional fields | Success fields |
|---|---|---|
| `POST /api/admin/employee/chats` | `{}` | `chats`: newest first, each with numeric `id`, `title`, `updated_at`, `created_at`, `exchanges`. |
| `POST /api/admin/employee/chats/open` | `{"chat_id":7}` | `chat:{id,title,messages}`. A message has string `id`, `prompt`, `answer`, `created_at`, `blocked`, `edited`. |
| `POST /api/admin/employee/chats/rename` | `{"chat_id":7,"title":"Code review"}` | `chat_id:7,title:"Code review"`. Whitespace is normalized; an empty title is `400`. |
| `POST /api/admin/employee/chats/delete` | `{"chat_id":7}` | `deleted:7`. Removing history does not remove statistics. |
| `POST /api/admin/employee/chats/search` | `{"query":"total"}` | `results:[{chat_id,chat_title,message_id,prompt,answer,created_at,excerpt},…]`. Only the caller's chats; empty query → `[]`. |
| `POST /api/admin/employee/chats/message/edit` | `{"chat_id":7,"message_id":"<id>","text":"Review the sum."}` | `messages`: updated list (edited message has `edited:true,edited_at`). |
| `POST /api/admin/employee/chats/message/delete` | `{"chat_id":7,"message_id":"<id>"}` | `messages`: remaining messages. Missing messages return `404`. |
| `POST /api/admin/employee/chat/regenerate` | `{"chat_id":7,"message_id":"<id>"}` | Chat envelope with `reply_message` and updated `messages` on success. |

## `POST /api/admin/team`

`{"token":"<admin or page grant>"}` (or an authorized browser cookie). Returns `admin`, `members`, `stats:{members,sent,blocked,overrides,block_rate}`, `stages`, `reasons`, `trend`, `timeline`, `days` and ordinary success fields. No raw chat history. By default the timeline contains metadata only. Optional previews of ordinary sends, regenerations and edits are controlled by `CYBERSYN_LOG_PROMPT_PREVIEW`; **blocked and overridden sends never log their text**.

## Known gaps

- Only prompts submitted through this gateway are screened. No interception of other AI sites, multi-turn provider memory or OpenAI-compatible proxy is implied.
- Screeners are heuristics plus local models, not proof of confidentiality or of source-code ownership. Code policy blocks recognized source, not a particular licence. Missing models fail closed.
- A saved key is currently required even for the Ollama chat/discovery routes. Discovery pins validated socket addresses; completion uses an administrator-approved base and LiteLLM's transport. Restrict network egress on shared or cloud gateways.
- SQLite chat content is not encrypted. Protect the data volume and backups. Audit events/statistics survive offboarding; deleting rows is not secure erasure from backups. Explicit preview opt-in exposes ordinary prompt/edit prefixes on the admin timeline.
- The existing portal-to-statistics redirect and team-page guard are unchanged. Dashboard range controls and timeline aggregation have existing limitations; use the documented server responses rather than assuming the UI is a deduplicated audit export.
