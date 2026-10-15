# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SIP-Plan — a Django 5 web application for Thai government budget planning and project tracking (ระบบบริหารแผนงาน โครงการ และติดตามงบประมาณ). All user-facing text is Thai; locale is `th-th` / `Asia/Bangkok`.

## Commands

The local virtualenv is `.venv/` (Python 3.14, Django 5.2). Always run through it:

```bash
.venv/bin/python manage.py runserver          # dev server on :8000, SQLite
.venv/bin/python manage.py makemigrations
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py shell
.venv/bin/python manage.py collectstatic --noinput
```

Docker (MySQL + gunicorn; migrate and collectstatic run automatically on boot):

```bash
docker compose up --build
```

Back up the database (safe while the app is running):

```bash
./scripts/backup_db.sh
```

There is no linter and no frontend build step in this repo.

## Database

Config is read via `django-environ`. `core/settings.py` calls `read_env()` on `.env` at the project root when present; real environment variables always win. `.env` is git-ignored — `.env.example` documents every variable.

`USE_SQLITE` **defaults to `True`**. SQLite is used unless `USE_SQLITE=False`, and only then are `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` read for MySQL.

### The SQLite file must live outside any cloud-sync folder

The project directory is inside **Synology Drive**. Sync clients (Synology Drive, Dropbox, iCloud, Google Drive) do not honour the POSIX file locks SQLite depends on and will copy the file mid-write, which corrupts it. The database therefore lives at `~/sip-plan-data/db.sqlite3`, set via `SQLITE_PATH` in `.env`.

Never point `SQLITE_PATH` back inside the project directory, and never commit a `.sqlite3` file. The SQLite `OPTIONS` in settings enable WAL, `synchronous=NORMAL`, `transaction_mode='IMMEDIATE'`, and a 20s lock timeout.

Data size is not a reason to move to MySQL — the dataset is tiny (tens of rows) and SQLite scales far beyond it. The only reason to switch is many concurrent **writers** (roughly 10+ sustained) or a multi-server deployment.

### Backups

`scripts/backup_db.sh` runs `sqlite3 .backup` (safe on a live database — never `cp`), verifies `integrity_check`, gzips, and prunes backups older than `KEEP_DAYS` (default 30) from `~/sip-plan-data/backups/`. `~/sip-plan-data/pre-migration/` holds pre-move snapshots.

### Docker

`docker-compose.yml` starts a MySQL service but does **not** set `USE_SQLITE=False`, so the `web` container still runs on SQLite and the MySQL service goes unused. Set `USE_SQLITE=False` in the web service's environment if MySQL is actually wanted.

## Architecture

Two apps: `users` (identity, roles, departments, profiles) and `plans` (everything else). `core/` is the project package. Templates live in a single top-level `templates/` directory, not per-app.

### Domain hierarchy

```
Plan (แผนงาน, per fiscal year, self-nesting via `parent`)
└── Project (โครงการ)
    ├── ProjectMember (with contribution_percent)
    └── TaskGroup (a Kanban column, with its own budget + dates)
        └── ProjectTask (งาน — the unit that actually spends budget)
            ├── TaskAttachment / TaskComment / TaskFollower
            └── TaskTag (m2m, per-project)
```

`Plan.parent` is a self-FK, but the code assumes exactly two levels everywhere: views build a flat `parent_plans` list plus a `children_map` dict keyed by parent id, rather than recursing. Preserve that shape when touching `DashboardView`, `PlanListView`, or `ProjectFilterMixin`.

### Budget model — spend is derived, never stored

Every budget figure splits into two buckets: `CURRENT` (งบประมาณปีปัจจุบัน) and `CARRY_OVER` (งบเหลื่อมปี). Plans hold `allocated_*`, projects hold `requested_*`, and tasks hold a single `amount` tagged with a `budget_source`.

Nothing records "money spent." Remaining budget is recomputed on read from tasks where `is_completed=True`:

- `Plan.remaining_current_budget` / `remaining_carry_over_budget` aggregate completed tasks across the plan **and its direct children**.
- `TaskGroup.disbursed_amount` / `remaining_budget` / `budget_usage_percent` do the same at group level.

So marking a task complete is what "disburses" its budget. `DashboardView.total_allocated` deliberately sums **parent plans only**, because child plan budgets are already counted inside the parent — don't "fix" this into summing all plans.

### Project status is computed, not stored

`Project.status` (with `STATUS_CHOICES`) exists on the model but the UI does not use it. Display goes through `Project.dynamic_status_display`, derived from task completion and dates: `"สำเร็จ"` (all tasks done) → `"เกินกำหนด"` (past `end_date`) → `"กำลังดำเนินการ (ขอขยายเวลา)"` (`is_extended`) → `"กำลังดำเนินการ"`. Aggregates such as `Plan.completed_projects_count` compare against these Thai strings, so changing the wording breaks counting.

### Soft delete applies to Plan only

`Plan.delete()` is overridden to set `is_deleted`/`deleted_at`. `Plan.objects` is an `ActivePlanManager` that filters deleted rows out; `Plan.all_objects` sees everything. Queries in views nonetheless spell out `.filter(is_deleted=False)` in most places. `Plan.parent` and `Project.plan` use `on_delete=RESTRICT` to keep the hierarchy intact. Every other model hard-deletes.

### Thai fiscal year

`Plan.fiscal_year` is a Buddhist-era year (พ.ศ.). It is computed as `timezone.now().year + 543` and this conversion is repeated inline in `DashboardView`, `PlanListView`, and `ProjectFilterMixin` — all default their year filter to the current Thai year.

### Authentication

Two login paths, both live:

- **Username/password** — Django's own `LoginView`, subclassed as `SIPLoginView` in `core/urls.py` only to add `google_login_enabled` / `google_allowed_domain` to the context. Template `templates/registration/login.html`.
- **Google (django-allauth)** — restricted to the `@ubu.ac.th` Google Workspace domain.

`AUTHENTICATION_BACKENDS` lists `ModelBackend` **first**; removing it breaks password login for everyone. `django.contrib.sites` is deliberately *not* installed — the Google app is configured through `SOCIALACCOUNT_PROVIDERS['google']['APPS']` in settings, so no `SocialApp` DB row and no `SITE_ID` are needed. If anyone adds the sites framework later they must add `SITE_ID` and must not also create a DB `SocialApp`.

**`core/urls.py` include order is load-bearing:** `accounts/login/` (ours) → `django.contrib.auth.urls` → `allauth.urls`. Django matches top-down, so our login page wins `/accounts/login/` while `/accounts/google/...` falls through to allauth. URL *names* don't collide (`login` vs `account_login`). Reordering silently swaps the login page for allauth's English template.

**The domain gate lives in `users/adapters.py`, not in settings.** `SOCIALACCOUNT_PROVIDERS[...]['AUTH_PARAMS']['hd']` only pre-filters Google's account chooser and is user-editable in the URL — it is not a security control. `UbuGoogleSocialAccountAdapter.pre_social_login()` does the real check: verified email, exact `rsplit('@', 1)[-1] == GOOGLE_ALLOWED_DOMAIN` (never `endswith`, which would admit `student.ubu.ac.th` and `evil-ubu.ac.th`), `hd` claim cross-check, and active-account check. Rejections raise `ImmediateHttpResponse` after `messages.error`, so **`login.html` must keep its `{% if messages %}` block** or the reason vanishes.

Account-takeover controls, all required together: `User.Meta` has a case-insensitive unique constraint on non-blank `email`; `ProfileUpdateForm` deliberately has **no `email` field** (a user who could edit their own email could point it at a colleague's and capture that colleague's first Google login); and `can_authenticate_by_email()` refuses to auto-link `is_superuser`/`is_staff`/`is_executive` accounts.

### Profile completion

New users must complete a profile before using the app. `users.middleware.ProfileCompletionMiddleware` (last in `MIDDLEWARE`) enforces it from `process_view` — not `__call__`, where `request.resolver_match` is still `None` and only fragile path-prefix matching is available.

`User.profile_completed` is a **cache** read on every request; `UserProfile.is_complete` (driven by `REQUIRED_PROFILE_FIELDS` / `REQUIRED_USER_FIELDS` in `users/constants.py`) is the truth. `UserProfile.sync_completion()` writes the cache with a targeted `queryset.update()` so it cannot clobber concurrent role edits, and it **only ever upgrades** `False → True`. It must never revoke the flag: users grandfathered in by migration `0005` do not satisfy the current required-field set, so a downgrade would throw them into the setup flow the moment they saved an unrelated profile edit. Re-prompting is done by bumping `PROFILE_SCHEMA_VERSION`, never by recomputing the flag downward. Bumping `PROFILE_SCHEMA_VERSION` in settings re-prompts everyone without a data migration.

Exempt from enforcement: the `admin`, `account` and `socialaccount` namespaces, `/accounts/*` (blocking the Google callback would deadlock login), `/admin/` (the recovery hatch), static/media, and any view decorated `@profile_completion_exempt`. Three independent guards prevent a redirect loop.

JSON endpoints get a `403` JSON body instead of a `302`. Detection is via the `@json_endpoint` decorator on the three `task_tag_*_api` views, because the delete `fetch()` in `project_task_form.html` sends no `Content-Type` and header sniffing alone would miss it. The existing JS reads `data.error` regardless of status, so it works unchanged.

### Authorization

There are no Django groups or permissions. Roles are boolean flags on the custom `users.User` model (`AUTH_USER_MODEL = 'users.User'`): `is_executive`, `is_budget_officer`, `is_finance_officer`, `is_department_head`, `is_general_staff`, alongside built-in `is_staff` / `is_superuser`. They are edited both through the app's own screen (`user_permission_edit`) and via `CustomUserAdmin`'s "RBAC Info" fieldset.

Three patterns are in use:

- `plans.views.BudgetOfficerMixin` — plan/project create, edit, delete.
- `users.views.AdminRequiredMixin` (`is_staff or is_executive`) — user and department management.
- An inline predicate repeated across task-level views and function views:
  `user.is_staff or user.is_executive or user.is_budget_officer or project.members.filter(user=user).exists()`
  This is both the `test_func` for class-based task views and the `can_edit` flag pushed into context for templates. Read-only views (`ProjectDetailView`, `ProjectTaskBoardView`) compute `can_edit` the same way and let templates hide controls. Keep the predicate identical in all three places when changing access rules.

Note `ProjectListView` shows every project to any logged-in user; `MyProjectListView` is the filtered "mine" view (`created_by` or membership).

### Views layer

`plans/views.py` (~750 lines) mixes Django CBVs for CRUD with `@login_required` function views for the interactive parts — attachments, comments, follower toggle, task groups, and the tag endpoints. `ProjectFilterMixin` supplies the shared year + `q` search filtering and builds the plan-tree context consumed by the project list templates; it depends on the subclass assigning `self.queryset` inside `get_queryset()` before calling `super()`.

The three `task_tag_*_api` views are JSON endpoints: they `json.loads(request.body)`, return `JsonResponse`, and answer 403 with `{'error': ...}` rather than redirecting. They are the only non-HTML responses in the app.

### Frontend

Server-rendered Django templates. Tailwind comes from the CDN (`cdn.tailwindcss.com`) and is configured inline in `templates/base.html` — there is no `package.json`, no PostCSS, no compiled CSS, so utility classes must be plain Tailwind. Also loaded from CDN: Tom Select (searchable dropdowns), Font Awesome, Google Fonts.

The typeface is **IBM Plex Sans Thai** (weights 300–700), declared in three places per template: the Google Fonts `<link>`, `tailwind.config.theme.extend.fontFamily.sans`, and the `font-family` CSS rules. `templates/registration/login.html` is a standalone page that does not extend `base.html`, so it carries its own copy of the Tailwind config, the font link, and the blue palette — a font or colour change must be applied to both files. `base.html` also sets the font imperatively on Tom Select inputs (a `!important` CSS block plus `input.style.fontFamily` in the `onInitialize` callback), because Tom Select injects its own styles.

`TaskTag.color` stores a **Tailwind class string** (e.g. `bg-slate-500 text-white`) directly in the database and templates interpolate it into `class=`. Because Tailwind is CDN-based and unpurged this works, but it means tag colors must remain valid Tailwind utilities.

The shared `<head>` (favicon, Tailwind config, IBM Plex Sans Thai) now lives in `templates/includes/head_assets.html` and is included by `base.html`, `registration/login.html`, `users/profile_setup.html` and `socialaccount/authentication_error.html` — change the font or palette there, once.

`templates/users/includes/avatar.html` renders a profile photo with the old initial-letter circle as fallback; `templates/users/includes/field.html` renders one labelled form field. Standalone pages that must not show the sidebar (login, profile setup, OAuth error) do not extend `base.html`, partly because `base.html` installs a global submit-confirm handler on every `button[type=submit]`.

`templates/plans/includes/task_card.html` and `templates/plans/partials/project_card.html` are shared fragments; the Kanban board is `templates/plans/project_task_board.html`.

### Django admin

Registered: `User`, `Department`, `Plan`, `Project`, `ProjectMember`, `ProjectTask`. The Kanban-era models (`TaskGroup`, `TaskTag`, `TaskAttachment`, `TaskComment`, `TaskFollower`) are not registered.

`UserProfile` is registered as its own `ModelAdmin`, **never as an inline on `CustomUserAdmin`** — an inline would expose every staff member's national ID to anyone who can edit users. `national_id` is excluded from `search_fields` (a searchable ID is an existence oracle and lands in web-server access logs) and is shown masked except to superusers.

`PlanAdmin` lists and filters on `is_deleted`, but `ModelAdmin` uses the model's default manager — `ActivePlanManager` — so soft-deleted plans never appear there. Override `get_queryset()` to use `Plan.all_objects` if they need to be visible.

## Conventions

- Comments, `help_text`, and `verbose_name` are written in Thai; match that when adding fields.
- `users.signals.show_login_message` pushes a message on `user_logged_in`, so `Client.force_login()` raises `MessageFailure` ("You cannot add messages without installing MessageMiddleware") — the test client's bare request has no message storage. Disconnect the receiver first: `user_logged_in.disconnect(show_login_message)`. Real requests are unaffected.
- **Django `{# ... #}` comments are single-line only.** A multi-line `{# ... #}` block is *not* commented out — its contents render, and any `{% %}` tag inside actually executes. An include example inside such a block once made `avatar.html` include itself into infinite recursion. Use `{% comment %}...{% endcomment %}` for anything spanning lines.
- Model `max_length` runs **before** the form's `clean_<field>()`, so a field that accepts punctuation the model won't store (`081-234-5678`, `1-2345-67890-12-3`) must be redeclared on the form with a wider `max_length`, with the real validation done after normalising. See `mobile_phone` / `national_id` in `users/forms.py`.
- `ModelForm.save(commit=False)` has already written the new upload onto `instance.photo` by the time custom save logic runs, so the *old* file name must be captured in `__init__` (`_remember_old_photos`) or the previous image is orphaned on disk.
- Dates are entered and displayed as **พ.ศ.** but stored as CE. Use `ThaiDateField` (`users/forms.py`) at the form boundary — `date(2510, 1, 1)` is valid Python and would corrupt data silently. This differs from `Plan.fiscal_year`, which stores พ.ศ. directly because it is an `IntegerField`, not a `DateField`.
- The app shell in `base.html` is a fixed-viewport layout: `body` is `overflow-hidden`, the wrapper is `h-screen overflow-hidden`, and `aside` and `main` each scroll internally. The document itself must never scroll — if it does, the shell scrolls away and leaves blank space below it.
- `ProjectTaskBoardView` prefetches `tasks__attachments`, `tasks__comments`, `tasks__followers`. Many budget/status properties hit the database per call, so keep `select_related`/`prefetch_related` in list and board views.
- `*.sqlite3`, `media/`, `staticfiles/`, `.venv/`, and `.env` are git-ignored; the working database lives outside the repo entirely (see **Database**).
