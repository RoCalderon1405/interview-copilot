"""Small local semantic-index tests with fake vectors: no model download/network.

These prove persistence, exact priority and safe abstention, NOT real embedding accuracy.
"""
from __future__ import annotations

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
