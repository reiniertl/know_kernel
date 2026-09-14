# Implementation Plan: Authentication Gate, Sessions, and Implicit Reviewer Identity

**Created:** 2026-08-19
**Status:** Ready for implementation
**Source audit:** silk run `audit-auth-session-01` (cb-audit, FINAL_STATUS SUCCESS, 6 stages, 0 violations)
**Scope:** New `MOD-KK-AUTH` spec module, new `src/authgate/` package, separate `auth.db`,
session + remember-me, admin user management, implicit reviewer attribution, entry-point switch
**Prerequisite:** None
**Blocking decisions:** two, listed in §14 (both have defaults; neither blocks Task Group A)

---

## 0. How to use this document

This plan is written to be executed in a **future session with no memory of the
conversation that produced it**. Every fact it depends on was verified by reading
the repository on 2026-08-18/19; verification commands are given in §12 so a future
session can re-confirm before editing.

Task groups A–G in §7 map one-to-one onto future `/cb-*` invocations. §15 gives the
suggested invocation sequence. Do not collapse groups: each ends at a green test
suite and a working application.

---

## 1. Requirement, as stated by the operator

Collected across the design conversation of 2026-08-18. Quoted intent, not paraphrase:

1. "Implement user authentication for the whole system and then have a session open."
2. "Session does not need to expire... once logged in you stay logged in." Later refined:
   "Lets make the session expire after 24h, but also allow the browser to store credentials
   and autologin. Same I see in most browsers where using a link or refreshing the page seems
   like nothing changed but I am sure the session had expired."
3. "The logging mechanism does not need to be extremely secure... it just needs to allow only
   the people meant to use it. No secret or personal data is being maintained."
4. "Can you make an app entry point and then redirect with authorization token or something for
   the current app? That may simplify the gating behind a wall issue."
5. "The know_kernel app must track the session from the logging page. I see this similar to how
   banks operate their login: you login and data is passed to the dashboard app which tracks the
   session properties."
6. "I do not think you should mix this capability with the knowledge database."
7. "The user in the login must be available in the app for things such as reviews so one does not
   need to pick its name from any dropdown list when writing reviews or performing other
   activities that we will add later on."
8. "You can remove the roster and use the name of the user, it is that simple, or every user gets
   automatically registered in the roster." → resolved to auto-registration (see §3, D-6).
9. "Of course we need an admin user type so we can add users, that is not self registration on
   this site."
10. "It would have less than 50 users at any given time."
11. "I also want the drop down list to go away. Once a user is logged in we should expect the
    user to be implicitly the reviewer."

---

## 2. Verified baseline (state of the repo before this plan)

All line numbers verified 2026-08-18. Re-verify with §12 before editing.

### Application shape

| Fact | Evidence |
|---|---|
| FastAPI app built by factory `create_app(db_path)` | `src/web/app.py:18` |
| Module-level `app = create_app(os.environ.get("KNOW_KERNEL_DB", ":memory:"))` at import time | `src/web/app.py:50` |
| SQLite connection opened in lifespan, exposed as `app.state.conn` | `src/web/app.py:27-35` |
| `SCHEMA_SQL` executed on every startup (`CREATE TABLE IF NOT EXISTS`) → auto-migration | `src/web/app.py:32` |
| Routes registered by `setup_routes(app, templates)` | `src/web/routes.py:138` |
| 26 routes total: 21 GET, 2 POST, 2 PUT, 1 DELETE | `src/web/routes.py` |
| `WEB_MUTATION_ALLOWLIST` tuple is the structural enforcement of `INV-KK-WEB-MUTATION-ALLOWLISTED` | `src/web/routes.py:27-36` |
| Templates: 13 files, `base.html` holds the nav | `src/web/templates/` |
| Nav has 8 links + htmx search box, no user indicator, no logout | `src/web/templates/base.html:43-60` |
| htmx 1.9.12 loaded from unpkg; nav search fires `hx-get /api/search` on keyup | `src/web/templates/base.html:50-56, 63` |
| MCP server runs over stdio via `mcp.run()` — not HTTP-reachable | `src/mcp_server/server.py:609` |
| ingest / export are argparse CLIs — not HTTP-reachable | `src/ingest/cli*.py`, `src/export/cli.py` |

### Storage

| Fact | Evidence |
|---|---|
| `SCHEMA_SQL` declares exactly two tables: `nodes`, `edges` | `src/graph/schema.py:152-172` |
| `NODE_KINDS` has 27 kinds with a SQL `CHECK` constraint | `src/graph/schema.py:8` |
| `EDGE_KINDS` has 37 kinds | `src/graph/schema.py:10-48` |
| Adding a node kind requires `NODE_KINDS` + `ID_PREFIXES` + `REQUIRED_ATTRS` + `RULES_BY_KIND` | `src/graph/schema.py`, `src/graph/rules.py:261` |
| Dashboard counts **every** `nodes.kind` with no filter | `src/web/routes.py:139-152` |
| `/api/search` does unfiltered `attrs LIKE` across all nodes | `src/web/routes.py:318-350` |
| Exporter copies only `nodes` + `edges` **rows**, filtered by `ALLOWED_KINDS` | `src/export/exporter.py:38-59` |
| `validate_snapshot` compares master vs snapshot **table sets** and raises on any difference | `src/export/exporter.py:99-104` |

### Review subsystem

| Fact | Evidence |
|---|---|
| `review_paper(conn, source_id, reviewer, score, verdict, rationale)` — reviewer is a **name string** | `src/ingest/paper_scorer.py:29-36` |
| `review_paper` rejects unregistered reviewers (`INV-KK-REVIEW-REVIEWER-REGISTERED`) | `src/ingest/paper_scorer.py:60-64` |
| One review per (source, reviewer) (`INV-KK-REVIEW-SINGLE-PER-REVIEWER`) | `src/ingest/paper_scorer.py:76-89` |
| Roster API: `find_reviewer`, `register_reviewer`, `list_reviewers` → `ReviewerResult(reviewer_id, name)` | `src/ingest/reviewer_registry.py:24,39,71` |
| Roster names are unique case-insensitively (`INV-KK-REVIEWER-NAME-UNIQUE`) | `src/ingest/reviewer_registry.py:24-37` |
| `Reviewer` node ids use prefix `rvr-` | `src/graph/schema.py:149` |
| `submit_review` trusts `body["reviewer"]` | `src/web/routes.py:1071-1099` |
| `update_review` (PUT) does **not** accept a reviewer — `INV-KK-REVIEW-EDIT-IMMUTABLE-REVIEWER` | `src/web/routes.py:1101-1126` |
| `remove_review` (DELETE) takes only `review_id` — no ownership check today | `src/web/routes.py:1128-1147` |
| The **only** reviewer picker in the whole UI | `src/web/templates/paper_detail.html:292-298` |
| Its "no reviewers registered" warning | `src/web/templates/paper_detail.html:299-303` |
| Its client-side guard | `src/web/templates/paper_detail.html:437` |
| Its request body field | `src/web/templates/paper_detail.html:439` |
| Roster list injected into the paper page context | `src/web/routes.py:826` |
| `list_reviewers` imported at `paper_detail` route top | `src/web/routes.py:670` |
| `<select>` elements in `reviews.html` are verdict/min-score **filters** — unrelated, keep | `src/web/templates/reviews.html:8,14` |
| `/reviewers` page + `POST /api/reviewers` roster admin | `src/web/routes.py:1029-1069` |

### Spec graph

Totals at audit time: 3587 nodes, 8396 edges. `npm run spec:check` → **0 errors**, 1051 warnings
(all pre-existing `AUTH-WARN-ORPHANED-ALGO` / `AUTH-WARN-DEAD-INTERFACE`).

know_kernel modules: `MOD-KK-WEB`, `MOD-KK-GRAPH`, `MOD-KK-INGEST`, `MOD-KK-REVIEW`.

`MOD-KK-WEB` contains 24 nodes — 15 algorithms, 9 invariants — **none about identity or access**:

```
ALG-KK-WEB-ABSTRACT-EDIT      ALG-KK-WEB-FEED-CARD          ALG-KK-WEB-FEED-LIST
ALG-KK-WEB-FEED-REVIEW-BADGE  ALG-KK-WEB-FEED-SEND          ALG-KK-WEB-PAPER-DETAIL
ALG-KK-WEB-PAPER-DETAIL-REVIEW ALG-KK-WEB-RADAR             ALG-KK-WEB-REVIEW-DELETE
ALG-KK-WEB-REVIEW-EDIT        ALG-KK-WEB-REVIEW-STATUS      ALG-KK-WEB-REVIEW-SUBMIT
ALG-KK-WEB-REVIEWER-CREATE    ALG-KK-WEB-REVIEWERS-PAGE     ALG-KK-WEB-REVIEWS-LIST
INV-KK-FEED-CARD-LINK-ABSOLUTE INV-KK-FEED-CONFIG-VENUE-TYPE
INV-KK-FEED-SEND-PLACEHOLDER-REQUIRED INV-KK-FEED-SEND-TIMEOUT
INV-KK-FEED-SUMMARY-MAX-WORDS INV-KK-WEB-MUTATION-ALLOWLISTED
INV-KK-WEB-PAPER-404-NON-SOURCE INV-KK-WEB-PAPER-CONCEPT-CHAIN INV-KK-WEB-QUERY-BOUNDED
```

Roster-related spec nodes (relevant to D-6, all **retained** by this plan):
`ALG-KK-REVIEWER-REGISTER`, `ALG-KK-REVIEWER-LIST`, `ALG-KK-WEB-REVIEWER-CREATE`,
`ALG-KK-WEB-REVIEWERS-PAGE`, `IFC-KK-REVIEWER`, `INV-KK-REVIEWER-NAME-UNIQUE`,
`INV-KK-REVIEW-REVIEWER-REGISTERED`, `INV-KK-REVIEW-SINGLE-PER-REVIEWER`,
`INV-KK-REVIEW-EDIT-IMMUTABLE-REVIEWER`, `MOD-KK-REVIEW`.

### Dependencies

| Package | State |
|---|---|
| `fastapi`, `uvicorn[standard]`, `jinja2`, `mcp`, `httpx` | declared in `pyproject.toml:9-15` |
| `starlette` 1.2.1 | transitive; `SessionMiddleware(app, secret_key, session_cookie='session', max_age=1209600, path='/', same_site='lax', https_only=False, domain=None)` |
| `itsdangerous` 2.2.0 | installed transitively, **undeclared** |
| `python-multipart` | installed transitively, **undeclared** |
| `passlib` | **not installed** — and not needed (stdlib `hashlib.pbkdf2_hmac`) |

### Tests

| Fact | Evidence |
|---|---|
| 167 tests build their client from `create_app` directly | `tests/test_web.py:17-45` |
| Router sweep asserting the mutation allowlist, also on `create_app` | `tests/test_source_abstract.py:209-221` |
| **No HTTP-level tests exist for any `/api/review*` endpoint** | verified: `grep -rn "api/review" tests/` → no matches |
| `review_paper` is covered at function level only | `tests/test_paper_scorer.py:50+` |
| **Pre-existing failures**: asserts `len(NODE_KINDS) == 24` and `len(EDGE_KINDS) == 35`, shipped values are 27 and 37 | `tests/test_graph_schema.py:19-28,32-46` |

### Entry points

```
start.bat / start.sh : python -m uvicorn web.app:app --host 127.0.0.1 --port 8000 --reload
                       exports KNOW_KERNEL_DB, PYTHONPATH=src
pyproject scripts    : kk-ingest, kk-feed, kk-web = "web.app:main", kk-export, kk-mcp
```

`--reload` matters: any per-process random signing key would be regenerated on every reload,
silently invalidating all sessions. See D-4.

---

## 3. Design decisions (with rationale — do not re-litigate)

**D-1 — Parent gate app, child mount.** A new ASGI app owns `/login`, `/logout`, `/admin/*` and
mounts the unmodified know_kernel app at `/`. Rationale: one structural choke point, mirroring the
existing `WEB_MUTATION_ALLOWLIST` pattern; it also covers FastAPI's auto-generated `/docs`,
`/redoc`, `/openapi.json`, which per-route dependencies would silently miss.

*Consequences:* (a) `INV-KK-WEB-MUTATION-ALLOWLISTED` never changes, because `/login` and `/logout`
are not in `MOD-KK-WEB`; (b) the 167 tests in `tests/test_web.py` keep passing untouched because
they target `create_app` directly; (c) `tests/test_source_abstract.py`'s router sweep must **stay**
on `create_app`, or it will pick up the gate's mutating routes and fail.

*Accepted risk:* running `uvicorn web.app:app` directly still serves everything anonymously. The
inner app cannot self-defend under this design. Mitigated by switching every documented entry point
and documenting it (Task G-4).

**D-2 — Mount at `/`, never a sub-path.** Templates use absolute links (`href="/feed"`,
`base.html:44-51`), and `paper_detail.html:445` fetches `/api/review/...`. A sub-path mount would
break every one. Verified working: explicit parent routes registered before `Mount("/")` win the
match, so `/login` resolves in the gate, not the child.

**D-3 — Identity crosses the mount via `request.state`.** Starlette propagates `request.state`
through a `Mount` via the ASGI `scope["state"]` dict. **Verified empirically against the installed
starlette 1.2.1** with this exact probe:

```python
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
inner = FastAPI()
@inner.get('/whoami')
async def whoami(request: Request):
    return {'user': getattr(request.state, 'user', None)}
parent = FastAPI()
@parent.middleware('http')
async def gate(request: Request, call_next):
    request.state.user = {'username': 'reinier', 'reviewer': 'Reinier'}
    return await call_next(request)
parent.mount('/', inner)
print(TestClient(parent).get('/whoami').json())
# → {'user': {'username': 'reinier', 'reviewer': 'Reinier'}}
```

This is the mechanism behind requirement 5. **No token in the URL** — tokens in URLs leak through
browser history, server logs, and `Referer` headers. Login sets a cookie and 302s to `?next=`.

**D-4 — Server-side sessions, not signed cookies.** A `sessions` table in `auth.db`; the cookie
carries an opaque random token only. Rationale: logout genuinely revokes; no signing secret is
needed at all, which removes the `--reload` key-churn failure mode entirely; `itsdangerous` and
`SessionMiddleware` are not used. Consequence: `itsdangerous` need not be declared after all
(contrast with the pre-decision audit finding, which assumed cookie sessions).

**D-5 — Separate `auth.db`.** Rationale: requirement 6, plus it sidesteps
`validate_snapshot`'s table-set comparison (`src/export/exporter.py:99-104`) — `master.db` never
gains a table, so `kk-export` is untouched. Also keeps credentials out of the graph, where the
dashboard's kind counts and the unfiltered `/api/search` would otherwise publish them.

**D-6 — Keep the roster; auto-register users into it.** Requirement 8 offered removal as an option;
**do not remove it.** Rationale: (a) `HumanReview` nodes carry a `reviewed-by` edge to `Reviewer`
nodes, so the roster is the graph-side record of authorship — deleting it would force `master.db`
to depend on `auth.db` to answer "who wrote this review", inverting the separation of D-5;
(b) removal touches 10 source/test files and ~9 spec nodes and is a refactor of shipped behaviour,
which needs its own explicit approval under CLAUDE.md rule #4. Auto-registration satisfies the
operator's actual goal (requirement 11, no dropdown) at a fraction of the cost.

**D-7 — Roster name == auth username.** Usernames are unique in `auth.db` by primary key, so
`INV-KK-REVIEWER-NAME-UNIQUE` (case-insensitive) can never be violated by user creation. A separate
display name is deliberately deferred — see §16.

**D-8 — Two cookies.** 24h sliding session + 30d rotating remember-me token. This is the mechanism
behind the operator's observation in requirement 2: when the session has expired but the remember
token is valid, the gate mints a new session inline and the request proceeds — the user sees
nothing. Rotation on use is cheap (one row update) and is what makes a 30d token acceptable.

**D-9 — Deactivate, never delete users.** A deleted user whose reviews still reference their roster
entry leaves dangling attribution. `users.active` costs one column and one `WHERE` clause.

**D-10 — Gate templates live in `src/authgate/templates/`.** Not in `src/web/templates/`. Rationale:
the separation in D-5 should hold for presentation too; the gate must render its login page without
depending on the knowledge app being importable or its DB being open. `login.html` is therefore
standalone and does **not** extend `base.html`. (This supersedes the on-screen report of
2026-08-18, which placed `login.html` under `src/web/templates/`.)

**D-11 — Skip hardening.** Per requirement 3: no rate limiting, no CSRF tokens, no password reset,
no email, no account lockout, no 2FA. `SameSite=Lax` on both cookies is the whole CSRF story.
`https_only` is a config flag defaulting to `False` (deployment is `127.0.0.1`).

**D-12 — Server-side reviewer authority.** `submit_review` stops reading `body["reviewer"]`
entirely. Not a security measure — a correctness one: otherwise attribution is decorative and any
hand-crafted request can impersonate. This is the enforcement half of requirement 11.

---

## 4. Target architecture

```
uvicorn authgate.app:app                     ← the ONLY documented entry point
  │
  │  lifespan: opens auth.db  (KNOW_KERNEL_AUTH_DB, default data/auth.db)
  │            executes AUTH_SCHEMA_SQL (CREATE TABLE IF NOT EXISTS)
  │
  ├── GET  /login          → login.html                    (exempt)
  ├── POST /login          → verify, mint session, 302 next (exempt)
  ├── POST /logout         → revoke, clear cookies, 302 /login
  ├── GET  /admin/users    → admin_users.html              (admin only)
  ├── POST /admin/users    → create user + roster entry    (admin only)
  ├── POST /admin/users/{username}/deactivate              (admin only)
  ├── POST /admin/users/{username}/password                (admin only)
  ├── GET  /healthz        → 200 "ok"                      (exempt, gate liveness)
  │
  ├── gate middleware  (runs for every request, including the mount)
  │      1. path in AUTH_EXEMPT_PATHS            → pass through, no identity
  │      2. valid session cookie                 → slide expiry, inject identity
  │      3. expired/absent session + valid remember token
  │                                              → mint session, rotate token, inject
  │      4. otherwise → HX-Request ? 401 + HX-Redirect : 302 /login?next=<path>
  │
  └── Mount("/", create_app(KNOW_KERNEL_DB))    ← existing app, routes unchanged
         reads request.state.user
```

`request.state.user` shape (single source of truth for downstream code):

```python
{"username": "reinier", "role": "admin", "reviewer": "reinier"}
```

`reviewer` is currently always equal to `username` (D-7) but is kept as a distinct key so a display
name can be introduced later without touching call sites.

---

## 5. New spec nodes (`MOD-KK-AUTH`)

Author these **before any code** (CLAUDE.md rule #3). Use
`npm run ril -- template <kind> --json` for the live attribute/edge constraints, and
`npm run ril -- query add-options <kind>` for valid module targets. `npm run spec:check` must
remain at **0 errors** after the batch.

### Module

| Id | Kind | Description |
|---|---|---|
| `MOD-KK-AUTH` | module | Authentication gate: login, session lifecycle, user administration, and identity injection into the mounted know_kernel app. Owns `auth.db`; never touches the knowledge graph. `language: py` |

### Interfaces

| Id | Fields |
|---|---|
| `IFC-KK-USER` | `username` TEXT PK, `password_hash` TEXT, `salt` TEXT, `iterations` INTEGER, `role` TEXT ∈ {admin,user}, `active` INTEGER, `created_at` TEXT ISO-8601 |
| `IFC-KK-SESSION` | `token` TEXT PK (opaque, 32 bytes urlsafe), `username` TEXT, `created_at` TEXT, `expires_at` TEXT |
| `IFC-KK-REMEMBER-TOKEN` | `token_hash` TEXT PK (sha256 of the cookie value), `username` TEXT, `created_at` TEXT, `expires_at` TEXT |
| `IFC-KK-IDENTITY` | `username` TEXT, `role` TEXT, `reviewer` TEXT — the shape injected into `request.state.user` |

### Algorithms

| Id | Contract |
|---|---|
| `ALG-KK-AUTH-USER-CREATE` | **Pre:** caller is admin (HTTP) or CLI; username non-empty, not already present. **Post:** row in `auth.db.users` with a pbkdf2 hash; `Reviewer` node present in `master.db` named by the username; both or neither (see `INV-KK-AUTH-ROSTER-MIRRORS-USERS`). |
| `ALG-KK-AUTH-VERIFY-CREDENTIAL` | **Pre:** username, candidate password. **Post:** true iff the user exists, is `active`, and `hmac.compare_digest` matches. Never distinguishes "no such user" from "wrong password" to the caller. |
| `ALG-KK-AUTH-LOGIN` | **Pre:** POST body carries username + password. **Post:** on success a `sessions` row exists, `kk_session` cookie is set, optional `kk_remember` cookie + `remember_tokens` row when "remember me" was ticked, response is 302 to a **validated local** `next` (see `INV-KK-AUTH-NEXT-IS-LOCAL`); on failure re-renders `login.html` with one generic message and HTTP 401. |
| `ALG-KK-AUTH-LOGOUT` | **Post:** the session row is deleted, the remember-token row (if any) is deleted, both cookies are cleared, response is 302 to `/login`. |
| `ALG-KK-AUTH-SESSION-RESUME` | **Pre:** session absent/expired, `kk_remember` cookie present. **Post:** if the token hash matches a non-expired row for an active user → old remember row deleted, new one written, new cookie set, new session minted, request proceeds. Otherwise treated as anonymous. |
| `ALG-KK-AUTH-GATE` | The middleware of §4. **Post:** every request either carries `request.state.user` or is on `AUTH_EXEMPT_PATHS` or is answered with 302/401 before reaching the mount. |
| `ALG-KK-AUTH-SESSION-SLIDE` | **Post:** a resolved session's `expires_at` is pushed to `now + SESSION_TTL` on each request (at most one UPDATE per request). |
| `ALG-KK-AUTH-ADMIN-USER-LIST` | GET `/admin/users` → all users with role, active flag, created_at. Admin only. |
| `ALG-KK-AUTH-ADMIN-USER-CREATE` | POST `/admin/users` → delegates to `ALG-KK-AUTH-USER-CREATE`. Admin only. |
| `ALG-KK-AUTH-ADMIN-USER-DEACTIVATE` | POST `/admin/users/{username}/deactivate` → sets `active=0`, deletes that user's sessions and remember tokens. Admin only. Refuses to deactivate the last active admin. |
| `ALG-KK-AUTH-ADMIN-PASSWORD-SET` | POST `/admin/users/{username}/password` → re-hash. Admin only. Also the self-service path when the caller is the same user. |
| `ALG-KK-AUTH-CLI-USERADD` | `kk-useradd [--admin] <username>` — prompts for the password twice via `getpass`, never accepts it as an argv argument (`INV-KK-AUTH-NO-PLAINTEXT-PASSWORD`). |

### Invariants

| Id | Predicate | Enforcement |
|---|---|---|
| `INV-KK-AUTH-GATE-COVERS-MOUNT` | `forall request. request.path not in AUTH_EXEMPT_PATHS implies request reaching the mounted app carries a resolved identity` | Structural: the mount sits behind the gate middleware; `AUTH_EXEMPT_PATHS` is the single tuple, mirroring `WEB_MUTATION_ALLOWLIST`. |
| `INV-KK-AUTH-NO-PLAINTEXT-PASSWORD` | `forall password p. p is never written to disk, log, or DB in cleartext` | pbkdf2 at every write site; `getpass` in the CLI; no password in any log statement. |
| `INV-KK-AUTH-STORE-SEPARATE` | `no auth table in master.db and no graph table in auth.db` | Two distinct schema constants and two connections; test asserts the table sets are disjoint. |
| `INV-KK-AUTH-NO-SELF-REGISTRATION` | `forall user-creating path. caller is admin or caller is the CLI` | No unauthenticated POST creates a user; `/admin/*` is role-gated. |
| `INV-KK-AUTH-ROSTER-MIRRORS-USERS` | `forall u in users where u.active. exists Reviewer node named u.username` | `ALG-KK-AUTH-USER-CREATE` writes both; a test sweeps both stores. |
| `INV-KK-AUTH-SESSION-TTL` | `forall s in sessions. s.expires_at <= s.created_at + SESSION_TTL` and expired sessions never resolve | Checked on every read; expired rows are deleted lazily. |
| `INV-KK-AUTH-REMEMBER-ROTATES` | `forall remember token t consumed. t is deleted and replaced in the same transaction` | Single transaction in `ALG-KK-AUTH-SESSION-RESUME`; a replay test asserts the old token 302s. |
| `INV-KK-AUTH-NEXT-IS-LOCAL` | `forall next parameter n. n starts with "/" and does not start with "//"` | Rejects open redirects; falls back to `/`. |
| `INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION` | `forall review submission. reviewer == request.state.user.reviewer` | `submit_review` never reads `body["reviewer"]`. |

### Amended existing nodes

| Node | Change |
|---|---|
| `ALG-KK-WEB-REVIEW-SUBMIT` | Precondition changes from "body carries a registered reviewer name" to "request carries a resolved identity; the reviewer is derived from it". Postcondition adds "the request body's `reviewer` field, if present, is ignored." |
| `ALG-KK-WEB-PAPER-DETAIL` | Postcondition drops "the reviewer roster is supplied to the template". |
| `ALG-KK-WEB-REVIEWERS-PAGE` | Description gains "read-only projection of the user list; new entries arrive via `ALG-KK-AUTH-USER-CREATE`". |

**Scope note to embed in `INV-KK-AUTH-GATE-COVERS-MOUNT`'s description:** the gate covers HTTP
only. The MCP server is stdio, ingest/export are local CLIs, and `master.db` remains readable to
anyone with filesystem access. This is not system-wide access control.

---

## 6. Auth database schema

`src/authgate/schema.py`, constant `AUTH_SCHEMA_SQL`, executed with `executescript` on gate startup:

```sql
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    iterations    INTEGER NOT NULL DEFAULT 240000,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remember_tokens (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);
CREATE INDEX IF NOT EXISTS idx_remember_username ON remember_tokens(username);
```

Notes:
- Usernames are stored lowercase-trimmed; the login form lowercases before lookup.
- `PRAGMA foreign_keys=ON` and `PRAGMA journal_mode=WAL`, matching `init_db` in `graph/schema.py`.
- Timestamps are ISO-8601 UTC strings (`datetime.now(timezone.utc).isoformat()`), consistent with
  the rest of the codebase's text dates.
- The session cookie holds the raw token; the remember cookie's value is hashed (sha256) before
  storage so a leaked DB file cannot be replayed directly.

Constants (module level, single definition site):

```python
SESSION_TTL   = timedelta(hours=24)
REMEMBER_TTL  = timedelta(days=30)     # DECISION D-13, see §14
PBKDF2_ROUNDS = 240_000
SESSION_COOKIE  = "kk_session"
REMEMBER_COOKIE = "kk_remember"
```

---

## 7. Task groups

Each group ends with a green suite and a runnable app. Do not merge groups.

### Group A — Spec authoring (no code)

- **A-1** `npm run ril -- template module|interface|algorithm|invariant --json` — capture the live
  required attributes before authoring.
- **A-2** `ril apply-batch` adding `MOD-KK-AUTH` and the four interfaces of §5.
- **A-3** `ril apply-batch` adding the twelve algorithms, each with `contains` from `MOD-KK-AUTH`.
- **A-4** `ril apply-batch` adding the nine invariants, each with `contains` from `MOD-KK-AUTH`
  and `checked-at` / `enforces` edges where the template permits.
- **A-5** Amend `ALG-KK-WEB-REVIEW-SUBMIT`, `ALG-KK-WEB-PAPER-DETAIL`, `ALG-KK-WEB-REVIEWERS-PAGE`
  descriptions/contracts per §5.
- **A-6** `npm run spec:check` → must stay at 0 errors. Warning count may rise (new algorithms have
  no pipeline stage yet); that is acceptable and matches the existing 1051-warning baseline.
- **A-7** Commit the `.cbm` mutation files.

**Exit:** `spec:check` 0 errors; `ril query node-info MOD-KK-AUTH` lists all 25 new nodes.

### Group B — Auth store (no HTTP)

- **B-1** `src/authgate/__init__.py`.
- **B-2** `src/authgate/schema.py`: `AUTH_SCHEMA_SQL` (§6), `init_auth_db(path) -> Connection`,
  `auth_db_path()` reading `KNOW_KERNEL_AUTH_DB` with default `data/auth.db`.
- **B-3** `src/authgate/store.py`:
  - `hash_password(password, salt=None, iterations=PBKDF2_ROUNDS) -> (hash_hex, salt_hex, iterations)`
  - `verify_password(stored_hash, salt, iterations, candidate) -> bool` — `hmac.compare_digest`
  - `create_user(auth_conn, username, password, role='user') -> UserRecord`
  - `get_user(auth_conn, username) -> UserRecord | None`
  - `list_users(auth_conn) -> list[UserRecord]`
  - `set_password(auth_conn, username, password) -> None`
  - `deactivate_user(auth_conn, username) -> None` — also clears that user's sessions + remember rows;
    raises if the target is the last active admin
  - `authenticate(auth_conn, username, password) -> UserRecord | None`
  - `create_session(auth_conn, username) -> (token, expires_at)`
  - `resolve_session(auth_conn, token) -> UserRecord | None` — deletes the row if expired
  - `slide_session(auth_conn, token) -> None`
  - `delete_session(auth_conn, token) -> None`
  - `create_remember(auth_conn, username) -> token` / `consume_remember(auth_conn, token) -> (UserRecord, new_token) | None` / `delete_remember(auth_conn, token)`
  - `purge_expired(auth_conn) -> int` — called once at gate startup
- **B-4** `tests/test_authgate_store.py` — the "Store" and "Session" blocks of §10.

**Exit:** `pytest tests/test_authgate_store.py -q` green; nothing else in the repo has changed.

### Group C — CLI and roster mirroring

- **C-1** `src/authgate/roster.py`: `ensure_roster_entry(master_conn, username) -> str` — calls
  `find_reviewer` then `register_reviewer` from `src/ingest/reviewer_registry.py`; idempotent;
  returns the `rvr-` node id. This module is the **only** place the gate touches `master.db`.
- **C-2** `src/authgate/cli.py`:
  - `kk-useradd [--admin] [--db PATH] [--auth-db PATH] <username>` — `getpass` twice, confirms match,
    creates the user, then `ensure_roster_entry`, commits both, prints the created username and role
  - `kk-userlist [--auth-db PATH]`
  - `kk-passwd [--auth-db PATH] <username>`
  - Ordering rule: write the user row first, then the roster entry, then commit `auth.db`, then
    commit `master.db`. If the roster write fails, roll back both and exit non-zero — the two-store
    write is not atomic, so it must be **fail-loud**, never silently half-applied.
- **C-3** `tests/test_authgate_cli.py` — creation produces both records; duplicate username exits
  non-zero and leaves no roster entry; the roster entry is idempotent on re-run.

**Exit:** `kk-useradd --admin reinier` creates a working admin and a `Reviewer` node. App still
runs unauthenticated.

### Group D — Gate and login

- **D-1** `src/authgate/gate.py`:
  - `AUTH_EXEMPT_PATHS = ("/login", "/healthz", "/static/")` — a tuple, commented as **the**
    structural enforcement of `INV-KK-AUTH-GATE-COVERS-MOUNT`, in the same style as
    `WEB_MUTATION_ALLOWLIST` at `src/web/routes.py:27-36`
  - `is_exempt(path) -> bool`
  - `safe_next(raw) -> str` — implements `INV-KK-AUTH-NEXT-IS-LOCAL`
  - `install_gate(app, auth_conn_getter)` registering the `@app.middleware("http")` of §4
  - htmx branch: `request.headers.get("HX-Request")` → `Response(status_code=401,
    headers={"HX-Redirect": "/login"})`. Required because `base.html:50-56` fires
    `hx-get /api/search` on every keystroke; a 302 would be swapped into the dropdown as HTML.
- **D-2** `src/authgate/templates/login.html` — standalone (D-10): username, password,
  "Remember me on this device" checkbox, hidden `next`, one generic error slot. Monospace styling
  copied from `base.html:8` so it does not look foreign.
- **D-3** `src/authgate/app.py`:
  - `create_gate_app(db_path, auth_db_path) -> FastAPI`
  - lifespan opens `auth.db`, runs `AUTH_SCHEMA_SQL`, `purge_expired`, stores it on
    `app.state.auth_conn`, closes on shutdown
  - `GET /login`, `POST /login`, `POST /logout`, `GET /healthz`
  - `install_gate(...)` **before** the mount
  - `app.mount("/", create_app(db_path))`
  - `app = create_gate_app(os.environ.get("KNOW_KERNEL_DB", ":memory:"), auth_db_path())`
  - `main()` for `uvicorn authgate.app:app`
  - Fail-closed rule: if `auth.db` cannot be opened, the gate must refuse to start rather than
    starting with everything open.
- **D-4** `pyproject.toml`: declare `python-multipart` (the login form posts urlencoded);
  add `src/authgate` to `[tool.hatch.build.targets.wheel] packages`. **Do not** add `itsdangerous`
  — D-4/D-8 removed the need.
- **D-5** `tests/test_authgate.py` — the "Gate" block of §10.

**Exit:** anonymous `GET /` bounces to `/login`; login works; refresh keeps the session;
`pytest tests/test_web.py tests/test_source_abstract.py -q` still green **unchanged**.

### Group E — Admin UI

- **E-1** `src/authgate/templates/admin_users.html` — table of username / role / active /
  created_at; an add form; deactivate and reset-password buttons. Under 50 users (requirement 10),
  so no pagination, search, or sorting.
- **E-2** Routes `GET /admin/users`, `POST /admin/users`,
  `POST /admin/users/{username}/deactivate`, `POST /admin/users/{username}/password` in
  `src/authgate/app.py`; each asserts `request.state.user["role"] == "admin"` → 403 otherwise.
- **E-3** `POST /admin/users` calls `ensure_roster_entry` in the same handler, with the same
  fail-loud ordering as C-2.
- **E-4** Tests: non-admin gets 403 on every `/admin/*` path; admin can create; the created user
  can log in; deactivation kills the target's live sessions; the last active admin cannot be
  deactivated.

**Exit:** users manageable from the browser without the CLI.

### Group F — Implicit reviewer identity

- **F-1** `src/web/routes.py:1071-1099` `submit_review`:
  - read `identity = getattr(request.state, "user", None)`; if `None` → 401 JSON
    `{"error": "Not authenticated"}` (defensive; the gate should have caught it)
  - `reviewer = identity["reviewer"]`
  - pass that to `review_paper`; **delete** the `body["reviewer"]` read
  - keep the existing 404 / 409 / 422 mapping untouched
- **F-2** `src/web/routes.py:826` — delete the `"reviewers": [r.name for r in list_reviewers(conn)],`
  context entry.
- **F-3** `src/web/routes.py:670` — the `from ingest.reviewer_registry import list_reviewers` import
  inside `paper_detail` becomes unused; delete it. **Do not** touch the identical import at
  `src/web/routes.py:1032`, which the `/reviewers` page still needs.
- **F-4** `src/web/templates/paper_detail.html:291-304` — delete the whole `<label>Reviewer:</label>`
  + `<select name="reviewer">` + `{% if not reviewers %}` warning block. Current text:

  ```html
  <label>Reviewer:</label>
  <select name="reviewer" required
          style="font-family:monospace;padding:0.2rem 0.4rem;width:100%;">
    <option value="">-- select --</option>
    {% for name in reviewers %}
    <option value="{{ name }}">{{ name }}</option>
    {% endfor %}
  </select>
  {% if not reviewers %}
  <p style="font-size:0.85em;color:#c0392b;margin:0.3em 0 0 0;">
    No reviewers registered. Add one on the <a href="/reviewers">Reviewers</a> page first.
  </p>
  {% endif %}
  ```

  Replacement (DECISION D-14, see §14 — one static line, no widget):

  ```html
  <p style="margin:0;font-size:0.9em;color:#555;">
    Reviewing as <strong>{{ request.state.user.reviewer }}</strong>
  </p>
  ```

- **F-5** `src/web/templates/paper_detail.html:437` — delete
  `if (!form.reviewer.value) { status.textContent = 'Select a reviewer'; ... return; }`.
- **F-6** `src/web/templates/paper_detail.html:439` — delete the `reviewer: form.reviewer.value,`
  line from the `data` object. Leave `score`, `verdict`, `rationale` unchanged.
- **F-7** `src/web/templates/base.html:43-60` nav — append, after the existing links and before the
  search span:

  ```html
  {% if request.state.user %}
    <span style="margin-left:1rem;color:#555;">{{ request.state.user.username }}</span>
    {% if request.state.user.role == 'admin' %}<a href="/admin/users">Admin</a>{% endif %}
    <form method="post" action="/logout" style="display:inline;">
      <button type="submit" style="font-family:monospace;">Logout</button>
    </form>
  {% endif %}
  ```

  The `{% if %}` guard matters: `tests/test_web.py` renders these templates through `create_app`
  with **no** gate and therefore no `request.state.user`. Without the guard all 167 tests break.
  Jinja's undefined is falsy on attribute access via `request.state.user`, but `state` raises
  `AttributeError` if absent — so the store must set the key or the template must use
  `request.state.user is defined`. **Verify which during implementation** and pick the form that
  keeps the ungated tests green; the F-9 test exists to catch exactly this.
- **F-8** `src/web/templates/reviews.html` — **no change**. Its `<select>` elements at lines 8 and 14
  are verdict and min-score filters.
- **F-9** Tests in `tests/test_authgate.py`: gated `GET /paper/{id}` contains no
  `<select name="reviewer">`; `POST /api/review/{id}` with no reviewer field succeeds and the
  created `HumanReview` carries the session username; a body-supplied `reviewer` is ignored;
  and an **ungated** `create_app` render of `/paper/{id}` and `/` still returns 200 (regression
  guard for F-7).

**Exit:** the dropdown is gone; attribution comes from the session; `tests/test_web.py` unchanged
and green.

### Group G — Entry points and documentation

- **G-1** `pyproject.toml:33-38`: `kk-web = "authgate.app:main"`;
  add `kk-useradd = "authgate.cli:useradd"`, `kk-userlist = "authgate.cli:userlist"`,
  `kk-passwd = "authgate.cli:passwd"`.
- **G-2** `start.bat` and `start.sh`: launch `authgate.app:app`; set
  `KNOW_KERNEL_AUTH_DB` (default `<script dir>/data/auth.db`); print the auth DB path alongside the
  existing DB and URL lines; keep `--reload`.
- **G-3** `.gitignore`: `data/auth.db`, `data/auth.db-wal`, `data/auth.db-shm`.
- **G-4** `README.md`: a "Users and login" section — first-admin bootstrap with `kk-useradd --admin`,
  the two env vars, and an explicit warning that `uvicorn web.app:app` bypasses the gate and must
  not be used (the accepted risk of D-1).
- **G-5** Full-suite run and manual smoke test per §12.

**Exit:** a fresh clone, `kk-useradd --admin`, `./start.sh` → login page → dashboard.

---

## 8. Complete file manifest

### New files

| Path | Purpose |
|---|---|
| `src/authgate/__init__.py` | package marker |
| `src/authgate/schema.py` | `AUTH_SCHEMA_SQL`, `init_auth_db`, `auth_db_path` |
| `src/authgate/store.py` | users, sessions, remember tokens, hashing |
| `src/authgate/roster.py` | `ensure_roster_entry` — the only `master.db` touchpoint |
| `src/authgate/gate.py` | `AUTH_EXEMPT_PATHS`, `is_exempt`, `safe_next`, `install_gate` |
| `src/authgate/app.py` | `create_gate_app`, login/logout/admin routes, mount, `main` |
| `src/authgate/cli.py` | `kk-useradd`, `kk-userlist`, `kk-passwd` |
| `src/authgate/templates/login.html` | standalone login page |
| `src/authgate/templates/admin_users.html` | admin user table |
| `tests/test_authgate_store.py` | store + session unit tests |
| `tests/test_authgate_cli.py` | CLI + roster mirroring |
| `tests/test_authgate.py` | gate, login, roles, identity, regression |

### Modified files

| Path | Line(s) | Change |
|---|---|---|
| `src/web/routes.py` | 1071-1099 | reviewer from `request.state.user`, body field ignored |
| `src/web/routes.py` | 826 | drop `"reviewers"` context entry |
| `src/web/routes.py` | 670 | drop now-unused `list_reviewers` import (keep the one at 1032) |
| `src/web/templates/paper_detail.html` | 291-304 | delete select + warning, add "Reviewing as" line |
| `src/web/templates/paper_detail.html` | 437 | delete client-side reviewer guard |
| `src/web/templates/paper_detail.html` | 439 | delete `reviewer:` body field |
| `src/web/templates/base.html` | 43-60 | user indicator, Admin link, Logout form (guarded) |
| `pyproject.toml` | 9-15 | declare `python-multipart` |
| `pyproject.toml` | 33-38 | `kk-web` → authgate; add three CLI entry points |
| `pyproject.toml` | 44 | add `src/authgate` to wheel packages |
| `start.bat` | tail | authgate entry point + `KNOW_KERNEL_AUTH_DB` |
| `start.sh` | tail | authgate entry point + `KNOW_KERNEL_AUTH_DB` |
| `.gitignore` | — | `data/auth.db*` |
| `README.md` | — | "Users and login" section |

### Explicitly untouched (assert this in review)

`src/graph/schema.py` · `src/graph/rules.py` · `src/graph/engine.py` · `src/export/exporter.py` ·
`src/mcp_server/**` · `src/ingest/paper_scorer.py` · `src/ingest/reviewer_registry.py` ·
`WEB_MUTATION_ALLOWLIST` (`src/web/routes.py:27-36`) · all 21 GET routes ·
`src/web/templates/reviews.html` · `src/web/templates/reviewers.html` · `tests/test_web.py` ·
`tests/test_source_abstract.py`.

---

## 9. Commit sequence

| # | Group | Commit message | Green after |
|---|---|---|---|
| 1 | A | `spec: MOD-KK-AUTH — gate, session, identity nodes` | `spec:check` 0 errors |
| 2 | B | `feat: auth store — users, sessions, remember tokens` | `pytest tests/test_authgate_store.py` |
| 3 | C | `feat: kk-useradd CLI with roster mirroring` | `pytest tests/test_authgate_cli.py` |
| 4 | D | `feat: authentication gate with login and mounted app` | full suite |
| 5 | E | `feat: admin user management` | full suite |
| 6 | F | `feat: implicit reviewer identity from session` | full suite |
| 7 | G | `chore: switch entry points to the auth gate` | full suite + manual smoke |

One logical change per commit (CLAUDE.md rule #7); `npm run spec:check` before each; `.cbm` files
travel with commit 1.

---

## 10. Test plan

### Store (`tests/test_authgate_store.py`)
1. `create_user` writes a row; `get_user` returns it.
2. Duplicate username raises.
3. `authenticate` succeeds with the right password.
4. `authenticate` fails with the wrong password.
5. The stored hash is not the password, and two users with the same password get different hashes (distinct salts).
6. A deactivated user cannot authenticate.
7. Username lookup is case-insensitive and whitespace-trimmed.
8. `set_password` invalidates the old password.
9. `deactivate_user` refuses on the last active admin.

### Session (`tests/test_authgate_store.py`)
10. A fresh session resolves to its user.
11. An expired session does not resolve and its row is gone afterwards.
12. `slide_session` pushes `expires_at` forward.
13. `delete_session` revokes immediately.
14. `consume_remember` on a valid token returns the user **and** a new token.
15. The consumed token no longer resolves (rotation / replay).
16. An expired remember token does not resolve.
17. A remember token for a deactivated user does not resolve.
18. `purge_expired` removes only expired rows.

### CLI (`tests/test_authgate_cli.py`)
19. `kk-useradd` creates the user **and** the `Reviewer` node.
20. Re-running for an existing username exits non-zero and creates no second roster entry.
21. `ensure_roster_entry` is idempotent when the roster entry already exists.
22. `--admin` sets `role='admin'`.
23. The password never appears in argv or in captured output.

### Gate (`tests/test_authgate.py`)
24. Anonymous `GET /` → 302 to `/login?next=/`.
25. `GET /login` is 200 while anonymous.
26. `POST /login` with valid credentials → 302 to the validated `next`, session cookie set.
27. `POST /login` with bad credentials → 401 and one generic message; no cookie.
28. After login, `GET /` → 200.
29. `GET /docs` and `GET /openapi.json` are gated while anonymous.
30. An `HX-Request` header while anonymous → 401 with `HX-Redirect: /login`.
31. `POST /logout` clears the cookie; the next `GET /` → 302.
32. A session past its TTL, with a valid remember cookie → request succeeds and a new session cookie is issued.
33. A session past its TTL with **no** remember cookie → 302 to `/login`.
34. `next=https://evil.example` and `next=//evil.example` are both rejected in favour of `/`.

### Roles (`tests/test_authgate.py`)
35. A non-admin `GET /admin/users` → 403.
36. An admin `GET /admin/users` → 200 listing all users.
37. An admin `POST /admin/users` creates a user who can then log in, and creates the roster entry.
38. A non-admin `POST /admin/users` → 403 and creates nothing.
39. Deactivating a user invalidates that user's live session on their next request.

### Identity and reviews (`tests/test_authgate.py`)
40. Gated `GET /paper/{id}` HTML contains no `<select name="reviewer">`.
41. Gated `GET /paper/{id}` shows "Reviewing as <username>".
42. `POST /api/review/{id}` with `{score, verdict, rationale}` and no reviewer → 201; the stored `HumanReview.reviewer` equals the session username.
43. The same POST **with** `"reviewer": "someone-else"` → the stored reviewer is still the session user.
44. A second review of the same paper by the same session user → 409 (`INV-KK-REVIEW-SINGLE-PER-REVIEWER` still holds).
45. The nav shows the username and a Logout control; a non-admin sees no Admin link.

### Regression (must pass unmodified)
46. `pytest tests/test_web.py -q` — all 167.
47. `pytest tests/test_source_abstract.py -q` — including the router sweep, still built on `create_app`.
48. An ungated `create_app` render of `/` and `/paper/{id}` returns 200 with no identity present (guards F-7).

---

## 11. Fixture design (important)

Three distinct fixtures; keeping them separate is what preserves the 167 existing tests.

```python
# tests/test_authgate.py
@pytest.fixture
def gated(tmp_path):
    """Full stack: gate + mounted app + seeded admin and plain user."""
    master = tmp_path / "master.db"; conn = init_db(master); ...seed a Source...; conn.close()
    auth = tmp_path / "auth.db"
    aconn = init_auth_db(auth)
    create_user(aconn, "boss", "pw-boss", role="admin")
    create_user(aconn, "reinier", "pw-user", role="user")
    aconn.commit(); aconn.close()
    mconn = sqlite3.connect(master)
    ensure_roster_entry(mconn, "boss"); ensure_roster_entry(mconn, "reinier")
    mconn.commit(); mconn.close()
    app = create_gate_app(str(master), str(auth))
    with TestClient(app) as c:
        yield c            # anonymous by default; tests log in explicitly

def login(client, username, password, remember=False):
    return client.post("/login", data={"username": username, "password": password,
                                       "remember": "on" if remember else ""},
                       follow_redirects=False)
```

`TestClient` persists cookies across calls, so one `login(...)` authenticates the rest of a test.

`tests/test_web.py`'s existing `client` fixture (line 17) stays on `create_app` — **do not**
convert it. Same for `tests/test_source_abstract.py`.

For time-dependent tests (32, 33, 11), do **not** sleep. Either expose `SESSION_TTL` as a
module constant and monkeypatch it, or write the `expires_at` column directly to a past ISO
timestamp. Prefer the direct DB write — it is deterministic and does not depend on import order.

---

## 12. Verification

Baseline re-confirmation before editing (all read-only):

```bash
npm run spec:check | grep -c '"severity": "error"'        # expect 0
npm run ril -- query node-info MOD-KK-WEB --json | grep -c '"to"'
grep -n "select name=\"reviewer\"" src/web/templates/paper_detail.html   # expect 292
grep -n "reviewers" src/web/routes.py                                    # expect 33,670,826,1032,1037,1040,1047,1051
grep -rn "api/review" tests/                                             # expect no matches
pytest tests/ -q                                                         # note pre-existing failures
```

After each group:

```bash
npm run spec:check
pytest tests/ -q
pytest tests/test_web.py tests/test_source_abstract.py -q    # regression proof
```

Manual smoke (Group G):

```bash
kk-useradd --admin reinier
./start.sh                       # or start.bat
```

1. `http://localhost:8000/` → redirected to `/login`.
2. Log in without "remember me" → dashboard; the nav shows `reinier` and Logout.
3. Refresh, follow links → still logged in.
4. Restart the server → still logged in (server-side session, not tied to process state).
5. Open a paper → no reviewer dropdown; "Reviewing as reinier"; submit a review; it appears attributed correctly.
6. `/admin/users` → visible as admin; create a second, non-admin user; log in as them; `/admin/users` → 403.
7. Log out → `/` bounces to `/login`.
8. Expire the session by hand (`UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'`) with a remember cookie present → refresh proceeds silently and a new session row appears.
9. `curl -s -o /dev/null -w '%{http_code}' localhost:8000/api/search?q=x` → 302 (anonymous).

---

## 13. Known risks and accepted trade-offs

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R-1 | `uvicorn web.app:app` bypasses the gate entirely | HIGH | Switch all entry points (G-1, G-2); document loudly (G-4). Structural fix is impossible without moving the gate into `MOD-KK-WEB`, which D-1 rejects. |
| R-2 | The two-store write in `ALG-KK-AUTH-USER-CREATE` is not atomic | MEDIUM | Fail-loud ordering (C-2); `ensure_roster_entry` is idempotent, so re-running repairs a half-applied state. |
| R-3 | A `Reviewer` node renamed or deleted in `master.db` breaks attribution → 422 on submit | MEDIUM | Username-as-roster-name (D-7); `ensure_roster_entry` on login could self-heal — deferred, see §16. |
| R-4 | `auth.db` unreachable → gate must not start open | MEDIUM | Fail-closed in the D-3 lifespan; test 24 covers the closed path. |
| R-5 | Nav template touches `request.state.user` in ungated tests | MEDIUM | `{% if %}` guard (F-7) plus regression test 48. |
| R-6 | Pre-existing red tests (`tests/test_graph_schema.py:19-28,32-46`: 24 vs 27 node kinds, 35 vs 37 edge kinds) will be misread as auth fallout | LOW | Fix separately via `/cb-fix` **before** starting, so the suite is green at baseline. See §15 step 0. |
| R-7 | Remember tokens are long-lived on shared machines | LOW | Accepted per requirement 3; rotation on use limits replay; "remember me" is opt-in and unchecked by default. |
| R-8 | No CSRF tokens | LOW | Accepted per requirement 3; `SameSite=Lax` on both cookies. |
| R-9 | New algorithms will raise `AUTH-WARN-ORPHANED-ALGO` warnings | INFO | Consistent with the existing 1051-warning baseline; only the error count is a gate. |

---

## 14. Open decisions

**D-13 — Remember-me duration.** Plan assumes **30 days**. Alternatives: 7 days (tighter) or
90 days (fewer logins). Single constant `REMEMBER_TTL` in `src/authgate/schema.py`. *Not blocking
Group A or B.*

**D-14 — The "Reviewing as <user>" line.** Plan includes one static line of text (F-4). The operator
asked for the dropdown to go away; this is not a widget and nothing is selectable, but it is more
than literally nothing. Drop the `<p>` if unwanted. *Not blocking Group A–E.*

Both default as written if no answer arrives; note the choice in the commit message.

---

## 15. Suggested `/cb-*` sequence for the implementing session

```
step 0   /cb-fix    reconcile tests/test_graph_schema.py stale kind counts (24→27, 35→37)
                    — do this FIRST so the baseline suite is green (R-6)
step 1   /cb-green  Group A — author MOD-KK-AUTH spec nodes
step 2   /cb-green  Group B — auth store + unit tests
step 3   /cb-green  Group C — kk-useradd CLI + roster mirroring
step 4   /cb-green  Group D — gate, login page, mount, entry-point wiring for dev
step 5   /cb-green  Group E — admin user management
step 6   /cb-green  Group F — implicit reviewer identity, dropdown removal
step 7   /cb-green  Group G — entry points, gitignore, README
step 8   /cb-audit  read-only confirmation: spec:check, full suite, INV-KK-AUTH-* coverage
```

Groups B and C can be merged into one `/cb-green` if the session has budget; A must stand alone
(spec before code, rule #3), and F must come after D (it depends on `request.state.user`).

---

## 16. Deliberately out of scope

Recorded so a future session does not treat these as oversights:

- **Roster removal.** Rejected in D-6. If it is ever wanted, it is its own plan: ~10 source/test
  files and ~9 spec nodes, and it needs explicit rule-#4 approval.
- **Display names distinct from usernames.** D-7. The `reviewer` key in the identity dict exists so
  this can be added later without touching call sites.
- **Ownership checks on review edit/delete.** `update_review` (`routes.py:1101`) and `remove_review`
  (`routes.py:1128`) currently let any authenticated user edit or delete any review. With identity
  available this becomes possible to restrict; not requested.
- **Self-healing roster on login** (would mitigate R-3).
- **Password reset by email, rate limiting, account lockout, CSRF tokens, 2FA** — D-11.
- **HTTPS / secure-cookie enforcement.** `https_only` is a config flag defaulting to `False`;
  deployment is `127.0.0.1`.
- **Per-user permissions beyond admin/user** — requirement 9 asks for exactly two roles.
- **Auth for MCP, ingest, export.** Not HTTP-reachable; see the scope note in §5.
- **Session listing / "log out everywhere" UI.** The store supports it (`sessions` is queryable by
  username); no UI is planned.
