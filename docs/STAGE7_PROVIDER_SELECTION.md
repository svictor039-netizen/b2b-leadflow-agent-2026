# Stage 7 — Provider Selection Guide (no vendor chosen)

This document compares **requirements** for a future live email provider. **No provider is selected** — the owner decides in Stage 7B.

## Evaluation criteria

| Criterion | Why it matters |
|---|---|
| API idempotency | At-most-once send; safe retries on timeout |
| Sandbox / test mode | Dry validation without production delivery |
| Verified sender / domain | SPF/DKIM alignment; bounces routed correctly |
| Webhook signing | Verify bounce/complaint/delivery events |
| Bounce / complaint events | Feed Stage 6 suppression automatically |
| Unsubscribe handling | Legal compliance; list-unsubscribe or provider UI |
| Rate limits | Match pilot daily/per-minute caps |
| EU data processing | DPA, data residency if required |
| Auditability | Message IDs, event logs, export |
| API key rotation | Rotate without downtime |
| Pricing | **Check current pricing at selection time** — not documented here |
| SDK / dependency | Operational complexity vs raw HTTP |
| Operational complexity | DNS setup, warmup, support |

## Providers commonly considered (not ranked)

SendGrid, Amazon SES, Mailgun, Postmark, Resend, Brevo — each must be evaluated against the table above at decision time.

## Stage 7B — Data required from owner

Before enabling live pilot, collect:

| Item | Notes |
|---|---|
| Provider name | Owner decision — not auto-selected |
| Verified sender domain | DNS records configured by owner |
| Sender email | From address on verified domain |
| Pilot recipient | One allowlisted address after explicit confirmation |
| Daily limit | > 0, within provider quota |
| Per-minute rate limit | > 0, conservative for canary |
| Jurisdiction / legal basis | GDPR, CAN-SPAM, local rules |
| Unsubscribe footer | Required content in message template |
| Privacy / contact information | Company details in footer |

## Secrets policy

- API keys, SMTP passwords, tokens → **environment / secret manager only**.
- Never commit to git.
- Config endpoints expose `present` / `missing` — never raw values.
- Placeholder values (`changeme`, `your-api-key`) treated as not configured.

## Stage 7A status

Infrastructure is ready for provider wiring. `DisabledLiveEmailProvider` returns `LIVE_PROVIDER_NOT_CONFIGURED`. Readiness always shows live blockers until owner completes Stage 7B checklist.
