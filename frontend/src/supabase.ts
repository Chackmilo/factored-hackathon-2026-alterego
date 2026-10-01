import { createClient } from '@supabase/supabase-js'

// Supabase Auth signs people in when the build carries the project URL and its publishable key
// (frontend/.env.local, or the deploy's build variables). Without them the app stays in local mode:
// the persona picker of the local issuer, which only answers when the API runs in development or test.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined

export const supabase =
  url && publishableKey
    ? createClient(url, publishableKey, {
        auth: {
          storage: window.sessionStorage, // closing the tab ends the session, as in local mode
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: false, // no magic links or OAuth redirects
        },
      })
    : null
