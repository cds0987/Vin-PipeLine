from __future__ import annotations

from adapters.file_adapter import FileAdapter
from models.ingest_job import PermissionModel
from pipeline.run import run
from retrieval.service import RetrievalRequest, RetrievalService


def _index_doc(doc_id, file_uri, permission, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map(file_uri, doc_id=doc_id)
    job.permission = permission
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)


def test_retrieval_filters_by_public_permission(fake_ai_provider, vector_store, metadata_store):
    _index_doc(
        "doc-public",
        "data/sample/policy.txt",
        PermissionModel(visibility="public"),
        fake_ai_provider,
        vector_store,
        metadata_store,
    )
    service = RetrievalService(fake_ai_provider, vector_store, metadata_store)

    contexts = service.retrieve(
        RetrievalRequest(query="travel reimbursement", user_id="u1", user_roles=[], org_id=None, top_k=3)
    )

    assert len(contexts) == 1
    assert contexts[0]["source"] == "doc-public"


def test_retrieval_filters_private_document(fake_ai_provider, vector_store, metadata_store):
    _index_doc(
        "doc-private",
        "data/sample/policy.txt",
        PermissionModel(visibility="private", owner_id="owner-1"),
        fake_ai_provider,
        vector_store,
        metadata_store,
    )
    service = RetrievalService(fake_ai_provider, vector_store, metadata_store)

    denied = service.retrieve(
        RetrievalRequest(query="travel reimbursement", user_id="u2", user_roles=[], org_id=None, top_k=3)
    )
    allowed = service.retrieve(
        RetrievalRequest(query="travel reimbursement", user_id="owner-1", user_roles=[], org_id=None, top_k=3)
    )

    assert denied == []
    assert len(allowed) == 1


def test_retrieval_filters_org_role_and_user_access(fake_ai_provider, vector_store, metadata_store):
    _index_doc(
        "doc-org",
        "data/sample/faq.md",
        PermissionModel(visibility="org", org_id="org-1", allowed_roles=["legal"], allowed_users=["u-special"]),
        fake_ai_provider,
        vector_store,
        metadata_store,
    )
    service = RetrievalService(fake_ai_provider, vector_store, metadata_store)

    by_org = service.retrieve(
        RetrievalRequest(query="refund processing", user_id="u1", user_roles=[], org_id="org-1", top_k=3)
    )
    by_role = service.retrieve(
        RetrievalRequest(query="refund processing", user_id="u2", user_roles=["legal"], org_id="org-x", top_k=3)
    )
    by_user = service.retrieve(
        RetrievalRequest(query="refund processing", user_id="u-special", user_roles=[], org_id=None, top_k=3)
    )
    denied = service.retrieve(
        RetrievalRequest(query="refund processing", user_id="u3", user_roles=["sales"], org_id="org-x", top_k=3)
    )

    assert len(by_org) == 1
    assert len(by_role) == 1
    assert len(by_user) == 1
    assert denied == []
