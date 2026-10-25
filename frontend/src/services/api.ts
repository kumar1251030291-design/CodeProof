export interface HealthResponse {
  status: string
}

export type ApplicationRole = 'candidate' | 'evaluator'

export interface CurrentUserResponse {
  profile: { id: string; display_name: string | null; email: string | null }
  roles: ApplicationRole[]
  access_state: 'authorized' | 'pending_access'
}

export interface CandidateAssistantTurn {
  role: 'user' | 'assistant'
  text: string
}

export interface CandidateAssistancePayload {
  assessment_id: string
  attempt_id: string
  question_id: string
  message: string
  history: CandidateAssistantTurn[]
  include_code: boolean
  code?: string
}

export interface CandidateAssistanceResponse {
  message: string
}

export type AssessmentDifficulty = 'easy' | 'medium' | 'hard'
export type AssessmentAccessMode = 'open' | 'restricted'
export type AssessmentPurpose = 'hiring' | 'practice'
export type AssessmentQuestionType = 'programming' | 'debugging' | 'explanation' | 'multiple-choice'
export interface GeneratedPublicCase { input_data: string; expected_output: string }
export interface GeneratedQuestionDraft {
  title: string
  prompt: string
  question_type: AssessmentQuestionType
  difficulty: AssessmentDifficulty
  points: number
  default_language: 'python' | 'c'
  allowed_languages: Array<'python' | 'c'>
  time_limit_seconds: number
  display_order: number
  problem_statement: string
  examples: string
  answer_options: string[]
  correct_answer: string | null
  test_cases: Array<{ input_data: string; expected_output: string; visibility: 'public'; display_order: number }>
}
export interface GeneratedAssessmentDraft {
  title: string
  description: string
  instructions: string
  questions: GeneratedQuestionDraft[]
}
export interface GenerateAssessmentRequest {
  topic: string
  purpose: AssessmentPurpose
  experience_level: string
  difficulty: AssessmentDifficulty
  programming_languages: Array<'python' | 'c'>
  question_count: number
  question_types: AssessmentQuestionType[]
  duration_seconds: number
  job_role?: string
  skills?: string
  difficulty_mix?: string
  learning_objectives?: string
}
export type TestCaseVisibility = 'public' | 'hidden'

export interface TestCaseRecord {
  id: string
  input_data: string
  expected_output: string
  visibility: TestCaseVisibility
  display_order: number
}

export interface AssessmentQuestionRecord {
  id: string
  title: string
  prompt: string
  question_type: AssessmentQuestionType
  difficulty: AssessmentDifficulty
  points: number
  default_language: 'python' | 'c'
  allowed_languages: string[]
  time_limit_seconds: number
  display_order: number
  problem_statement: string
  examples: string
  answer_options: string[]
  correct_answer: string | null
  test_cases: TestCaseRecord[]
}

export interface AssessmentSummaryRecord {
  id: string
  title: string
  description: string
  instructions: string
  status: string
  difficulty: AssessmentDifficulty
  duration_seconds: number
  allowed_languages: string[]
  access_mode: AssessmentAccessMode
  purpose: AssessmentPurpose | null
  max_attempts: number | null
  starts_at: string | null
  ends_at: string | null
  published_at: string | null
  show_results_after_submission: boolean
  question_count: number
  created_at: string
  updated_at: string
}

export interface EvaluationQuestionResultRecord {
  question_id: string
  question_title: string
  question_type: AssessmentQuestionType
  question_prompt: string
  max_points: number
  response_text: string | null
  programming_language: string | null
  execution_status: string
  score: number | null
  passed_test_cases: number | null
  total_test_cases: number | null
  execution_details: Array<Record<string, unknown>> | null
  manual_score: number | null
  manual_feedback: string | null
  reviewed_at: string | null
  review_eligible: boolean
}

export interface EvaluationAttemptResultRecord {
  attempt_id: string
  candidate_id: string
  candidate_display_name: string | null
  attempt_number: number
  status: 'in_progress' | 'submitted' | 'expired'
  execution_status: string
  started_at: string
  submitted_at: string | null
  score: number | null
  max_score: number | null
  manual_score: number | null
  final_score: number | null
  review_status: 'pending' | 'complete' | 'not_required'
  responses: EvaluationQuestionResultRecord[]
}

export interface AssessmentResultsRecord {
  assessment_id: string
  attempts: EvaluationAttemptResultRecord[]
  total: number
  limit: number
  offset: number
}

export interface AssessmentRecord extends AssessmentSummaryRecord {
  questions: AssessmentQuestionRecord[]
  /** Returned only at creation or rotation; never persisted or returned by reads. */
  access_code?: string | null
}

export interface CandidatePublicExample {
  input_data: string
  expected_output: string
  display_order: number
}

export interface CandidateQuestionRecord {
  id: string
  title: string
  prompt: string
  question_type: AssessmentQuestionType
  difficulty: AssessmentDifficulty
  points: number
  default_language: 'python' | 'c'
  allowed_languages: string[]
  time_limit_seconds: number
  display_order: number
  problem_statement: string
  examples: string
  answer_options: string[]
  public_examples: CandidatePublicExample[]
}

export interface CandidateAssessmentRecord {
  id: string
  title: string
  description: string
  instructions: string
  difficulty: AssessmentDifficulty
  duration_seconds: number
  allowed_languages: string[]
  question_count: number
  starts_at: string | null
  ends_at: string | null
  max_attempts: number | null
  questions?: CandidateQuestionRecord[]
}

export interface CandidateAttemptResponseRecord {
  question_id: string
  response_text: string
  programming_language: 'python' | 'c' | null
  saved_at: string
  execution_status: string
  score: number | null
}

export interface CandidateAttemptRecord {
  id: string
  assessment_id: string
  assessment_title: string
  attempt_number: number
  started_at: string
  deadline_at: string
  status: 'in_progress' | 'submitted' | 'expired'
  submitted_at: string | null
  execution_status: string
  score: number | null
  max_score: number | null
  responses: CandidateAttemptResponseRecord[]
}

export interface FollowUpQuestionRecord {
  id: string; prompt: string; origin: 'ai' | 'evaluator'; answer: string; answered_at: string | null;
  answer_locked: boolean; created_at: string
}
export interface FollowUpInterviewRecord {
  id: string; attempt_id: string; assessment_id: string; status: 'pending' | 'in_progress' | 'submitted' | 'reviewed';
  submitted_at: string | null; reviewed_at: string | null; reviewer_id: string | null;
  review_notes: string | null; review_score: number | null; questions: FollowUpQuestionRecord[]
}

export interface AssessmentDraftPayload {
  title: string
  description: string
  instructions: string
  difficulty: AssessmentDifficulty
  duration_seconds: number
  allowed_languages: string[]
  access_mode: AssessmentAccessMode
  purpose: AssessmentPurpose
  max_attempts: number | null
  starts_at: string | null
  ends_at: string | null
  show_results_after_submission: boolean
  questions: Array<{
    id?: string
    title: string
    prompt: string
    question_type: AssessmentQuestionType
    difficulty: AssessmentDifficulty
    points: number
    default_language: 'python' | 'c'
    allowed_languages: string[]
    time_limit_seconds: number
    display_order: number
    problem_statement: string
    examples: string
    answer_options: string[]
    correct_answer: string | null
    test_cases: Array<{
      input_data: string
      expected_output: string
      visibility: TestCaseVisibility
      display_order: number
    }>
  }>
}

export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/+$/, '')

export async function fetchHealth(): Promise<HealthResponse> {
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}/health`)
  } catch (error) {
    const detail = error instanceof Error ? `: ${error.message}` : ''
    throw new ApiError(`Unable to reach the CodeProof API${detail}`)
  }

  if (!response.ok) {
    throw new ApiError(`CodeProof API returned HTTP ${response.status}`, response.status)
  }

  return (await response.json()) as HealthResponse
}

export async function fetchCurrentUser(accessToken: string): Promise<CurrentUserResponse> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
  } catch {
    throw new ApiError('Unable to reach the CodeProof API')
  }

  if (!response.ok) {
    throw new ApiError(
      response.status === 401
        ? 'Your session could not be verified.'
        : `CodeProof API returned HTTP ${response.status}`,
      response.status,
    )
  }

  return (await response.json()) as CurrentUserResponse
}

async function assessmentRequest<T>(path: string, accessToken: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError('Unable to reach the CodeProof API')
  }

  if (!response.ok) {
    let detail = `CodeProof API returned HTTP ${response.status}`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        detail = body.detail.map(item => typeof item === 'object' && item && 'msg' in item ? String(item.msg) : 'Invalid request').join('; ')
      }
    } catch {
      // Keep the generic HTTP message if the response does not contain JSON.
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function fetchReport(path: string, accessToken: string): Promise<{ blob: Blob; filename: string }> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { headers: { Authorization: `Bearer ${accessToken}` } })
  } catch {
    throw new ApiError('Unable to reach the CodeProof API')
  }
  if (!response.ok) {
    let message = `CodeProof API returned HTTP ${response.status}`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch { /* retain generic response error */ }
    throw new ApiError(message, response.status)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filename = disposition.match(/filename="([A-Za-z0-9_.-]+)"/i)?.[1] ?? 'codeproof-report.pdf'
  return { blob: await response.blob(), filename }
}

const ASSESSMENTS_PATH = '/api/v1/evaluator/assessments'

export function fetchOwnedAssessments(accessToken: string): Promise<{ assessments: AssessmentSummaryRecord[] }> {
  return assessmentRequest(ASSESSMENTS_PATH, accessToken)
}

export function fetchAssessment(accessToken: string, assessmentId: string): Promise<AssessmentRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}`, accessToken)
}

export function createAssessmentDraft(accessToken: string, payload: AssessmentDraftPayload): Promise<AssessmentRecord> {
  return assessmentRequest(ASSESSMENTS_PATH, accessToken, { method: 'POST', body: JSON.stringify(payload) })
}

export function generateAssessmentQuestionDrafts(accessToken: string, payload: GenerateAssessmentRequest): Promise<GeneratedAssessmentDraft> {
  return assessmentRequest('/api/v1/evaluator/ai/question-drafts', accessToken, {
    method: 'POST', body: JSON.stringify(payload),
  })
}

export function updateAssessmentDraft(accessToken: string, assessmentId: string, payload: AssessmentDraftPayload): Promise<AssessmentRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}`, accessToken, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function publishAssessment(accessToken: string, assessmentId: string): Promise<AssessmentRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/publish`, accessToken, { method: 'POST' })
}

export function deleteAssessmentDraft(accessToken: string, assessmentId: string): Promise<void> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}`, accessToken, { method: 'DELETE' })
}

export function archiveAssessment(accessToken: string, assessmentId: string): Promise<AssessmentRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/archive`, accessToken, { method: 'POST' })
}

export function rotateAssessmentAccessCode(accessToken: string, assessmentId: string): Promise<{ assessment_id: string; access_code: string }> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/access-code`, accessToken, { method: 'POST' })
}

export function fetchAssessmentResults(accessToken: string, assessmentId: string, offset = 0): Promise<AssessmentResultsRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/results?limit=50&offset=${offset}`, accessToken)
}

export function saveManualQuestionReview(
  accessToken: string,
  assessmentId: string,
  attemptId: string,
  questionId: string,
  payload: { score: number; feedback: string },
): Promise<EvaluationAttemptResultRecord> {
  return assessmentRequest(
    `${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/attempts/${encodeURIComponent(attemptId)}/questions/${encodeURIComponent(questionId)}/review`,
    accessToken,
    { method: 'PATCH', body: JSON.stringify(payload) },
  )
}

export function fetchCandidateAttemptReport(accessToken: string, attemptId: string): Promise<{ blob: Blob; filename: string }> {
  return fetchReport(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}/report.pdf`, accessToken)
}

export function fetchEvaluatorAttemptReport(accessToken: string, assessmentId: string, attemptId: string): Promise<{ blob: Blob; filename: string }> {
  return fetchReport(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/attempts/${encodeURIComponent(attemptId)}/report.pdf`, accessToken)
}

const CANDIDATE_PATH = '/api/v1/candidate'

export function fetchCandidateAssessments(accessToken: string): Promise<{ assessments: CandidateAssessmentRecord[] }> {
  return assessmentRequest(`${CANDIDATE_PATH}/assessments`, accessToken)
}

export function fetchCandidateAssessment(accessToken: string, assessmentId: string): Promise<CandidateAssessmentRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/assessments/${encodeURIComponent(assessmentId)}`, accessToken)
}

export function verifyCandidateAccessCode(accessToken: string, accessCode: string): Promise<{ assessment: CandidateAssessmentRecord; grant_expires_at: string }> {
  return assessmentRequest(`${CANDIDATE_PATH}/assessments/access-code`, accessToken, {
    method: 'POST', body: JSON.stringify({ access_code: accessCode }),
  })
}

export function startCandidateAttempt(accessToken: string, assessmentId: string): Promise<CandidateAttemptRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/assessments/${encodeURIComponent(assessmentId)}/attempts`, accessToken, { method: 'POST' })
}

export function fetchCandidateAttempts(accessToken: string): Promise<{ attempts: CandidateAttemptRecord[] }> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts`, accessToken)
}

export function fetchCandidateAttempt(accessToken: string, attemptId: string): Promise<CandidateAttemptRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}`, accessToken)
}

export function saveCandidateResponse(accessToken: string, attemptId: string, questionId: string, responseText: string, language: 'python' | 'c' | null): Promise<CandidateAttemptResponseRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}/responses/${encodeURIComponent(questionId)}`, accessToken, {
    method: 'PUT', body: JSON.stringify({ response_text: responseText, programming_language: language }),
  })
}

export function submitCandidateAttempt(accessToken: string, attemptId: string): Promise<CandidateAttemptRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}/submit`, accessToken, { method: 'POST' })
}

export function generateFollowUpInterview(accessToken: string, attemptId: string): Promise<FollowUpInterviewRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}/follow-up/generate`, accessToken, { method: 'POST' })
}
export function fetchFollowUpInterview(accessToken: string, attemptId: string): Promise<FollowUpInterviewRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}/follow-up`, accessToken)
}
export function saveFollowUpAnswer(accessToken: string, attemptId: string, questionId: string, answer: string): Promise<{ id: string; answer: string; answered_at: string | null }> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}/follow-up/questions/${encodeURIComponent(questionId)}`, accessToken, { method: 'PUT', body: JSON.stringify({ answer }) })
}
export function submitFollowUpInterview(accessToken: string, attemptId: string): Promise<FollowUpInterviewRecord> {
  return assessmentRequest(`${CANDIDATE_PATH}/attempts/${encodeURIComponent(attemptId)}/follow-up/submit`, accessToken, { method: 'POST' })
}
export function fetchEvaluatorFollowUpInterview(accessToken: string, assessmentId: string, attemptId: string): Promise<FollowUpInterviewRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/attempts/${encodeURIComponent(attemptId)}/follow-up`, accessToken)
}
export function addEvaluatorFollowUpQuestion(accessToken: string, assessmentId: string, attemptId: string, prompt: string): Promise<FollowUpInterviewRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/attempts/${encodeURIComponent(attemptId)}/follow-up/questions`, accessToken, { method: 'POST', body: JSON.stringify({ prompt }) })
}
export function reviewFollowUpInterview(accessToken: string, assessmentId: string, attemptId: string, notes: string, score: number | null): Promise<FollowUpInterviewRecord> {
  return assessmentRequest(`${ASSESSMENTS_PATH}/${encodeURIComponent(assessmentId)}/attempts/${encodeURIComponent(attemptId)}/follow-up/review`, accessToken, { method: 'PATCH', body: JSON.stringify({ notes, score }) })
}

export function requestCandidateAssistance(
  accessToken: string,
  payload: CandidateAssistancePayload,
): Promise<CandidateAssistanceResponse> {
  return assessmentRequest('/api/v1/candidate/ai/assistance', accessToken, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
