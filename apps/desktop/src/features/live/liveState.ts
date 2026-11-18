import type {LiveEvent} from '../../types';
import type {LiveSuggestionEvent} from './LiveSuggestion';

export type LivePhase = 'idle' | 'consent' | 'connecting' | 'listening' | 'stopping' | 'stopped' | 'error';
export type LiveViewState = {
  phase: LivePhase;
  status: string;
  provider: string | null;
  partial: string;
  frames: number;
  sequence: number;
  transcript: {id: number; text: string}[];
  suggestions: {id: number; event: LiveSuggestionEvent}[];
};

export const initialLiveState: LiveViewState = {
  phase: 'idle', status: 'Prepara la captura y autorízala en la ventana de audio.',
  provider: null, partial: '', frames: 0, sequence: 0, transcript: [], suggestions: [],
};

/** Presentation only: each feed has its own bounded, newest-first history. */
export function receiveLiveEvent(state: LiveViewState, event: LiveEvent): LiveViewState {
  switch (event.type) {
    case 'partial':
      return ['stopping', 'stopped', 'error'].includes(state.phase) ? state : {...state, partial: event.text};
    case 'metrics':
      return {...state, frames: event.frames};
    case 'final':
      return {...state, partial: '', sequence: state.sequence + 1,
        transcript: [{id: state.sequence, text: event.text}, ...state.transcript].slice(0, 80)};
    case 'suggestion':
    case 'generated_suggestion':
      return {...state, sequence: state.sequence + 1,
        suggestions: [{id: state.sequence, event}, ...state.suggestions].slice(0, 20)};
    case 'error':
      return {...state, phase: 'error', status: event.text, partial: ''};
    case 'status': {
      const text = event.text;
      let phase = state.phase;
      if (text.startsWith('Confirma la captura')) phase = 'consent';
      else if (text === 'Solicitando audio del sistema…' || /^(Comprobando|Conectando con) /.test(text)) phase = 'connecting';
      else if (/^(Vosk|Faster-Whisper|Deepgram Nova-3) listo\./.test(text)) phase = 'listening';
      else if (text.startsWith('Deteniendo')) phase = 'stopping';
      else if (text === 'Captura detenida.' || text === 'Captura y STT detenidos.') phase = 'stopped';
      else if (text.startsWith('FALLO:')) phase = 'error';
      const provider = ['Vosk', 'Faster-Whisper', 'Deepgram Nova-3'].find(name =>
        text.startsWith(`Comprobando ${name}`) || text.startsWith(`Conectando con ${name}`) || text.startsWith(`${name} listo.`));
      const starting = text === 'Solicitando audio del sistema…';
      return {...state, status: text, phase,
        provider: starting ? null : provider ?? state.provider,
        frames: starting ? 0 : state.frames,
        partial: ['consent', 'connecting', 'stopping', 'stopped', 'error'].includes(phase) ? '' : state.partial};
    }
  }
}

/** Merge the initial IPC snapshot with events delivered while it was in flight. */
export function restoreLiveState(snapshot: LiveEvent[], pending: LiveEvent[]): LiveViewState {
  const durable = (event: LiveEvent) => event.type !== 'partial' && event.type !== 'metrics';
  const queued = pending.filter(durable);
  let overlap = Math.min(snapshot.length, queued.length);
  while (overlap > 0 && !snapshot.slice(-overlap).every((event, index) =>
    JSON.stringify(event) === JSON.stringify(queued[index]))) overlap--;
  // Drop transients preceding a final already present in the snapshot as well.
  let start = 0;
  while (overlap > 0 && start < pending.length) if (durable(pending[start++])) overlap--;
  return [...snapshot, ...pending.slice(start)].reduce(receiveLiveEvent, initialLiveState);
}
