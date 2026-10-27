import axios from 'axios';

// Configurable base URL defaulting to http://127.0.0.1:8000 per prompt specification
const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export const apiClient = axios.create({
  baseURL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 180000, // 180s timeout for bounded Docker operations
});

/**
 * Extract clean, user-friendly error messages from Axios responses.
 */
export function formatApiError(error) {
  if (!error) return 'An unknown error occurred.';
  if (error.response) {
    const data = error.response.data;
    if (data?.detail) {
      if (typeof data.detail === 'string') return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail.map(d => `${d.loc ? d.loc.join('.') + ': ' : ''}${d.msg}`).join('; ');
      }
    }
    if (data?.final_details) return data.final_details;
    if (data?.error_message) return data.error_message;
    if (data?.errors && Array.isArray(data.errors)) return data.errors.join('; ');
    return `Server Error (${error.response.status}): ${error.response.statusText || 'Request failed'}`;
  }
  if (error.request) {
    return 'Unable to connect to backend service. Please check that FastAPI is running on ' + baseURL;
  }
  return error.message || 'Error configuring request.';
}

// -----------------------------------------------------------------------------
// Health Check
// -----------------------------------------------------------------------------
export async function fetchHealth() {
  const start = performance.now();
  const resp = await apiClient.get('/health');
  const latency = Math.round(performance.now() - start);
  return { ...resp.data, latency };
}

// -----------------------------------------------------------------------------
// Phase 2: GitHub Issue Intake
// -----------------------------------------------------------------------------
export async function analyzeIssue(issueUrl) {
  const resp = await apiClient.post('/issues/analyze', { issue_url: issueUrl });
  return resp.data;
}

// -----------------------------------------------------------------------------
// Phase 3: Sandbox Preparation & Reproduction Runner
// -----------------------------------------------------------------------------
export async function prepareSandbox({ issue_url, commit_sha }) {
  const payload = { issue_url };
  if (commit_sha && commit_sha.trim()) {
    payload.commit_sha = commit_sha.trim();
  }
  const resp = await apiClient.post('/sandbox/prepare', payload);
  return resp.data;
}

export async function reproduceBug({ session_id, test_command, expected_failure_pattern }) {
  const payload = { session_id };
  if (test_command && test_command.trim()) {
    payload.test_command = test_command.trim();
  }
  if (expected_failure_pattern && expected_failure_pattern.trim()) {
    payload.expected_failure_pattern = expected_failure_pattern.trim();
  }
  const resp = await apiClient.post('/sandbox/reproduce', payload);
  return resp.data;
}

export async function fetchSession(sessionId) {
  const resp = await apiClient.get(`/sandbox/${sessionId}`);
  return resp.data;
}

// -----------------------------------------------------------------------------
// Phase 4: Deterministic Localization & Patch Proposal
// -----------------------------------------------------------------------------
export async function localizeBug({
  issue_title,
  issue_body,
  stack_trace,
  reproduction_stdout,
  reproduction_stderr,
}) {
  const resp = await apiClient.post('/localize', {
    issue_title,
    issue_body: issue_body || null,
    stack_trace: stack_trace || null,
    reproduction_stdout: reproduction_stdout || null,
    reproduction_stderr: reproduction_stderr || null,
  });
  return resp.data;
}

export async function proposePatch({ localization, context, provider = 'mock' }) {
  const resp = await apiClient.post('/patch/propose', {
    localization,
    context: context || null,
    provider,
  });
  return resp.data;
}

export async function validatePatch({ session_id, unified_diff }) {
  const resp = await apiClient.post('/patch/validate', {
    session_id,
    unified_diff,
  });
  return resp.data;
}

// -----------------------------------------------------------------------------
// Phase 5A: Safe Patch Application
// -----------------------------------------------------------------------------
export async function applyPatch({ session_id, unified_diff }) {
  const resp = await apiClient.post('/patch/apply', {
    session_id,
    unified_diff,
  });
  return resp.data;
}

// -----------------------------------------------------------------------------
// Phase 5B: Isolated Docker Test Verification
// -----------------------------------------------------------------------------
export async function verifyPatchTest({ session_id, test_command, expected_failure_pattern, timeout }) {
  const payload = { session_id };
  if (test_command && test_command.trim()) payload.test_command = test_command.trim();
  if (expected_failure_pattern && expected_failure_pattern.trim()) {
    payload.expected_failure_pattern = expected_failure_pattern.trim();
  }
  if (timeout) payload.timeout = Number(timeout);

  const resp = await apiClient.post('/patch/verify-test', payload);
  return resp.data;
}

// -----------------------------------------------------------------------------
// Phase 6B: Bounded Automated Repair Loop
// -----------------------------------------------------------------------------
export async function runRepairLoop({
  session_id,
  localization,
  test_command,
  expected_failure_pattern,
  provider = 'mock',
  context,
  test_timeout = 60,
}) {
  const resp = await apiClient.post('/patch/repair-loop', {
    session_id,
    localization,
    test_command,
    expected_failure_pattern: expected_failure_pattern || null,
    provider,
    context: context || null,
    test_timeout: Number(test_timeout),
  });
  return resp.data;
}

// -----------------------------------------------------------------------------
// Session Reset Dirty
// -----------------------------------------------------------------------------
export async function resetDirtySession({ session_id }) {
  const resp = await apiClient.post('/patch/reset-dirty', { session_id });
  return resp.data;
}
