"""RegComp API regression tests."""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from api import app

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_body(self, client):
        b = client.get("/health").json()
        assert b["status"] == "healthy"
        assert b["service"] == "RegComp"
        assert "llm_available" in b

class TestAssess:
    def test_assess_happy_path(self, client):
        r = client.post("/api/v1/compliance/assess",
                        json={"intent": "GDPR gap assessment for user data pipeline",
                              "workflow_id": "test-wf-001"})
        assert r.status_code == 200

    def test_assess_response_shape(self, client):
        b = client.post("/api/v1/compliance/assess",
                        json={"intent": "HIPAA audit of patient records",
                              "workflow_id": "test-wf-002"}).json()
        assert "assessment_id" in b
        assert "workflow_id"   in b
        assert "source"        in b
        assert "frameworks"    in b
        assert "gap_count"     in b
        assert "compliance_score" in b
        assert "summary"       in b

    def test_assess_source_is_mock_without_key(self, client):
        b = client.post("/api/v1/compliance/assess",
                        json={"intent": "SOX compliance check"}).json()
        assert b["source"] == "mock"

    def test_assess_id_is_deterministic(self, client):
        payload = {"intent": "PCI DSS gap", "workflow_id": "wf-det-001"}
        id1 = client.post("/api/v1/compliance/assess", json=payload).json()["assessment_id"]
        id2 = client.post("/api/v1/compliance/assess", json=payload).json()["assessment_id"]
        assert id1 == id2, "Same workflow+intent must produce same assessment_id"

    def test_gap_count_is_non_negative(self, client):
        b = client.post("/api/v1/compliance/assess",
                        json={"intent": "ISO 27001 controls"}).json()
        assert b["gap_count"] >= 0

    def test_compliance_score_in_range(self, client):
        b = client.post("/api/v1/compliance/assess",
                        json={"intent": "GDPR HIPAA SOX audit"}).json()
        assert 0 <= b["compliance_score"] <= 100

class TestFrameworks:
    def test_frameworks_endpoint(self, client):
        r = client.get("/api/v1/compliance/frameworks")
        assert r.status_code == 200
        b = r.json()
        assert "frameworks" in b
        assert "GDPR"    in b["frameworks"]
        assert "HIPAA"   in b["frameworks"]
        assert "SOX"     in b["frameworks"]
        assert "PCI DSS" in b["frameworks"]

class TestHistory:
    def test_history_returns_list(self, client):
        b = client.get("/api/v1/compliance/history").json()
        assert "assessments" in b
        assert "count"       in b
        assert isinstance(b["assessments"], list)
