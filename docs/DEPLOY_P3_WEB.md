# P3 deploy prerequisites (human-run)

What the P3 web build needs from the operator before the phase gate. The
code is live once the VM pulls the branch and Vercel deploys `packages/web`;
these are the pieces neither can do for itself.

## 1. Migration

Apply `supabase/migrations/009_share_tokens.sql` (prerequisites 001–008, in
order). Adds the nullable unique `projects.share_token` column.

## 2. R2 bucket CORS (REQUIRED for browser uploads)

The browser PUTs source files directly to R2 with a presigned URL — a
cross-origin request the bucket must allow. In the Cloudflare dashboard
(R2 → bucket → Settings → CORS policy), or via API, set:

```json
[
  {
    "AllowedOrigins": [
      "https://nashr.com.uz",
      "https://www.nashr.com.uz",
      "http://localhost:3000"
    ],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["Content-Type"],
    "MaxAgeSeconds": 3600
  }
]
```

Without this, every web upload fails in the browser at the PUT step (the
presign itself will still succeed). Signed GET URLs (deck viewer, downloads)
are plain navigations/iframe loads and need no CORS.

## 3. Vercel project (packages/web)

Root directory: `packages/web`. Build command/output: Next.js defaults.
Environment variables (all public by design — the web tier must never hold
the service key):

| Var | Value |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | project REST URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon key |
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.nashr.com.uz` |

NOTE: the variable is `NEXT_PUBLIC_API_BASE_URL` (the name the existing code
reads), not `NEXT_PUBLIC_API_URL`.

## 4. API CORS

`WEB_CORS_ORIGINS` on the VM must include the deployed web origins
(`https://nashr.com.uz,https://www.nashr.com.uz` — plus the Vercel preview
origin if the gate runs there).
