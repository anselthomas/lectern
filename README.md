# Lectern

Turn any book into a course you actually finish. Upload a PDF; Lectern finds the chapters, teaches them one at a time in plain words, checks what you kept with quizzes and explain-it-back prompts, and brings back what you missed as spaced-repetition flashcards. Every answer is cited to the page.

> Status: working beta at https://d1c6wdw7xblc4l.cloudfront.net. Payments are not switched on yet.

## How it works

1. **Upload** a textbook, manual or scanned PDF. It goes straight to S3; the book is never sent to a model all at once.
2. **Confirm the chapters.** Lectern reads the bookmarks or contents page, maps printed page numbers to PDF pages, and lets you fix anything.
3. **Learn one chapter at a time.** Chapter 1 is built right away; later chapters are built when you reach them.

Each chapter runs the same loop: chapter map → pre-question → short sections with quick checks → explain it back → chapter quiz → missed ideas become flashcards (FSRS) → review → final test.

## Architecture

```
Browser ──► CloudFront ──┬── /*      → S3 (React app, private via Origin Access Control)
                         └── /api/*  → EC2 t4g.small (Sydney)
                                         ├── FastAPI (api)
                                         ├── worker (PDF ingest, chapter builds, reminders)
                                         └── Postgres 16 (local, encrypted EBS, daily snapshots)
                                               │
                    Amazon Bedrock ◄───────────┤  Nova 2 Lite (lessons, quizzes, tutor, grading)
                                               │  Titan Text Embeddings V2
                    S3 Vectors ◄───────────────┤  chunk embeddings for page-cited retrieval
                    Cognito ◄──────────────────┤  sign-up, email codes, password reset
                    S3 ◄───────────────────────┘  uploaded PDFs (presigned URLs only)
```

Key choices:

- **One EC2 instance with local Postgres.** No RDS or Aurora. Cheapest setup that handles long OCR and PDF jobs.
- **S3 Vectors for embeddings.** Pay-per-use vector search; chunk text and full-text search stay in Postgres.
- **Nova 2 Lite** via the global inference profile (about $0.30 / $2.50 per 1M input / output tokens). Background chapter builds use the flex tier at half price.

Full design, data model, pipelines and cost estimates: [docs/architecture-plan.md](docs/architecture-plan.md).

## Security

- The server has no SSH and no key pair. Admin access goes through AWS Systems Manager Session Manager.
- The server accepts HTTP only from CloudFront's origin-facing IP ranges, and the API also checks a secret header that CloudFront adds. Direct requests to the server's IP are dropped.
- All buckets block public access and are encrypted; uploads and downloads use short-lived presigned URLs.
- The instance role is least-privilege: only its own buckets, vector index, two Bedrock models, its Cognito pool, and `/lectern/*` parameters.
- Secrets live in SSM Parameter Store (SecureString), never in this repo.
- CloudTrail logs all account activity; budget alerts and a project spend limit cap costs.

## Repository layout

```
infra/        CloudFormation template for all AWS resources (lectern.yaml)
docs/         Architecture and pipeline plan
backend/      FastAPI API (app/), background worker (app/worker.py), end-to-end QA (tests/qa_api.py)
frontend/     React + Vite + TypeScript app
deploy/       docker-compose, server deploy, web deploy, test-user and SSM helper scripts
```

## Deploying the infrastructure

Requires an AWS CLI profile with admin rights. The stack lives in `ap-southeast-2`; Bedrock is called in `us-east-1`.

```bash
# one-time: shared secret between CloudFront and the server
aws ssm put-parameter --name /lectern/origin-verify --type SecureString \
  --value "$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" --region ap-southeast-2

aws cloudformation deploy --stack-name lectern-core --template-file infra/lectern.yaml \
  --capabilities CAPABILITY_NAMED_IAM --region ap-southeast-2 \
  --parameter-overrides OriginVerifySecret="$(aws ssm get-parameter --name /lectern/origin-verify \
    --with-decryption --query Parameter.Value --output text --region ap-southeast-2)"
```

## Deploying the app

```bash
bash deploy/run-on-host.sh deploy/deploy.sh   # server: pull main, rebuild, restart (via SSM)
bash deploy/deploy-web.sh                     # frontend: build and publish to S3 + CloudFront
bash deploy/create-test-user.sh EMAIL         # internal QA account; password stored in SSM /lectern/test-user
```

End-to-end QA against the live stack (runs on the server as an existing user):

```bash
docker compose exec -T api python -m tests.qa_api EMAIL PDF_URL
```

## Roadmap

- [x] AWS account setup, budget alerts, CloudTrail
- [x] Core infrastructure: VPC, EC2, S3, S3 Vectors, CloudFront, Cognito, ECR, snapshots
- [x] Backend: schema, auth, plans and limits, upload and ingest pipeline
- [x] Chapter generation, tutor with citations, grading, FSRS review
- [x] Frontend from the design
- [x] Test user and end-to-end run on a real textbook (OpenStax University Physics Vol. 1, 959 pages)
- [ ] Later: payments, custom domain, Google sign-in, Teams

> Infra note: `infra/lectern.yaml` includes a fix to the instance's first-boot health placeholder that the running
> stack doesn't have yet. Deploying the template as-is stops and starts the app server (data is on its own volume and
> survives). IAM-only changes can be applied without touching the instance by change-setting the deployed template.
