# Auth hardening — Google OAuth + custom SMTP (human-applied dashboard config)

The code side (P3.5) ships the Google button on /login; everything below is
Supabase/Google/Resend dashboard configuration the operator applies. No app
code depends on WHEN this lands — the email door keeps working throughout.

## 1. Google OAuth (primary browser door)

The button calls `supabase.auth.signInWithOAuth({provider: "google"})`, lands
on `/auth/callback` with a GoTrue session, and the existing
`POST /auth/email/exchange` mints the app session. Identity parity is by
construction: the API keys on the GoTrue user's (email, auth_user_id), and a
Google user is the same GoTrue user shape as a magic-link user — a user who
used the email door earlier and now signs in with Google (same address, same
GoTrue user) resolves to the same account.

### Google Cloud Console

1. Console → APIs & Services → OAuth consent screen: External, app name
   "Nashr", support email, domain `nashr.com.uz`. Publish (not Testing —
   Testing caps at 100 users and expires tokens weekly).
2. Credentials → Create credentials → OAuth client ID → Web application:
   - Authorized JavaScript origins: `https://kzxjtkzetpuqemmdnrfe.supabase.co`
   - Authorized redirect URIs:
     `https://kzxjtkzetpuqemmdnrfe.supabase.co/auth/v1/callback`
3. Copy Client ID + Client secret.

### Supabase dashboard

1. Authentication → Providers → Google: Enable, paste Client ID + secret.
2. Authentication → URL Configuration:
   - Site URL: `https://nashr.com.uz`
   - Additional Redirect URLs: `https://nashr.com.uz/auth/callback`,
     `https://www.nashr.com.uz/auth/callback`, and (while testing)
     `http://localhost:3000/auth/callback` plus the Vercel preview origin.
     Without the exact entry, OAuth redirects fall back to Site URL and the
     callback page shows "havola yaroqsiz".

## 2. Custom SMTP via Resend (magic-link deliverability)

Default Supabase SMTP is heavily rate-limited (~2 emails/hour) and lands in
spam. Cut over to Resend before any real user cohort.

### Resend

1. resend.com → Domains → Add Domain → `nashr.com.uz` (region closest: EU).
2. Resend shows 3 DNS records; add them at the `nashr.com.uz` DNS host:

   | Type | Name | Value |
   | --- | --- | --- |
   | TXT | `resend._domainkey` | DKIM key Resend displays (long `p=...` value) |
   | TXT | `send` (or root, per Resend UI) | `v=spf1 include:amazonses.com ~all` |
   | MX | `send` | `feedback-smtp.<region>.amazonses.com` priority 10 |

   Exact values come from the Resend dashboard — copy them verbatim, then
   wait for "Verified" (minutes to an hour).
3. API Keys → Create ("supabase-smtp", Sending access only). Copy once.

### Supabase dashboard fields

Project Settings → Authentication → SMTP Settings → Enable custom SMTP:

| Field | Value |
| --- | --- |
| Sender email | `login@nashr.com.uz` |
| Sender name | `Nashr` |
| Host | `smtp.resend.com` |
| Port | `465` |
| Username | `resend` |
| Password | the Resend API key |
| Minimum interval | leave default |

Then Authentication → Rate Limits: raise "emails per hour" from the 2/h
default to something real (30/h is plenty pre-launch).

### Verify

Send a magic link to a Gmail address: it should arrive in the inbox (not
spam) from `login@nashr.com.uz` within seconds; "show original" should show
`SPF: PASS` and `DKIM: PASS` for nashr.com.uz.
