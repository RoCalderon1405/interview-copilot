import type {LiveEvent} from '../../types';

export type LiveSuggestionEvent = Extract<LiveEvent, {type: 'suggestion' | 'generated_suggestion'}>;

/** Keep generated provenance structurally separate from documentary attribution. */
export function LiveSuggestion({item}: {item: LiveSuggestionEvent}) {
  if (item.type === 'generated_suggestion') return <div className="live-result">
    <strong>{item.question}</strong>
    <span className="live-result-label">Sugerencia generada por IA — revisar</span>
    <p>{item.answer}</p>
    <div className="small-muted">{item.provider} · {item.model} · Sin respaldo documental</div>
  </div>;
  return <div className="live-result">
    <strong>{item.question}</strong>
    <span className={`live-result-label ${item.status === 'found' ? 'matched' : ''}`}>
      {item.match_type === 'exact_qa' ? 'Respuesta exacta del documento' : item.match_type === 'semantic_qa' ? 'Posible respuesta semántica — revisar' : 'Sin respuesta suficientemente relacionada'}
    </span>
    {item.match_type === 'semantic_qa' && item.matched_question && <span className="small-muted">Pregunta guardada: {item.matched_question}</span>}
    {item.answer && <p>{item.answer}</p>}
    {item.source && <div className="small-muted">Fuente: {item.source.document_name} · {item.source.location}</div>}
  </div>;
}
