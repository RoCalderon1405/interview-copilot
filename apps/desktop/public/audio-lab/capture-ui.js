/** Translate authored controls only; never walk incoming transcript/document text. */
'use strict';
(() => {
  let language = 'es';
  const staticText = [];
  const attributes = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.textContent.trim() && !['SCRIPT','STYLE'].includes(node.parentElement?.tagName)) {
      staticText.push([node,node.textContent]);
    }
  }
  for (const element of document.querySelectorAll('[aria-label], [title], [placeholder]')) {
    for (const name of ['aria-label','title','placeholder']) {
      if (element.hasAttribute(name)) attributes.push([element,name,element.getAttribute(name)]);
    }
  }
  function t(text) {
    const translated = window.copilotUi.translate(language,text);
    return translated !== text ? translated : text.split(/(?<=\.)\s+/).map(part => window.copilotUi.translate(language,part)).join(' ');
  }
  function set(element, text) {
    element.dataset.uiCopy = text;
    element.textContent = t(text);
  }
  function content(element, text) {
    delete element.dataset.uiCopy;
    element.textContent = text;
  }
  function apply(next) {
    if (next !== 'en' && next !== 'es') return;
    language = next;
    document.documentElement.lang = next;
    document.title = t('Live audio — autorización y controles');
    for (const [node,text] of staticText) if (node.isConnected) node.textContent = t(text.trim());
    for (const [element,name,text] of attributes) element.setAttribute(name,t(text));
    for (const element of document.querySelectorAll('[data-ui-copy]')) element.textContent = t(element.dataset.uiCopy);
  }
  window.copilotCaptureUi = Object.freeze({set,content});
  apply('es');
  let revision = 0;
  const unsubscribe = window.copilotCapture?.onUiLanguage(next => { revision++; apply(next); });
  const initial = revision;
  void window.copilotCapture?.getUiLanguage().then(next => { if (initial === revision) apply(next); }).catch(() => {});
  window.addEventListener('pagehide', () => unsubscribe?.(), {once:true});
})();
