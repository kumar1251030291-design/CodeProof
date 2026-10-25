import assert from 'node:assert/strict'
import { test } from 'node:test'
import { accessVerificationFailure, ApiError, fetchWithTimeout, withTimeout } from '../src/services/request.ts'

test('API request timeout returns an actionable error without request details', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
  })
  try {
    await assert.rejects(fetchWithTimeout('http://127.0.0.1:8000/api/v1/me', {}, 5), error => {
      assert.ok(error instanceof ApiError)
      assert.match(error.message, /backend is running/)
      assert.doesNotMatch(error.message, /Bearer|token|password/i)
      return true
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a stalled session refresh is bounded', async () => {
  await assert.rejects(withTimeout(new Promise(() => {}), 5, 'Session refresh timed out.'), ApiError)
})

test('verification failures distinguish rejected sessions from backend and database errors', () => {
  assert.deepEqual(accessVerificationFailure(new ApiError('unauthorized', 401)), {
    status: 'expired', message: 'Your sign-in session could not be verified. Sign in again and retry.',
  })
  assert.deepEqual(accessVerificationFailure(new ApiError('Profile storage is unavailable. Check the backend database target and apply the reviewed Alembic migrations to that database.', 503)), {
    status: 'unavailable',
    message: 'Profile storage is unavailable. Check the backend database target and apply the reviewed Alembic migrations to that database.',
  })
})
