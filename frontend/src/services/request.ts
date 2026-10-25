export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const API_REQUEST_TIMEOUT_MS = 10_000

export async function fetchWithTimeout(url: string, init?: RequestInit, timeoutMs = API_REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController()
  let timedOut = false
  const timer = globalThis.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch (error) {
    if (timedOut) {
      throw new ApiError(`CodeProof API did not respond within ${Math.ceil(timeoutMs / 1000)} seconds. Confirm that the backend is running and VITE_API_BASE_URL points to it.`)
    }
    throw error
  } finally {
    globalThis.clearTimeout(timer)
  }
}

export async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = globalThis.setTimeout(() => reject(new ApiError(message)), timeoutMs)
      }),
    ])
  } finally {
    if (timer) globalThis.clearTimeout(timer)
  }
}

export type IdentityFailureStatus = 'expired' | 'unavailable'

export function accessVerificationFailure(error: unknown): { status: IdentityFailureStatus; message: string } {
  if (error instanceof ApiError && error.status === 401) {
    return { status: 'expired', message: 'Your sign-in session could not be verified. Sign in again and retry.' }
  }
  if (error instanceof ApiError) return { status: 'unavailable', message: error.message }
  return {
    status: 'unavailable',
    message: 'Could not verify access. Check that the backend and its configured database are available, then retry.',
  }
}
