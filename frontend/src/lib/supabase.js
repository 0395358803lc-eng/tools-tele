import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL || ''
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || ''

export const supabase = createClient(url, publishableKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: false,
  },
})

export function usernameToEmail(username) {
  const value = String(username || '').trim().toLowerCase()
  return value.includes('@') ? value : `${value}@users.mtm.local`
}

export async function signInIdentity(username, password) {
  const { data, error } = await supabase.auth.signInWithPassword({
    email: usernameToEmail(username),
    password,
  })
  if (error) throw error
  return data
}

export async function signOutIdentity() {
  await supabase.auth.signOut()
}

export async function getAccessToken() {
  const { data } = await supabase.auth.getSession()
  return data?.session?.access_token || ''
}

export async function getIdentitySession() {
  const { data } = await supabase.auth.getSession()
  return data?.session || null
}

export function onIdentityChange(callback) {
  const { data } = supabase.auth.onAuthStateChange((_event, session) => callback(session))
  return () => data.subscription.unsubscribe()
}
