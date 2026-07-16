import json

import pytest
import responses

from game_library_bridge.sources.itad import (
    BASE_URL,
    COLLECTION_API,
    WAITLIST_API,
    ItadClient,
    ItadError,
)

PAGE_URL = f"{BASE_URL}/uid/arcca/collection/"
WAIT_PAGE_URL = f"{BASE_URL}/uid/arcca/waitlist/"


def add_page(rsps, fixture_text, url=PAGE_URL):
    rsps.get(url, body=fixture_text("itad_page.html"), content_type="text/html")


@responses.activate
def test_token_extracted_and_sent(fixture_text, fixture_json):
    add_page(responses, fixture_text)
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=fixture_json("itad_collection_page0.json"))
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])

    games, warnings = ItadClient().fetch_collection("arcca")

    assert len(games) == 4
    assert warnings == []
    api_call = responses.calls[1].request
    assert api_call.headers["ITAD-SessionToken"] == "FAKE-test-token_1234567890abcdef"
    assert json.loads(api_call.body) == {"user": "arcca", "page": 0}


@responses.activate
def test_collection_paginates_until_empty(fixture_text, fixture_json):
    add_page(responses, fixture_text)
    page0 = fixture_json("itad_collection_page0.json")
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=page0)
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=page0)
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])

    games, _ = ItadClient().fetch_collection("arcca")

    assert len(games) == 8
    bodies = [json.loads(c.request.body)["page"] for c in responses.calls[1:]]
    assert bodies == [0, 1, 2]


@responses.activate
def test_waitlist_follows_has_next(fixture_text, fixture_json):
    add_page(responses, fixture_text, url=WAIT_PAGE_URL)
    responses.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page0.json"))
    responses.post(f"{BASE_URL}{WAITLIST_API}", json=fixture_json("itad_waitlist_page1.json"))

    games, warnings = ItadClient().fetch_waitlist("arcca")

    assert [g["title"] for g in games] == ["GRAVEN", "Hollow Knight: Silksong"]
    assert warnings == []


@responses.activate
def test_expired_token_is_reminted_once(fixture_text, fixture_json):
    add_page(responses, fixture_text)
    responses.post(f"{BASE_URL}{COLLECTION_API}", json={"status_code": 400}, status=400)
    add_page(responses, fixture_text)  # re-mint
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=fixture_json("itad_collection_page0.json"))
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])

    games, _ = ItadClient().fetch_collection("arcca")

    assert len(games) == 4


@responses.activate
def test_missing_token_raises(fixture_text):
    responses.get(PAGE_URL, body="<html><body>redesigned page</body></html>")

    with pytest.raises(ItadError, match="no session token"):
        ItadClient().fetch_collection("arcca")


@responses.activate
def test_profile_404_raises(fixture_text):
    responses.get(PAGE_URL, status=404)

    with pytest.raises(ItadError, match="not found"):
        ItadClient().fetch_collection("arcca")


@responses.activate
def test_malformed_entries_skipped_with_warning(fixture_text):
    add_page(responses, fixture_text)
    payload = {
        "good": {"id": "good", "title": "Good Game", "slug": "good-game"},
        "bad": {"id": "bad", "title": ""},
    }
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=payload)
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=[])

    games, warnings = ItadClient().fetch_collection("arcca")

    assert [g["id"] for g in games] == ["good"]
    assert len(warnings) == 1 and "malformed" in warnings[0]


@responses.activate
def test_unexpected_shape_raises(fixture_text):
    add_page(responses, fixture_text)
    responses.post(f"{BASE_URL}{COLLECTION_API}", json=["not", "empty"])

    with pytest.raises(ItadError, match="shape changed"):
        ItadClient().fetch_collection("arcca")


@responses.activate
def test_waitlist_shape_change_raises(fixture_text):
    add_page(responses, fixture_text, url=WAIT_PAGE_URL)
    responses.post(f"{BASE_URL}{WAITLIST_API}", json={"unexpected": True})

    with pytest.raises(ItadError, match="waitlist response shape"):
        ItadClient().fetch_waitlist("arcca")
