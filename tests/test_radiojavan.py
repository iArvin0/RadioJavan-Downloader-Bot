import pytest

from app.models import MediaCandidate
from app.radiojavan import (
    RadioJavanClient,
    UnsupportedLinkError,
    extract_url,
    normalize_input_url,
    public_page_url,
)


def test_extract_url():
    text = "listen https://rj.app/m/9v9gD8Oq?sid=123 please"
    assert extract_url(text) == "https://rj.app/m/9v9gD8Oq?sid=123"


def test_rejects_non_radiojavan_host():
    with pytest.raises(UnsupportedLinkError):
        normalize_input_url("https://example.com/song/test")


def test_normalizes_radiojavan_host():
    result = normalize_input_url("play.radiojavan.com/song/test")
    assert result == "https://play.radiojavan.com/song/test"


def test_candidate_order_prefers_320():
    client = RadioJavanClient()
    try:
        candidates = client._build_candidates("song", "SomeSong", [])
        assert isinstance(candidates[0], MediaCandidate)
        assert candidates[0].quality == "320 kbps"
        assert "/mp3-320/" in candidates[0].url
        assert any(candidate.quality == "256 kbps" for candidate in candidates)
    finally:
        import asyncio

        asyncio.run(client.client.aclose())


def test_short_m_url_identification():
    client = RadioJavanClient()
    try:
        media_type, media_id, _ = client._identify_media(
            "https://play.radiojavan.com/m/9v9gD8Oq", ""
        )
        assert media_type == "auto"
        assert media_id == "9v9gD8Oq"
    finally:
        import asyncio

        asyncio.run(client.client.aclose())


def test_rj_app_short_link_maps_without_network_request():
    result = public_page_url(
        "https://rj.app/m/ZEwR3oPv?sid=aa1d3490649e9594"
    )
    assert result == "https://play.radiojavan.com/m/ZEwR3oPv"


def test_rj_app_video_short_link_maps_without_tracking_query():
    result = public_page_url("https://rj.app/v/kPQpnQbn?sid=abc")
    assert result == "https://play.radiojavan.com/v/kPQpnQbn"
