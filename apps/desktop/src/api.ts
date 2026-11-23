import type { AnswerResponse, DeepgramAvailability, DocumentRecord, Feedback, PracticeQuestion, Session, SessionReport } from './types';

const API = 'http://127.0.0.1:8765';

async function request<T>(route: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${route}`, init);
  } catch {
    throw new Error('No se pudo conectar al backend. Inicia FastAPI en el puerto 8765.');
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Error HTTP ${response.status}`);
  return body as T;
}
const json = (body: unknown) => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), method: 'POST' });
export const api = {
  // Bound availability checks; a stalled backend must leave the UI retryable.
  liveStatus: () => request<{providers?:{deepgram?:DeepgramAvailability}}>('/live/status', {cache:'no-store', signal:AbortSignal.timeout(10000)}),
  health: () => request<{status: string}>('/health'),
  documents: () => request<{documents: DocumentRecord[]}>('/documents'),
  upload: (file: File) => { const data = new FormData(); data.append('file', file); return request<{id: string; name: string; entry_count: number}>('/documents', { method: 'POST', body: data }); },
  deleteDocument: (id: string) => request<{deleted: boolean}>(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  answer: (question: string) => request<AnswerResponse>('/answers', json({question})),
  createSession: (mode: Session['mode']) => request<Session>('/sessions', json({mode})),
  nextQuestion: (id: string) => request<PracticeQuestion>(`/sessions/${encodeURIComponent(id)}/next`, { method: 'POST' }),
  evaluate: (id: string, answer: string) => request<Feedback>(`/sessions/${encodeURIComponent(id)}/evaluate`, json({answer})),
  finishSession: (id: string) => request<SessionReport>(`/sessions/${encodeURIComponent(id)}/finish`, { method: 'POST' }),
  sessionReport: (id: string) => request<SessionReport>(`/sessions/${encodeURIComponent(id)}/report`),
};
