import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL || ''
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || ''

function buildClient(storageKey) {
  return createClient(url, publishableKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
      storageKey,
    },
  })
}

export const userSupabase = buildClient('mtm-user-auth')
export const adminSupabase = buildClient('mtm-admin-auth')

export function currentPortal() {
  if (typeof window !== 'undefined' && window.location.pathname.startsWith('/admin')) return 'admin'
  return 'user'
}

function clientFor(portal = currentPortal()) {
  return portal === 'admin' ? adminSupabase : userSupabase
}

export function usernameToEmail(username) {
  const value = String(username || '').trim().toLowerCase()
  return value.includes('@') ? value : `${value}@users.mtm.local`
}

export async function signInIdentity(username, password, portal = currentPortal()) {
  const { data, error } = await clientFor(portal).auth.signInWithPassword({
    email: usernameToEmail(username),
    password,
  })
  if (error) throw error
  return data
}

export async function signOutIdentity(portal = currentPortal()) {
  await clientFor(portal).auth.signOut()
}

export async function getAccessToken(portal = currentPortal()) {
  const { data } = await clientFor(portal).auth.getSession()
  return data?.session?.access_token || ''
}

export async function getIdentitySession(portal = currentPortal()) {
  const { data } = await clientFor(portal).auth.getSession()
  return data?.session || null
}

export function onIdentityChange(callback, portal = currentPortal()) {
  const { data } = clientFor(portal).auth.onAuthStateChange((_event, session) => callback(session))
  return () => data.subscription.unsubscribe()
}
