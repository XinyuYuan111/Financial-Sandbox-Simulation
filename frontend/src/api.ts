const jsonHeaders = { 'Content-Type': 'application/json' }

export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error_code: 'HTTP_ERROR', message: response.statusText }))
    throw new ApiError(body.error_code ?? 'HTTP_ERROR', body.message ?? response.statusText)
  }
  return response.json() as Promise<T>
}

export const api = {
  listRuns: <T>() => request<T>('/api/v1/runs'),
  getRun: <T>(runId: string) => request<T>(`/api/v1/runs/${runId}`),
  state: <T>(branchId: string, cursor?: number) => request<T>(`/api/v1/branches/${branchId}/state${cursor === undefined ? '' : `?cursor=${cursor}`}`),
  events: <T>(branchId: string, after = 0) => request<T>(`/api/v1/branches/${branchId}/events?after=${after}&limit=500`),
  observations: <T>(branchId: string, agentId: string, cursor?: number) => request<T>(`/api/v1/branches/${branchId}/agents/${agentId}/observations${cursor === undefined ? '' : `?cursor=${cursor}`}`),
  providers: <T>() => request<T>('/api/v1/providers'),
  providerPreflight: <T>(name: string) => request<T>(`/api/v1/providers/${name}/preflight`, { method: 'POST' }),
  agents: <T>(branchId: string) => request<T>(`/api/v1/branches/${branchId}/agents`),
  agent: <T>(branchId: string, agentId: string) => request<T>(`/api/v1/branches/${branchId}/agents/${agentId}`),
  decisions: <T>(branchId: string, agentId: string) => request<T>(`/api/v1/branches/${branchId}/agents/${agentId}/decisions`),
  plans: <T>(branchId: string, agentId: string) => request<T>(`/api/v1/branches/${branchId}/agents/${agentId}/plans`),
  receipts: <T>(branchId: string, agentId: string) => request<T>(`/api/v1/branches/${branchId}/agents/${agentId}/receipts`),
  interventionPlans: <T>(branchId: string) => request<T>(`/api/v1/branches/${branchId}/intervention-plans`),
  draftInterventionPlan: <T>(branchId: string, draft: unknown) => request<T>(`/api/v1/branches/${branchId}/intervention-plans`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ client_command_id: crypto.randomUUID(), draft }) }),
  interpretInterventionPlan: <T>(branchId: string, userIntent: string, requestedEffectiveTimeUs: number) => request<T>(`/api/v1/branches/${branchId}/intervention-plans/interpret`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ client_command_id: crypto.randomUUID(), user_intent: userIntent, requested_effective_time_us: requestedEffectiveTimeUs, provider: 'openai', access_scope: { private_grants: [] }, private_read_refs: [] }) }),
  confirmInterventionPlan: <T>(branchId: string, planId: string) => request<T>(`/api/v1/branches/${branchId}/intervention-plans/${planId}/confirm`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ client_command_id: crypto.randomUUID() }) }),
  rejectInterventionPlan: <T>(branchId: string, planId: string) => request<T>(`/api/v1/branches/${branchId}/intervention-plans/${planId}/reject`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ client_command_id: crypto.randomUUID() }) }),
  createScenario: <T>(body: unknown) => request<T>('/api/v1/scenarios', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(body) }),
  resolveScenario: <T>(scenarioId: string) => request<T>(`/api/v1/scenarios/${scenarioId}/resolve`, { method: 'POST' }),
  createRun: <T>(scenarioId: string) => request<T>('/api/v1/runs', { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ scenario_id: scenarioId }) }),
  command: <T>(branchId: string, commandType: string, payload: Record<string, unknown> = {}) => request<T>(`/api/v1/branches/${branchId}/commands`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ client_command_id: crypto.randomUUID(), command_type: commandType, payload }) }),
  fork: <T>(branchId: string, checkpointId: string) => request<T>(`/api/v1/branches/${branchId}/fork`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ client_command_id: crypto.randomUUID(), checkpoint_id: checkpointId }) }),
  exportArchive: <T>(runId: string) => request<T>('/api/v1/archives/export', { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ run_id: runId }) }),
  importArchive: async <T>(file: File) => {
    const form = new FormData()
    form.append('archive', file)
    return request<T>('/api/v1/archives/import', { method: 'POST', body: form })
  },
}
