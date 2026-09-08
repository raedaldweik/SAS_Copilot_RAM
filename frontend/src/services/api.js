// Dev uses Vite proxy to :8000. Works same-origin in prod.
const API = '';

async function req(path, opts = {}) {
  const r = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: 'Connection error' }));
    throw new Error(e.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export const getHealth = () => req('/api/health');

// Extract text from an uploaded file (multipart — no JSON headers)
export const extractAttachment = async (file) => {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(`${API}/api/extract`, { method: 'POST', body: fd });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(e.detail || `HTTP ${r.status}`);
  }
  return r.json();
};
export const getAgents = () => req('/api/agents');
export const getCollections = () => req('/api/collections');
export const getSessions = () => req('/api/sessions');
export const getSessionQueries = (sessionId) =>
  req(`/api/sessions/${encodeURIComponent(sessionId)}/queries`);

// target: { type: 'agent', id }
// attachments: [{ name, text }] — extracted documents inlined into the query
// Returns { queryId, querySessionId, pollInterval, timeout, result? } —
// poll getQueryStatus until done unless `result` came back inline.
export const submitQuery = (content, target, querySessionId = null, attachments = null, language = 'en') =>
  req('/api/query', {
    method: 'POST',
    body: JSON.stringify({
      content,
      agentId: target.type === 'agent' ? target.id : null,
      collectionIds: target.type === 'collection' ? [target.id] : null,
      querySessionId,
      attachments,
      language,
    }),
  });

// wait > 0 long-polls: the server holds the request (up to `wait` seconds,
// capped server-side) and answers the moment the agent finishes.
export const getQueryStatus = (queryId, wait = 0) =>
  req(`/api/query/${encodeURIComponent(queryId)}${wait ? `?wait=${wait}` : ''}`);

// Tool/LLM calls the agent recorded for a query — also works mid-run
export const getQueryTrace = (queryId) => req(`/api/query/${encodeURIComponent(queryId)}/trace`);
