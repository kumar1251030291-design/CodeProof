
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  if (mode === 'production') {
    const apiUrl = env.VITE_API_BASE_URL?.trim()
    const supabaseUrl = env.VITE_SUPABASE_URL?.trim()
    const publishableKey = env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim()

    if (
      !apiUrl ||
      !supabaseUrl ||
      !publishableKey ||
      /your-project|replace-with|your-supabase/i.test(
        `${apiUrl} ${supabaseUrl} ${publishableKey}`,
      )
    ) {
      throw new Error(
        'Production build requires VITE_API_BASE_URL, VITE_SUPABASE_URL, and VITE_SUPABASE_PUBLISHABLE_KEY.',
      )
    }

    try {
      const api = new URL(apiUrl)
      const supabase = new URL(supabaseUrl)

      if (
        api.protocol !== 'https:' ||
        supabase.protocol !== 'https:' ||
        (api.pathname !== '' && api.pathname !== '/')
      ) {
        throw new Error()
      }
    } catch {
      throw new Error(
        'Production API and Supabase URLs must be valid HTTPS origins; VITE_API_BASE_URL must not include a path.',
      )
    }
  }

  return { plugins: [react()] }
})
