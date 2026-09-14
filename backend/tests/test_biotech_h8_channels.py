"""WP4 · biotech_h8_channels 최소 fixture 테스트."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.scripts import biotech_h8_channels as mod


def test_fetch_pubmed_parses_count_and_ids():
    fake = {
        "esearchresult": {
            "count": "42",
            "idlist": ["12345", "67890"],
        }
    }
    m_resp = MagicMock()
    m_resp.json.return_value = fake
    m_resp.raise_for_status = MagicMock()
    with patch.object(mod.httpx, "Client") as m_client_cls:
        m_client = MagicMock()
        m_client.__enter__.return_value = m_client
        m_client.get.return_value = m_resp
        m_client_cls.return_value = m_client
        result = mod.fetch_pubmed("GLP-1", "2024/01/01", "2024/03/31")
    assert result == {"count": 42, "sample_pmids": ["12345", "67890"]}


def test_fetch_biorxiv_returns_records():
    fake = {
        "messages": [{"count": 30}],
        "collection": [{"title": "test paper"}, {"title": "another"}],
    }
    m_resp = MagicMock()
    m_resp.json.return_value = fake
    m_resp.raise_for_status = MagicMock()
    with patch.object(mod.httpx, "Client") as m_client_cls:
        m_client = MagicMock()
        m_client.__enter__.return_value = m_client
        m_client.get.return_value = m_resp
        m_client_cls.return_value = m_client
        result = mod.fetch_biorxiv("biorxiv", "2024-01-01", "2024-03-31")
    assert result["server"] == "biorxiv"
    assert result["returned_records"] == 2
    assert result["messages_count"] == 30
