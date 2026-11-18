import type {LiveEvent} from '../../types';

export type LiveSuggestionEvent = Extract<LiveEvent, {type: 'suggestion' | 'generated_suggestion'}>;

/** Keep generated provenance structurally separate from documentary attribution. */
export function LiveSuggestion({item}: {item: LiveSuggestionEvent}) {
  if (item.type === 'generated_suggestion') return <article className="live-result live-result-generated">
    <span className="live-result-label">Sugerencia generada por IA — revisar</span>
    <h3>{item.question}</h3>
    <p>{item.answer}</p>
    <div className="small-muted">{item.provider} · {item.model} · Sin respaldo documental</div>
    <span className="live-result-warning">No verificada. Puede contener errores o experiencia inventada.</span>
  </article>;
  return <article className={`live-result live-result-${item.status === 'found' ? item.match_type : 'no-evidence'}`}>
    <span className={`live-result-label ${item.status === 'found' ? 'matched' : ''}`}>
      {item.match_type === 'exact_qa' ? 'Respuesta exacta del documento' : item.match_type === 'semantic_qa' ? 'Posible respuesta semántica — revisar' : 'Sin respuesta suficientemente relacionada'}
    </span>
    <h3>{item.question}</h3>
    {item.match_type === 'semantic_qa' && item.matched_question && <span className="small-muted">Pregunta guardada: {item.matched_question}</span>}
    {item.answer && <p>{item.answer}</p>}
    {item.status === 'no_evidence' && <p>No hay una respuesta suficientemente relacionada en los documentos. Una sugerencia de IA, si llega, se muestra por separado.</p>}
    {item.source && <div className="small-muted">Fuente: {item.source.document_name} · {item.source.location}</div>}
  </article>;
}
