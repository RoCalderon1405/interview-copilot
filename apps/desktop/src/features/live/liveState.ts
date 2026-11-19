import type {GenerationFailureCode, LiveEvent} from '../../types';
import type {LiveGenerationState, LiveSuggestionEvent} from './LiveSuggestion';

export type LivePhase = 'idle' | 'consent' | 'connecting' | 'listening' | 'stopping' | 'stopped' | 'error';
export type LiveViewState = {
  phase: LivePhase;
  status: string;
  provider: string | null;
  partial: string;
  frames: number;
  sequence: number;
  transcript: {id: number; text: string}[];
  suggestions: {id: number; event: Extract<LiveSuggestionEvent, {type:'suggestion'}>;
    generated?: Extract<LiveSuggestionEvent, {type:'generated_suggestion'}>;
    generationFailure?: GenerationFailureCode; generationState?: LiveGenerationState}[];
};

export const initialLiveState: LiveViewState = {
  phase: 'idle', status: 'Prepara la captura y autorízala en la ventana de audio.',
  provider: null, partial: '', frames: 0, sequence: 0, transcript: [], suggestions: [],
};

function sameQuestion(left: {session_id?:string; question_id?:string}, right: {session_id?:string; question_id?:string}): boolean {
  return Boolean(left.session_id && left.question_id && left.session_id === right.session_id && left.question_id === right.question_id);
}

/** Retain unresolved outcomes without claiming that inference ever started. */
function endUnconfirmed(state: LiveViewState, reason: LiveGenerationState): LiveViewState['suggestions'] {
  return state.suggestions.map(item => item.generationState === 'unconfirmed' || item.generationState === 'replaced'
    || (reason !== 'replaced' && !item.generationState && item.event.status === 'no_evidence' && !item.generated)
    ? {...item, generationState:reason} : item);
}

/** Presentation only: each feed has its own bounded, newest-first history. */
export function receiveLiveEvent(state: LiveViewState, event: LiveEvent): LiveViewState {
  switch (event.type) {
    case 'partial':
      return ['stopping', 'stopped', 'error'].includes(state.phase) ? state : {...state, partial: event.text};
    case 'metrics':
      return {...state, frames: event.frames};
    case 'generation_failed': {
      if (['stopping','stopped','error'].includes(state.phase)) return state;
      return {...state, suggestions:state.suggestions.map(item => sameQuestion(item.event,event) &&
        item.event.status === 'no_evidence' && !item.generated &&
        !['stopped','interrupted'].includes(item.generationState ?? '')
        ? {...item, generationFailure:event.code, generationState:undefined} : item)};
    }
    case 'final':
      return {...state, partial: '', sequence: state.sequence + 1,
        transcript: [{id: state.sequence, text: event.text}, ...state.transcript].slice(0, 80)};
    case 'suggestion': {
      const existing = state.suggestions.find(item => sameQuestion(item.event,event));
      if (existing) return {...state, suggestions:state.suggestions.map(item => item.id === existing.id
        ? {...item, event, ...(event.status === 'found'
          ? {generated:undefined, generationFailure:undefined, generationState:undefined}
          : {generationState:item.generated ? undefined : item.generationState ?? (item.generationFailure ? undefined : 'unconfirmed')})} : item)};
      const card: LiveViewState['suggestions'][number] = {id:state.sequence, event,
        generationState:event.status === 'no_evidence' && event.session_id && event.question_id
          ? ['stopping','stopped'].includes(state.phase) ? 'stopped' : state.phase === 'error' ? 'interrupted' : 'unconfirmed' : undefined};
      return {...state, sequence: state.sequence + 1,
        suggestions:[card,...endUnconfirmed(state,'replaced')].slice(0, 20)};
    }
    case 'generated_suggestion':
      if (['stopping','stopped','error'].includes(state.phase)) return state;
      // AI enriches an existing correlated card; it never creates/reorders questions.
      return {...state, suggestions:state.suggestions.map(item => sameQuestion(item.event,event) &&
        item.event.status === 'no_evidence' && !['stopped','interrupted'].includes(item.generationState ?? '')
        ? {...item, generated:event, generationFailure:undefined, generationState:undefined} : item)};
    case 'error':
      return {...state, phase: 'error', status: event.text, partial: '', suggestions:endUnconfirmed(state,'interrupted')};
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
        suggestions:starting || phase === 'consent' || phase === 'error'
          ? endUnconfirmed(state,'interrupted') : ['stopping','stopped'].includes(phase) ? endUnconfirmed(state,'stopped') : state.suggestions,
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
