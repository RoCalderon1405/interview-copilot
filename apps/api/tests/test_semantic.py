"""Small local semantic-index tests with fake vectors: no model download/network.

These prove persistence, exact priority and safe abstention, NOT real embedding accuracy.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib.machinery import ModuleSpec
import threading
import types
import sys

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.parsers import ParsedEntry
from app.retrieval import suggest_live
from app.semantic import SemanticIndex
from app.store import KnowledgeStore


class FakeEmbedding:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        for text in texts:
            self.calls.append(text)
            t = text.lower()
            if 'authentication' in t or 'identidad' in t:
                yield [1, 0, 0]
            elif 'authorization' in t or 'permisos' in t:
                yield [0, 1, 0]
            elif 'injection' in t or 'inyeccion' in t:
                yield [0, 0, 1]
            elif 'unrelated' in t:
                yield [0.3, 0.2, 0.9]
            else:
                yield [0.5, 0.5, 0.5]


def qa(store, name, question, answer):
    store.import_document(
        name, name.encode(),
        [ParsedEntry('qa', question, answer, '', 'Línea 2')],
    )


def test_index_lookup_exact_priority_and_persistence(tmp_path):
    store = KnowledgeStore(tmp_path)
    qa(store, 'auth.md', 'What is authentication?', 'Authentication verifies an identity.')
    qa(store, 'authz.md', 'What is authorization?', 'Authorization grants permissions.')
    fake = FakeEmbedding()
    semantic = SemanticIndex(store, embedder=fake)
    assert semantic.status()['indexed'] == 0
    status = semantic.index()
    assert status['questions'] == 2 and status['indexed'] == 2
    assert fake.calls == ['What is authentication?', 'What is authorization?']

    found = suggest_live(store, 'Could you explain authentication?', semantic=semantic)
    assert found['match_type'] == 'semantic_qa'
    assert found['answer'] == 'Authentication verifies an identity.'
    assert found['matched_question'] == 'What is authentication?'
    assert found['source']['document_name'] == 'auth.md'
    assert found['similarity'] == 1.0

    exact = suggest_live(store, 'What is authorization?', semantic=semantic)
    assert exact['match_type'] == 'exact_qa'
    assert exact['answer'] == 'Authorization grants permissions.'
    assert len(fake.calls) == 3  # exact answer uses no embedding
    assert semantic.index()['indexed'] == 2  # cached, no duplicate work
    assert len(fake.calls) == 3

    restarted_store = KnowledgeStore(tmp_path)
    restarted = SemanticIndex(restarted_store, embedder=FakeEmbedding())
    assert restarted.status()['indexed'] == 2
    assert restarted.candidate('Could you explain authentication?')['answer'] == found['answer']


def test_new_document_indexed_later_and_deleted_vectors_cascade(tmp_path):
    store = KnowledgeStore(tmp_path)
    qa(store, 'auth.md', 'What is authentication?', 'identity')
    fake = FakeEmbedding()
    index = SemanticIndex(store, embedder=fake)
    index.index()
    qa(store, 'inject.md', 'What is dependency injection?', 'decoupling')
    assert index.status()['pending'] == 1
    assert len(fake.calls) == 1
    index.index()
    assert index.status()['pending'] == 0
    assert len(fake.calls) == 2
    with store.connection() as db:
        doc_id = db.execute('SELECT id FROM documents WHERE name=?', ('auth.md',)).fetchone()[0]
    assert store.delete_document(doc_id)
    assert index.status()['questions'] == 1 and index.status()['indexed'] == 1
    assert index.candidate('Could you explain authentication?') is None


def test_ambiguous_or_weak_similarity_abstains(tmp_path):
    store = KnowledgeStore(tmp_path)
    qa(store, 'auth.md', 'What is authentication?', 'identity')
    qa(store, 'identity.md', 'Explain user identity verification', 'different wording')

    class AmbiguousEmbedding:
        def embed(self, texts):
            for text in texts:
                if text == 'What is authentication?':
                    yield [1.0, 0.0, 0.0]
                elif text == 'Explain user identity verification':
                    yield [0.999, 0.0447, 0.0]
                elif text == 'could you explain authentication':
                    yield [1.0, 0.0, 0.0]
                else:
                    yield [0.0, 0.0, 1.0]

    index = SemanticIndex(store, embedder=AmbiguousEmbedding())
    index.index()
    assert index.candidate('could you explain authentication') is None
    assert index.candidate('completely unrelated') is None
    assert suggest_live(store, 'could you explain authentication', index)['status'] == 'no_evidence'


def test_semantic_candidates_keep_original_language_without_cross_language_margin_collisions(tmp_path):
    store = KnowledgeStore(tmp_path)
    ids = {}
    for language, question, answer in [
        ('es', '¿Qué es la identidad?', 'La identidad identifica a una persona.'),
        ('en', 'What is authentication?', 'Authentication verifies identity.'),
    ]:
        ids[language] = store.import_document(language + '.xlsx', language.encode(), [
            ParsedEntry('qa', question, answer, '', 'Sheet 1 · row 2 · ' + language.upper(), language),
        ])['id']
    index = SemanticIndex(store, embedder=FakeEmbedding())
    index.index()  # Both languages deliberately have the same fake vector.
    for query, language, answer in [
        ('Could you explain authentication?', 'en', 'Authentication verifies identity.'),
        ('Puedes explicar la identidad?', 'es', 'La identidad identifica a una persona.'),
    ]:
        result = suggest_live(store, query, index)
        assert result['match_type'] == 'semantic_qa' and result['answer'] == answer
        assert result['source']['language'] == language
    assert store.delete_document(ids['en'])
    assert suggest_live(store, 'Could you explain authentication?', index)['status'] == 'no_evidence'


def test_optional_model_absent_keeps_exact_and_status_endpoint(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/semantic/status').status_code == 200
        body = client.get('/semantic/status').json()
        assert body['indexed'] == 0
        app.state.store.import_document(
            'auth.md', b'auth', [ParsedEntry('qa', 'What is authentication?', 'identity', '', 'Línea 1')],
        )
        assert client.get('/semantic/status').json()['pending'] == 1
        assert suggest_live(app.state.store, 'What is authentication?', app.state.semantic)['match_type'] == 'exact_qa'
        assert suggest_live(app.state.store, 'Could you explain authentication?', app.state.semantic)['status'] == 'no_evidence'


def test_index_endpoint_with_fake_model_and_no_download(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        app.state.store.import_document(
            'auth.md', b'auth', [ParsedEntry('qa', 'What is authentication?', 'identity', '', 'Línea 1')],
        )
        app.state.semantic = SemanticIndex(app.state.store, embedder=FakeEmbedding())
        assert client.post('/semantic/index', json={}).status_code == 200
        assert client.get('/semantic/status').json()['indexed'] == 1
        found = suggest_live(app.state.store, 'Could you explain authentication?', app.state.semantic)
        assert found['match_type'] == 'semantic_qa'


@pytest.mark.parametrize('enabled', [False, True])
def test_import_schedules_only_new_qa_when_enabled_and_keeps_manual_indexing(tmp_path, monkeypatch, enabled):
    if enabled:
        monkeypatch.setenv('COPILOT_AUTO_SEMANTIC_INDEX', '1')
    else:
        monkeypatch.delenv('COPILOT_AUTO_SEMANTIC_INDEX', raising=False)
    app = create_app(tmp_path)
    fake = FakeEmbedding()
    app.state.semantic._embedder = fake
    qa(app.state.store, 'old.md', 'What is authentication?', 'old answer')
    with TestClient(app) as client:
        assert client.get('/semantic/status').json()['automatic_enabled'] is enabled
        fragment = client.post('/documents', files={'file': ('notes.txt', b'An ordinary document fragment.')})
        assert fragment.status_code == 201
        # A fragment-only import must not load or call the embedding model.
        assert fake.calls == []
        imported = client.post('/documents', files={'file': (
            'new.md', b'Q: What is authorization?\nA: Authorization grants permissions.')})
        assert imported.status_code == 201
        doc_id = imported.json()['id']
        if enabled:
            # The existing writer lock drains/coalesces automatic and legacy manual work.
            result = client.post('/semantic/index', json={'document_id': doc_id})
            assert result.status_code == 200
            assert fake.calls == ['What is authorization?']
        else:
            assert fake.calls == []
            state = next(doc for doc in client.get('/semantic/status').json()['documents'] if doc['document_id'] == doc_id)
            assert state['state'] == 'pending' and not state['requested']
            assert client.post('/semantic/index', json={'document_id': doc_id}).status_code == 200
        state = client.get('/semantic/status').json()
        old = next(doc for doc in state['documents'] if doc['name'] == 'old.md')
        assert old['pending'] == 1 and not old['requested']
        assert client.post('/answers', json={'question': 'What is authorization?'}).json()['match_type'] == 'exact_qa'


def test_overlapping_background_and_manual_requests_embed_missing_questions_once(tmp_path, monkeypatch):
    monkeypatch.setenv('COPILOT_AUTO_SEMANTIC_INDEX', '0')
    entered, release = threading.Event(), threading.Event()

    class HeldEmbedding(FakeEmbedding):
        def embed(self, texts):
            entered.set()
            assert release.wait(5)
            yield from super().embed(texts)

    app = create_app(tmp_path)
    fake = HeldEmbedding()
    app.state.semantic._embedder = fake
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        doc_id = client.post('/documents', files={'file': ('qa.md', b'Q: What is authentication?\nA: Identity verification.')} ).json()['id']
        request = {'document_id': doc_id, 'background': True}
        try:
            assert app.state.live.acquire_connection()
            assert client.post('/semantic/index', json=request).status_code == 200
            deferred = client.get('/semantic/status').json()
            assert deferred['deferred_for_live'] and deferred['documents'][0]['state'] == 'pending'
            assert not fake.calls and not entered.is_set()
            app.state.live.release_connection()
            assert entered.wait(5)
            for _ in range(2):
                response = client.post('/semantic/index', json=request)
                assert response.status_code == 200
                assert response.json()['documents'][0]['state'] == 'indexing'
            # Actual HTTP/SQLite search stays usable while native embedding is held.
            assert client.get('/health').status_code == 200
            assert client.post('/answers', json={'question': 'What is authentication?'}).json()['match_type'] == 'exact_qa'
            manual = executor.submit(client.post, '/semantic/index', json={'document_id': doc_id})
        finally:
            app.state.live.release_connection()
            release.set()
        assert manual.result(timeout=5).status_code == 200
        assert fake.calls == ['What is authentication?']
        assert client.get('/semantic/status').json()['documents'][0]['state'] == 'completed'


def test_missing_model_partial_failure_and_retry_never_download_or_erase_indexed_batches(tmp_path, monkeypatch):
    monkeypatch.setenv('COPILOT_AUTO_SEMANTIC_INDEX', '1')
    unavailable, failed = threading.Event(), threading.Event()
    local_only = []
    prepared = False

    class RecoverableEmbedding(FakeEmbedding):
        attempts = 0
        fail_batch = True

        def embed(self, texts):
            self.attempts += 1
            if self.attempts == 2 and self.fail_batch:
                failed.set()
                raise RuntimeError('private model detail')
            yield from super().embed(texts)

    fake = RecoverableEmbedding()

    def load_model(**options):
        local_only.append(options['local_files_only'])
        if not prepared:
            unavailable.set()
            raise OSError('private cache location')
        return fake

    runtime = types.ModuleType('fastembed')
    runtime.__spec__ = ModuleSpec('fastembed', loader=None)
    runtime.TextEmbedding = load_model
    monkeypatch.setitem(sys.modules, 'fastembed', runtime)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        payload = '\n'.join(f'Q: Question number {i}?\nA: Stored answer {i}.' for i in range(5)).encode()
        imported = client.post('/documents', files={'file': ('qa.md', payload)})
        assert imported.status_code == 201
        doc_id = imported.json()['id']
        assert unavailable.wait(5)
        app.state.semantic.drain()
        state = client.get('/semantic/status').json()['documents'][0]
        assert state['state'] == 'failed' and state['error'] == 'model_unavailable'
        assert client.post('/answers', json={'question': 'Question number 0?'}).json()['match_type'] == 'exact_qa'
        assert client.post('/answers', json={'question': 'Stored answer 0'}).json()['status'] == 'found'
        # Background downloads are rejected even when a caller explicitly asks for one.
        assert client.post('/semantic/index', json={'background': True, 'allow_download': True}).status_code == 422
        assert client.post('/semantic/index', json={'document_id': doc_id}).status_code == 409
        prepared = True
        assert client.post('/semantic/index', json={'document_id': doc_id, 'background': True}).status_code == 200
        assert failed.wait(5)
        app.state.semantic.drain()
        state = client.get('/semantic/status').json()['documents'][0]
        assert state['state'] == 'failed' and state['indexed'] == 4 and state['pending'] == 1
        with app.state.store.connection() as db:
            saved = [tuple(row) for row in db.execute('SELECT entry_id,embedding FROM qa_vectors ORDER BY entry_id')]
        fake.fail_batch = False
        assert client.post('/semantic/index', json={'document_id': doc_id}).status_code == 200
        final = client.get('/semantic/status').json()
        assert final['documents'][0]['state'] == 'completed' and final['indexed'] == 5
        assert len(fake.calls) == 5
        assert local_only and all(local_only)
        assert 'private' not in str(final)
        with app.state.store.connection() as db:
            assert [tuple(row) for row in db.execute('SELECT entry_id,embedding FROM qa_vectors ORDER BY entry_id LIMIT 4')] == saved


@pytest.mark.parametrize('operation', ['delete', 'shutdown'])
def test_deletion_and_shutdown_suppress_inflight_index_writes_and_stale_completion(tmp_path, monkeypatch, operation):
    monkeypatch.setenv('COPILOT_AUTO_SEMANTIC_INDEX', '1')
    entered, release = threading.Event(), threading.Event()

    class HeldEmbedding(FakeEmbedding):
        def embed(self, texts):
            entered.set()
            assert release.wait(5)
            yield from super().embed(texts)

    app = create_app(tmp_path)
    app.state.semantic._embedder = HeldEmbedding()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        imported = client.post('/documents', files={'file': ('qa.md', b'Q: What is authentication?\nA: Identity verification.')})
        doc_id = imported.json()['id']
        try:
            assert entered.wait(5)
            if operation == 'delete':
                assert client.delete('/documents/' + doc_id).status_code == 200
            else:
                closing = executor.submit(app.state.indexing.close)
                assert app.state.semantic._stopping.wait(5)
                assert not closing.done()  # Native work is drained, not abandoned.
                assert client.post('/semantic/index', json={'document_id': doc_id, 'background': True}).status_code == 503
        finally:
            release.set()
        if operation == 'shutdown':
            closing.result(timeout=5)
        app.state.semantic.drain()
        status = client.get('/semantic/status').json()
        assert status['indexed'] == 0
        if operation == 'delete':
            assert status['documents'] == []
            assert client.post('/semantic/index', json={'document_id': doc_id}).status_code == 404
            with app.state.store.connection() as db:
                assert db.execute('SELECT COUNT(*) FROM semantic_index_state').fetchone()[0] == 0
        else:
            assert status['documents'][0]['state'] == 'failed'
            assert status['documents'][0]['error'] == 'interrupted'
            assert client.post('/semantic/index', json={'document_id': doc_id}).status_code == 503
            # A fresh backend preserves the document and reports an actionable interruption.
            with TestClient(create_app(tmp_path)) as restarted:
                assert restarted.get('/semantic/status').json()['documents'][0]['error'] == 'interrupted'
