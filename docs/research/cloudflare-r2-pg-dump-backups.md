# Cloudflare R2 free tier for pg_dump backups

Date: 2026-07-31

## Question

Against Cloudflare R2 primary docs, confirm free-tier storage/ops/egress, S3 Compatibility API auth shape, and whether retain-7 daily logical dumps of a tens-to-low-hundreds-MB Postgres database fit indefinitely at $0. Note any gotchas for GitHub Actions uploads.

## Conclusion

**Yes — retain-7 daily `pg_dump` objects of a tens-to-low-hundreds-MB Postgres DB fit indefinitely inside R2’s Standard free tier at $0**, with large headroom on storage and Class A/B ops, and with **egress free** when reading/writing via the S3 API (the path Actions will use).

Plan shape that stays at $0 under published limits:

1. Complete the R2 subscription checkout (required before API tokens; no upfront charge if usage stays in free tier).
2. Use **Standard** storage only (free tier does **not** apply to Infrequent Access).
3. Auth with R2 Access Key ID + Secret Access Key against `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, `region_name="auto"`.
4. Scope an **Object Read & Write** token to the backup bucket; store credentials in GitHub Actions secrets; always pass the custom endpoint (AWS default endpoints will not work).
5. Keep ≤7 daily dump objects (lifecycle expire at 7–8 days, or delete-then-put in the job). Deletes are free.

At ~100 MB/day × 7 ≈ **0.7 GB-month** retained; even ~300 MB/day × 7 ≈ **2.1 GB-month** — both well under **10 GB-month**. Daily Class A usage is on the order of tens of requests/month, not millions.

## Free tier (Standard storage)

Rechecked **2026-07-31** from [R2 Pricing](https://developers.cloudflare.com/r2/pricing/).

| Meter | Free amount / month |
| --- | ---: |
| Storage | **10 GB-month** |
| Class A operations | **1 million** requests |
| Class B operations | **10 million** requests |
| Egress (data transfer to Internet) | **Free** (see footnote) |

Published paid Standard rates beyond free: storage **$0.015**/GB-month; Class A **$4.50**/million; Class B **$0.36**/million; egress still free.

### Egress footnote (primary)

Cloudflare states there are **no charges for egress bandwidth for any storage class**, and footnote 1 clarifies:

> Egressing directly from R2, including via the Workers API, S3 API, and `r2.dev` domains does not incur data transfer (egress) charges and is free. If you connect other metered services to an R2 bucket, you may be charged by those services.

For Actions `PutObject` / occasional restore `GetObject` via S3 API: **$0 egress**.

### Caveats that matter for $0

- Free tier applies **only to Standard storage**, not Infrequent Access ([pricing free-tier caution](https://developers.cloudflare.com/r2/pricing/#free-tier)).
- Usage is monthly; storage is **GB-month** averaged from daily peak storage over a 30-day period.
- Cloudflare **rounds up** billable units when you exceed free amounts (e.g. 1.1 GB-month → 2 GB-month billable beyond free). Stay under free caps and this does not bite.
- Unauthorized requests (HTTP 401) are **not** charged.

### Class A / B / free ops relevant to backups

From [pricing](https://developers.cloudflare.com/r2/pricing/):

| Class | Ops used by a typical backup job |
| --- | --- |
| **A** (mutate/list) | `PutObject`, `ListObjects` / `ListObjectsV2`, `CreateMultipartUpload`, `UploadPart`, `CompleteMultipartUpload`, `PutBucketLifecycleConfiguration`, … |
| **B** (read) | `GetObject`, `HeadObject`, `HeadBucket`, … |
| **Free** | `DeleteObject`, `DeleteBucket`, `AbortMultipartUpload` |

## Fit math: retain-7 daily logical dumps

Workload assumption from the map (#53): tens-to-low-hundreds of MB per logical dump; keep the last 7 daily objects.

| Dump size (steady) | Retained storage (7 objects) | vs 10 GB-month free |
| ---: | ---: | --- |
| 50 MB | ~0.35 GB | ~3.5% of free |
| 100 MB | ~0.7 GB | ~7% of free |
| 300 MB | ~2.1 GB | ~21% of free |
| 1 GB | ~7 GB | ~70% of free — still under |

**Headroom note:** Neon Free Postgres is capped at **0.5 GB** storage in the hosting redesign map, so a full logical dump of that DB cannot honestly grow past that envelope without a larger paid Neon plan. R2 free storage is not the binding constraint.

### Ops envelope (daily job, single-part upload)

Conservative monthly Class A budget if the job does roughly:

- 1× `PutObject` (new dump)
- 1× `ListObjectsV2` (inventory / prune)
- N× `DeleteObject` for objects older than retain-7 (**free**, not Class A)

≈ **~60 Class A / month** at one run/day — vs **1,000,000** free. Class B only if verifying downloads. Multipart is unnecessary below 5 GiB single-part max; if used, each `UploadPart` + create/complete adds Class A counts, still trivial at this size.

**Verdict:** indefinitely **$0** on R2 for this backup pattern, provided Standard class, retain-7 (or similar), and no unrelated high-volume traffic on the same account free allotment.

## S3 Compatibility API auth shape

Primary sources: [Authentication](https://developers.cloudflare.com/r2/api/tokens/), [Get started — S3](https://developers.cloudflare.com/r2/get-started/s3/), [boto3](https://developers.cloudflare.com/r2/examples/aws/boto3/), [aws CLI](https://developers.cloudflare.com/r2/examples/aws/aws-cli/), [S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/).

### Prerequisites

1. Cloudflare account with an **R2 subscription** via dashboard checkout ([get started](https://developers.cloudflare.com/r2/get-started/)): “R2 is free to get started with included free monthly usage. You are billed for your usage on a monthly basis.”
2. **You must purchase/subscribe to R2 before you can generate an API token** ([tokens](https://developers.cloudflare.com/r2/api/tokens/)).

### Credentials

| Concept | R2 value |
| --- | --- |
| Access Key ID | Issued when creating R2 API token (sometimes called Client ID) |
| Secret Access Key | Issued once at creation (Client Secret); cannot view again |
| Endpoint | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| Region | `auto` (required by SDKs; unused by R2). Empty and `us-east-1` alias to `auto` |
| Jurisdiction endpoints | EU: `https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com`; FedRAMP: `…fedramp.r2.cloudflarestorage.com` |

Token kinds:

- **Account API token** — account-scoped; Super Administrator to create/view; valid until revoked.
- **User API token** — tied to the Cloudflare user; inactive if user removed from account.

Recommended permission for Actions backup upload: **Object Read & Write**, scoped to **specific buckets only** ([get started S3](https://developers.cloudflare.com/r2/get-started/s3/)). Admin permissions are unnecessary for put/list/get/delete objects.

### boto3 shape (canonical for Python Actions steps)

```python
import boto3

s3 = boto3.client(
    service_name="s3",
    endpoint_url="https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
    aws_access_key_id="<ACCESS_KEY_ID>",
    aws_secret_access_key="<SECRET_ACCESS_KEY>",
    region_name="auto",
)
```

`PutObject` / `upload_file` / `upload_fileobj`, `ListObjectsV2`, `GetObject`, and `DeleteObject` are implemented on the S3 compatibility surface ([S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/)).

### aws CLI shape

```bash
aws configure   # Access Key ID, Secret, region=auto, output=json
aws s3api put-object \
  --endpoint-url https://<ACCOUNT_ID>.r2.cloudflarestorage.com \
  --bucket <BUCKET> --key dumps/$(date -u +%F).dump --body backup.dump
```

## GitHub Actions upload gotchas (R2-side)

These are the failure modes that follow from Cloudflare’s docs (not third-party blog posts):

1. **Custom endpoint is mandatory.** Point SDKs/CLI at `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`. Omitting `--endpoint-url` / `endpoint_url` talks to AWS S3 and fails auth or wrong-account.
2. **Subscribe before minting keys.** Dashboard checkout is required even when staying in free usage; tokens are unavailable until R2 is enabled on the account.
3. **Secret Access Key is shown once.** Capture into GitHub Actions secrets immediately (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, plus account id / bucket / endpoint).
4. **Region `auto`.** boto3/aws CLI require a region string; use `auto` per Cloudflare examples.
5. **Prefer Standard storage class.** Do not set Infrequent Access / `STANDARD_IA` for free-tier backups (no free allotment; retrieval fees; 30-day minimum duration).
6. **Single-part size limit is 5 GiB** ([limits](https://developers.cloudflare.com/r2/platform/limits/)); dump sizes here are fine as one `PutObject`. Multipart is available up to ~5 TiB but multiplies Class A ops and needs abort hygiene.
7. **Incomplete multipart uploads** get a **default lifecycle abort after 7 days** ([object lifecycles](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)). Prefer single-part for these dumps.
8. **Retain-7 enforcement:** either delete old keys in the workflow (`DeleteObject` is free) or set a bucket lifecycle Expiration rule (e.g. expire after 8 days). Lifecycle management needs a token with **Workers R2 Storage Write** (account-level), not just Object Read & Write — so configure lifecycle once in the dashboard/Wrangler with a privileged token, and keep the Actions token object-scoped.
9. **Scope tokens to the backup bucket.** Object Read & Write + specific buckets reduces blast radius if Actions secrets leak.
10. **Jurisdiction.** If the bucket was created in EU/FedRAMP jurisdiction, the Actions client must use the jurisdiction-specific endpoint, not the default account endpoint.
11. **Egress is free on restore via S3 API**; connecting other metered Cloudflare/third-party products to the bucket can still bill those products (pricing footnote).
12. **Do not rely on `r2.dev` for production restore tooling** — managed public `r2.dev` access is for testing and is rate-limited ([limits](https://developers.cloudflare.com/r2/platform/limits/)). Private bucket + signed S3 API credentials (or presigned URLs) is the backup path.

Actions-minutes / Neon dump generation are outside R2’s meters; they do not change the R2 $0 conclusion above.

## Limits that bound the design (non-pricing)

From [R2 limits](https://developers.cloudflare.com/r2/platform/limits/) (same content also under `/r2/reference/limits/`):

| Limit | Value |
| --- | --- |
| Object size | 5 TiB (multipart) |
| Maximum upload size | 5 GiB single-part / ~4.995 TiB multipart |
| Objects / bucket | Unlimited |
| Storage / bucket | Unlimited (billing meters still apply) |
| Concurrent writes to same key | 1 per second |

## Sources (primary)

- R2 pricing + free tier + egress footnote: https://developers.cloudflare.com/r2/pricing/
- Get started (subscription / free monthly usage): https://developers.cloudflare.com/r2/get-started/
- Get started — S3 credentials + endpoint: https://developers.cloudflare.com/r2/get-started/s3/
- Authentication / API tokens / permissions / jurisdiction endpoints: https://developers.cloudflare.com/r2/api/tokens/
- S3 API compatibility (endpoint, region `auto`, Put/Get/List/Delete): https://developers.cloudflare.com/r2/api/s3/api/
- boto3 example: https://developers.cloudflare.com/r2/examples/aws/boto3/
- aws CLI example: https://developers.cloudflare.com/r2/examples/aws/aws-cli/
- Object lifecycles (expire + multipart abort): https://developers.cloudflare.com/r2/buckets/object-lifecycles/
- Limits: https://developers.cloudflare.com/r2/platform/limits/

## Ambiguities / non-claims

- Exact Neon logical-dump byte size after PostGIS load is not measured in this ticket; the conclusion uses the map’s tens-to-low-hundreds-MB envelope and Neon’s 0.5 GB free DB cap as an upper bound on dump growth under the $0 redesign.
- Cloudflare does not publish a separate “GitHub Actions” guide; Actions gotchas above are derived from the S3 auth/endpoint/limits docs applied to a CI runner.
- Account-wide free-tier sharing: free amounts are per Cloudflare billing account. Unrelated R2 usage on the same account counts against the same 10 GB-month / 1M Class A pool.
