1. Install (browsers are already cached, do not run `playwright install`): `cd scripts/webshots && npm install`
2. Start the dev server against the stubs, from `packages/web`: `NEXT_PUBLIC_SUPABASE_URL=https://stub.supabase.co NEXT_PUBLIC_SUPABASE_ANON_KEY=stub-anon NEXT_PUBLIC_API_BASE_URL=https://api.stub.local npx next dev`
3. Run (from `scripts/webshots`, PNGs land in `review/p36_shots/`): `node shots.mjs` then `node journey.mjs`
