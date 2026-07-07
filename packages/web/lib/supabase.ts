// Supabase browser client for RLS reads and Realtime subscriptions. The app
// session JWT (minted by the API, sub = users.id) is set as BOTH the request
// Authorization and the Realtime auth so both surfaces enforce the same
// identity — exactly what the P1 preflight proves end to end.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export function createRlsClient(appAccessToken: string): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY not configured");
  }
  const client = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: `Bearer ${appAccessToken}` } },
  });
  client.realtime.setAuth(appAccessToken);
  return client;
}

// Plain anon client for the email door (signInWithOtp); its GoTrue session is
// exchanged at the API for the app session and is NOT the app credential.
export function createAnonClient(): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY not configured");
  }
  return createClient(url, anonKey);
}
