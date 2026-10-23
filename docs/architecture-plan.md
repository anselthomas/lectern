# Lectern: backend architecture and AWS deployment plan

Status: v2, 2026-10-24 — phases 0–6 built and deployed; payments, SES email, Google sign-in and Teams still to do. Based on the 36 screens in `Lectern — Study-from-PDF App.html`.
Payments (screens 11, 13) are out of scope for this phase. Billing UI reads from a `plans` table so Stripe/Razorpay can plug in later.

---

## 0. Account constraints (found in phase 1)

The AWS account was created with AWS's new sign-up flow (Google login, "projects"). AWS manages its organization and applies fixed service control policies:

- **Home region is ap-southeast-2 (Sydney).** AWS assigns it from the contact country (India → Sydney), and it can't be changed without "Activate advanced AWS features". All regional resources (EC2, Cognito, SES, SSM, ECR, S3 data buckets) go in Sydney. In us-east-1 only global services work, plus Bedrock inference.
- **Bedrock runs in us-east-1.** The app calls `global.amazon.nova-2-lite-v1:0` and `amazon.titan-embed-text-v2:0` through the us-east-1 endpoint, which works. Sydney Bedrock was still "being verified" on 2026-10-23. The region is a config value, so we can switch to Sydney later.
- **No AWS WAF on CloudFront.** It isn't available for project accounts, so we rely on app-level rate limits.
- **Spend limit $20/month on the project.** As spending nears the limit, AWS applies policies that block EC2 starts, Bedrock and more, and then pauses the project. Fixed infrastructure alone is about $23/month, so **the limit must be raised to at least $50** in AWS Settings → Billing before launch.
- IAM roles under `role/managed/*` are AWS's and can't be changed. Our own roles are fine.

---

## 1. What the backend has to support (from the design)

| Area | Screens | Backend needs |
|---|---|---|
| Auth | 01, 10, 28 | Email+password, Google sign-in, 6-digit email verification, reset link (30 min expiry), delete account |
| Onboarding | 02 | Goal (Simple / Standard / Exam level), daily minutes, reminder opt-in, first upload |
| Upload & structure | 03, 04, 14 | Large PDF upload (600+ pages), password-protected PDFs (password used once, never stored), detect chapters from bookmarks or contents page, map printed page numbers to PDF pages, manual chapter marking, equal split fallback, OCR for scanned PDFs (Pro) |
| Course generation | 04, 05 | Build chapter 1 right away; build later chapters only when the learner reaches them. Email when chapter 1 is ready |
| Learning loop (8 steps) | 05, 06, 18, 19, 07 | Chapter map, pre-question, sections with quick checks and key terms, explain-it-back grading, chapter quiz (MCQ and free text graded for the idea), missed questions turn into flashcards |
| Tutor | 06 | Chat that answers only from this book, with page citations |
| Review | 08 | FSRS spaced repetition across all books, target recall setting (85/90/95%) |
| Final test | 20 | 40-question cumulative test weighted to weak chapters, timed, pass mark 75%, certificate |
| Progress | 21 | Time studied, streak, cards reviewed, quiz average, weak spots |
| Notes | 22, 23 | Highlights and notes per page, source page viewer, "report a wrong citation" |
| Search | 25 | Search across books, notes and cards |
| Notifications | 24 | Inbox plus email preferences (review reminder, chapter ready, streak at risk, billing, product) |
| Plans & usage | 09, 12 | Plan limits, usage meters (books, storage, tutor messages), upgrade prompt |
| Teams | 26 | Org, seats, invite links, assigned chapters, learner progress, CSV export (phase 2) |
| Data export | 09 | Flashcards to CSV/Anki, full data export |

---

## 2. Architecture

```
                         ┌─────────────────────────────── AWS (ap-southeast-2) ──────────────────────────────┐
 Browser / mobile web    │                                                                                │
        │                │   CloudFront (HTTPS, *.cloudfront.net to start)                               │
        └───────────────►│     ├── /*      → S3 bucket "web" (React build, private, Origin Access Control) │
                         │     └── /api/*  → EC2 origin (HTTP, locked to CloudFront prefix list           │
                         │                    + secret origin header)                                     │
                         │                                                                                │
                         │   EC2 t4g.small (ARM, Amazon Linux 2023, Docker Compose, no SSH, SSM only)     │
                         │     ├── api      FastAPI (Python 3.12)                                          │
                         │     ├── worker   PDF pipeline + AI generation jobs + reminder cron             │
                         │     └── postgres 16, local (data on encrypted EBS gp3, daily snapshots)        │
                         │            │                                                                    │
                         │            ├── S3 "uploads" (private, SSE, presigned PUT/GET only)              │
                         │            ├── Bedrock Runtime (us-east-1): Nova 2 Lite, Titan Embeddings V2    │
                         │            ├── S3 Vectors "chunks" index (1024-d cosine embeddings)          │
                         │            ├── Cognito User Pool (auth, Google IdP, verification codes)         │
                         │            ├── SES (transactional email)                                        │
                         │            └── SSM Parameter Store / Secrets Manager (secrets)                  │
                         │   CloudWatch logs + alarms, AWS Budgets alerts                                 │
                         └────────────────────────────────────────────────────────────────────────────────┘
```

### Why this shape

- **One EC2 instance, not Lambda/ECS/RDS.** Cheapest thing that handles long PDF jobs (OCR on 600 pages can take many minutes) and keeps Postgres local. t4g.small is ARM, 2 vCPU, 2 GB RAM, $15.48/month on demand in Sydney, and covered by sign-up credits. Lambda would be cheaper at zero traffic but awkward for long OCR jobs and native PDF libraries. Postgres stays on this instance by design: no RDS or Aurora.
- **CloudFront in front of everything.** One URL for the SPA and the API (no CORS), free TLS on `xxxx.cloudfront.net`, caching for static files. Custom domain later with an ACM certificate.
- **Postgres job queue (`SELECT … FOR UPDATE SKIP LOCKED`) instead of SQS.** One less service on a single box. Swap to SQS when the worker moves to its own machine.
- **Cognito for auth.** It already does everything screens 01 and 10 show (sign up, Google, 6-digit verification code, reset link) and is free at our scale. We don't store passwords.
- **S3 Vectors for embeddings.** Pay-per-use (storage plus queries), no server to run, and it keeps vector search off the 2 GB instance. One index `chunks`, keys `{book_id}:{chunk_n}`, filterable metadata `user_id`, `book_id`, `chapter_n`, `pdf_page`. Chunk text stays in Postgres; every query filters by `user_id` and `book_id`. OpenSearch Serverless (from ~$175/month) isn't needed.

### Security pattern

1. **Root account:** MFA on, no root access keys long-term. Root is used only to create an admin identity, then locked away.
2. **Admin access for CLI:** IAM Identity Center user (or, simpler, an IAM user `lectern-admin` with MFA) and short-lived credentials. **I recommend you don't hand me root keys.** Give me an admin profile; I'll scope it down once the stack exists.
3. **EC2 has no SSH and no key pair.** Access via SSM Session Manager. Instance role allows only: its own S3 buckets, `bedrock:InvokeModel` on the two model ARNs, `cognito-idp` admin calls on our pool, `ses:SendEmail` from our identity, reading `/lectern/*` parameters, CloudWatch logs.
4. **Network:** Security group inbound only on port 80 from the AWS-managed CloudFront origin-facing prefix list. CloudFront adds a secret `X-Origin-Verify` header; the API rejects requests without it. No direct public access to the API or Postgres. IMDSv2 required.
5. **S3:** Block Public Access on every bucket, SSE-S3 encryption, web bucket readable only through CloudFront OAC, uploads only through 15-minute presigned URLs scoped to `users/{user_id}/…`.
6. **Data:** EBS encrypted. Postgres listens only on the Docker network. Daily EBS snapshots (Data Lifecycle Manager, keep 7). PDF passwords are used in memory and never logged or stored.
7. **App-level:** Every query is scoped by `user_id` (tenant isolation tested). Cognito JWTs verified against the pool JWKS. Rate limits per user on tutor and upload endpoints. Uploaded PDFs are parsed in the worker with size/page caps and a timeout.
8. **Guardrails on spend:** AWS Budgets alerts at $10 / $25 / $50, a CloudWatch alarm on Bedrock invocation count, and per-user monthly token caps in the app.
9. **Logging:** CloudTrail on (management events, free), CloudWatch Logs for containers with 14-day retention.

---

## 3. Pipelines

### 3.1 Upload → structure (screens 04, 14)

1. `POST /api/books` → creates `book` row, returns presigned S3 PUT URL. Browser uploads straight to S3 (no file through the API).
2. `POST /api/books/{id}/uploaded` → enqueue `ingest_book`.
3. Worker `ingest_book`:
   - Open with **PyMuPDF**. If encrypted → status `needs_password` (screen 14). The user submits the password once; the worker decrypts in memory and saves an unencrypted copy to S3.
   - Text check: if most pages have no text layer → `scanned`. Free plan: reject with the upgrade message. Pro: OCR with **OCRmyPDF/Tesseract** on the box (zero cost; Textract at ~$1.50 per 1,000 pages is the upgrade if quality is poor).
   - **Structure:** (a) PDF outline/bookmarks, (b) else parse the contents page with Nova 2 Lite (send only the first ~20 pages of text), (c) else status `no_structure` → manual marking or equal split (screen 14).
   - **Page mapping:** PDF page labels if present, else detect printed page numbers in headers/footers to compute the offset ("Printed page 1 = PDF page 19").
   - Flag items to check (e.g. a last chapter with no bookmark end).
   - Store per-page text in `pages`, split into ~500-token chunks with page numbers, embed with Titan V2 → vectors in S3 Vectors, text in Postgres `chunks`.
4. User confirms or edits chapters → enqueue `build_chapter(1)`.

### 3.2 Chapter build (lazy)

`build_chapter(book, n)` runs when the book is confirmed (chapter 1) and when a learner opens chapter n's map (pre-builds n+1 in the background so it's ready).

One Nova 2 Lite call per step, structured JSON output, using only that chapter's text (a chapter is usually 10k–40k tokens; Nova 2 Lite takes 1M):

1. Chapter map: sections with page ranges, key ideas, difficulty, time estimate.
2. Per section, for each level (Simple / Standard / Exam — Exam is Pro): lesson text, key terms with page refs, 1–2 quick checks. Generate the user's default level first; other levels on demand and cached.
3. Chapter quiz: 10 questions (MCQ + short answer), each tied to a section and a page.
4. Explain-it-back prompt with 3 key points it grades against.
5. Seed flashcards for key terms.

Generated content is shared per book+chapter+level, so it isn't regenerated per user unless the book is private (all books are private for now; the shared cache matters for Teams).

Every citation must point to a page we actually have in `pages`; the worker checks this and drops citations it can't match.

### 3.3 Interactive calls

| Call | What goes to the model | Approx tokens |
|---|---|---|
| Tutor message | system rules ("answer only from the excerpts, cite pages, say so if it isn't in the book") + top 6 chunks from hybrid search (S3 Vectors similarity + Postgres full-text, merged) in this book, current chapter boosted + last 6 turns | ~4k in / 400 out |
| Explain-it-back grading | key points + user text + relevant chunk | ~2k in / 300 out |
| Free-text quiz grading | question, model answer, user answer | ~1k in / 150 out |
| Pre-question plan | chapter map + user's self-rating | ~1.5k in / 200 out |

Tutor replies stream over Server-Sent Events.

### 3.4 Review and progress

- **FSRS** (`fsrs` Python package) per card, target recall from settings. Missed quiz questions become cards automatically.
- Daily worker cron: due-card counts, reminder emails at the user's chosen time, streak-at-risk emails.
- `study_sessions` table records minutes per day per book for screen 21.

---

## 4. Data model (main tables)

```
users            id, cognito_sub, email, name, plan_id, limits_exempt, level_default, daily_minutes,
                 target_recall, reminder_time, tz, created_at, deleted_at
plans            id ('free','pro','teams','internal'), name, price_month, price_year, limits jsonb
usage_monthly    user_id, month, books_added, tutor_messages, tokens_in, tokens_out, storage_bytes
books            id, user_id, title, s3_key, pages, bytes, kind(text|scanned), status, page_offset, error
chapters         id, book_id, n, title, pdf_start, pdf_end, status(pending|building|ready|failed), check_note
sections         id, chapter_id, n, title, pdf_start, pdf_end
lessons          id, section_id, level, body jsonb, key_terms jsonb, quick_checks jsonb, model, created_at
pages            book_id, pdf_page, printed_label, text
chunks           id, book_id, chapter_id, chunk_n, pdf_page, text, tsv tsvector   (vector lives in S3 Vectors under key book_id:chunk_n)
quizzes          id, chapter_id | book_id (final), questions jsonb
attempts         id, user_id, quiz_id, answers jsonb, score, started_at, finished_at
cards            id, user_id, book_id, chapter_id, front, back, pdf_page, source, fsrs_state jsonb, due_at
reviews          id, card_id, rating, reviewed_at
chat_threads / chat_messages   with citations jsonb
notes            id, user_id, book_id, pdf_page, quote, note, term
progress         user_id, section_id, state, step
study_sessions   user_id, book_id, date, minutes
notifications    id, user_id, type, title, body, read_at
notification_prefs  user_id, type, email, push
jobs             id, type, payload, status, attempts, run_after, locked_at, error
orgs / org_members / assignments   (Teams, phase 2)
```

Migrations with Alembic. Plans and limits live in the database so pricing changes don't need a deploy.

---

## 5. Plans and limits (placeholder defaults)

Prices are placeholders until payments are wired up. All shown in USD; INR pricing can be added per country later (checkout already shows India/UPI).

| | Free | Pro | Teams | Internal (test) |
|---|---|---|---|---|
| Price | $0 | $9.99/mo or $89/yr | $8/seat/mo (min 5) | — |
| Books | 1 | Unlimited (fair use: 10 new books/mo) | Unlimited + shared library | Unlimited |
| Max PDF | 100 MB, 800 pages | 500 MB, 2,000 pages | same as Pro | 500 MB, 2,000 pages |
| Scanned PDFs (OCR) | No | Yes | Yes | Yes |
| Levels | Simple, Standard | + Exam | + Exam | All |
| Final test | No | Yes | Yes | Yes |
| Tutor messages | 50 / month | 1,000 / month | 1,000 / seat / month | No limit |
| Storage | 200 MB | 5 GB | 5 GB / seat | No limit |

The usage meters on screen 9 read straight from `usage_monthly` against `plans.limits`. Hitting a limit returns HTTP 402 with a code the frontend turns into screen 12.

### Test user

- Created in Cognito with `admin-create-user`, email pre-verified, password generated by the setup script.
- `plan_id = 'internal'`, `limits_exempt = true` → every limit check is skipped.
- Credentials are stored in SSM Parameter Store as a SecureString at `/lectern/test-user`, never in code or chat. Read them with:
  `aws ssm get-parameter --name /lectern/test-user --with-decryption --query Parameter.Value --output text`

---

## 6. Cost estimate

Nova 2 Lite prices confirmed from the AWS Pricing API (us-east-1, 2026-10-23), per 1M tokens:

| Nova 2 Lite tier | Input | Output | Cache read | Use for |
|---|---|---|---|---|
| Global cross-region (`global.amazon.nova-2-lite-v1:0`) | $0.30 | $2.50 | $0.075 | Tutor, grading (interactive) |
| US cross-region (`us.amazon.nova-2-lite-v1:0`) | $0.33 | $2.75 | $0.0825 | Only if data must stay in the US |
| Flex, global | $0.15 | $1.25 | $0.0375 | Background chapter builds (slower, half price) |
| Batch, global | $0.15 | $1.25 | — | Bulk jobs that can wait |

Cache writes are free, so the system prompt and chapter text get prompt-cached. Titan Embeddings V2 is about $0.02 per 1M tokens (not re-checked). With flex pricing for chapter builds, the per-chapter cost below roughly halves.

**Per user activity**

| Item | Estimate |
|---|---|
| Ingest a 640-page book (structure + embeddings) | ~$0.01 |
| Build one chapter at one level (~30k in / 10k out) | ~$0.035 |
| Full 18-chapter book at one level | ~$0.65 |
| Tutor message | ~$0.002 |
| Heavy Pro user/month (4 books started, 8 chapters each, 500 tutor msgs, grading) | ~$2.50 |

So $9.99 Pro leaves healthy margin. Free users cost about $0.10–$0.70 each, capped by the 1-book and 50-message limits.

**Fixed infrastructure per month (low traffic)**

| Item | Monthly |
|---|---|
| EC2 t4g.small on demand (Sydney) | $15.48 |
| EBS gp3 30 GB + snapshots | ~$3 |
| Public IPv4 address | ~$3.60 |
| CloudFront, S3, Cognito, SES, SSM at low volume | ~$0–2 (mostly free tiers) |
| **Total** | **~$23/month** before Bedrock usage |

New accounts get $100 in credits (up to $200 after onboarding tasks), which covers several months.

---

## 7. Account and plan choice (decision needed)

AWS now asks new accounts to pick a **Free plan** or **Paid plan** at sign-up. Both get the credits.

- **Free plan:** restricted to selected services, the account closes when credits run out or after 6 months, and there are reports of Bedrock quotas being denied on Free plan accounts.
- **Paid plan:** same credits, no service restrictions, billed only after credits are used.

**Recommendation: choose the Paid plan** and rely on the Budgets alerts in section 2 for cost control. A production app shouldn't sit on an account that closes itself.

---

## 7b. What changed during the build

- **Lessons are generated per section** (one call each, run 4 at a time) after a chapter-map call; quizzes use a strict schema with separate multiple-choice and short-answer lists so options and answers can't be omitted.
- **Lessons at other levels are built on demand** by a `build_lesson` job the first time someone switches level, then cached.
- **Tutor retrieval** merges S3 Vectors similarity and Postgres full-text results (reciprocal rank fusion), boosts the current chapter, and drops any citation the model gives for a page it wasn't shown.
- **Measured on OpenStax University Physics Vol. 1 (959 pages, 81 MB):** ingest 9 s, 17 chapters + 7 appendices from bookmarks, 1,802 chunks embedded in ~2 min, chapter 1 built in ~90 s for ~95k input / ~6k output tokens (≈ $0.02–0.04).
- **Email** (chapter ready, reminders) is in-app only until an SES sending domain exists. Cognito sends verification and reset codes itself (50/day limit).

## 8. Build order

| Phase | Work | Who |
|---|---|---|
| 0 | Create AWS account (email, password, card, phone check, root MFA), choose plan, create admin IAM user with MFA + access key, `aws configure --profile lectern` | **You** — I can't create accounts or enter card details or passwords |
| 1 | Done 2026-10-23: budget alerts, CloudTrail (Sydney), Bedrock tested in us-east-1, prices confirmed | Me via CLI |
| 2 | Infra as code (Terraform or CDK): VPC, SG, EC2 + role, S3 buckets, CloudFront + OAC, Cognito pool, SSM params, DLM snapshots | Me |
| 3 | Backend: FastAPI skeleton, Alembic schema, auth middleware, plans/limits, books upload, ingest worker | Me |
| 4 | Chapter build + lesson/quiz/flashcard generation, tutor with citations, grading, FSRS review | Me |
| 5 | Frontend: React + Vite + TypeScript, rebuilt from the design screens, deployed to S3/CloudFront | Me |
| 6 | Test user, smoke test the whole loop on a real textbook PDF via the CloudFront URL | Me, then you |
| Later | SES production access, Google sign-in (needs your Google Cloud OAuth client), payments, custom domain, Teams | Together |

### Repo layout

```
StudyPlannerAI/
  infra/            terraform (or cdk)
  backend/
    app/            api routes, auth, models, services (bedrock, s3, fsrs, limits)
    worker/         jobs: ingest_book, build_chapter, reminders
    migrations/
    tests/
    Dockerfile
  frontend/         React + Vite + TS
  deploy/           docker-compose.yml, ssm deploy script
  docs/
```

Deploys: build ARM images in CI or locally, push to ECR, `aws ssm send-command` to pull and restart on the instance. No SSH anywhere.
