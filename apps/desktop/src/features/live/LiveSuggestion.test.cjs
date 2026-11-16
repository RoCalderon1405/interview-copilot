/** Render the real TSX component with the existing TypeScript/React dependencies. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname,'LiveSuggestion.tsx'),'utf8'), {
  compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS},
}).outputText;
const component = {exports:{}};
vm.runInNewContext(compiled,{require,exports:component.exports,module:component});
const render = item => renderToStaticMarkup(React.createElement(component.exports.LiveSuggestion,{item}));
test('generated answers show unverified AI provenance, not documentary attribution',()=>{
  const html=render({type:'generated_suggestion',kind:'ai_generated',question:'Explain caching?',
    answer:'<script>untrusted</script>',provider:'ollama',model:'local',source:null});
  assert.match(html,/Sugerencia generada por IA — revisar/);
  assert.match(html,/ollama · local · Sin respaldo documental/);
  assert.doesNotMatch(html,/Respuesta exacta|Fuente:|<script>/);
  assert.match(html,/&lt;script&gt;/);
});
test('exact and semantic answers retain source-backed labels',()=>{
  for(const match_type of ['exact_qa','semantic_qa']) {
    const html=render({type:'suggestion',question:'Question?',answer:'Stored wording',status:'found',
      match_type,matched_question:'Original?',source:{document_name:'synthetic.md',location:'Line 1'}});
    assert.match(html,/Fuente: synthetic.md/);
    assert.match(html,match_type==='exact_qa'?/Respuesta exacta del documento/:/Posible respuesta semántica — revisar/);
    assert.doesNotMatch(html,/generada por IA|Sin respaldo documental/);
  }
});
test('no evidence remains visible without a fabricated answer',()=>{
  const html=render({type:'suggestion',question:'Question?',status:'no_evidence',answer:null,source:null,match_type:null});
  assert.match(html,/Sin respuesta suficientemente relacionada/);
  assert.doesNotMatch(html,/generada por IA|Fuente:/);
});
