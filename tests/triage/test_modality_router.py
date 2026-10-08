
"""OI-079: text-only boundary. Pure-function tests; no FastAPI needed."""
import pytest

from triage.modality_router import NON_TEXT_FIELDS, UNSUPPORTED_MODALITY, check_modality

OK = {"text": "What is the capital of Japan?"}
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def reasons(payload):
    v = check_modality(payload)
    assert v.supported is False
    return v.reasons


# ---- plain text passes ----

@pytest.mark.parametrize("payload", [
    OK,
    {"text": "hi", "session_token": "v1.x.1.y", "confirmation_token": None},
    {"text": "hi", "modality": "text"},
    {"text": "hi", "modality": " TEXT "},
    {"text": "hi", "modality": None},
    {"text": "what is a PNG image file?"},                     # mentioning images is ordinary text
    {"text": "explain the data: URI scheme"},                  # not an embedded payload
    {"text": "see data:image/png;base64,abc for the format"},  # too short to be a real payload
])
def test_plain_text_is_supported(payload):
    v = check_modality(payload)
    assert v.supported is True and v.reasons == ()


@pytest.mark.parametrize("empty", [None, "", [], {}, ()])
def test_empty_attachment_fields_from_ordinary_clients_are_ignored(empty):
    assert check_modality({**OK, "image": empty, "attachments": empty, "audio": empty}).supported


def test_other_unknown_fields_are_ignored():
    assert check_modality({**OK, "temperature": 0.2, "user": "u"}).supported


# ---- non-text input is refused ----

@pytest.mark.parametrize("field", sorted(NON_TEXT_FIELDS))
def test_every_known_non_text_field_is_refused_when_populated(field):
    assert reasons({**OK, field: "payload"}) == (f"non_text_field:{field}",)


def test_field_names_are_matched_case_insensitively():
    assert reasons({**OK, "ImAgE": "x"}) == ("non_text_field:image",)


@pytest.mark.parametrize("value", [b"\x89PNG", "https://example.com/a.png", [{"url": "x"}], {"data": "x"}, 5, True])
def test_any_non_empty_value_in_a_non_text_field_counts(value):
    assert reasons({**OK, "image": value}) == ("non_text_field:image",)


@pytest.mark.parametrize("text", [
    [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": "x"}}],
    {"type": "audio"},
    12345,
    b"bytes",
    None,
])
def test_non_string_text_is_non_text_input(text):
    assert "text_not_string" in reasons({"text": text})


def test_missing_text_is_refused():
    assert reasons({"session_token": "t"}) == ("text_not_string",)


@pytest.mark.parametrize("declared", ["image", "audio", "video", "multimodal", "", 5, ["text"]])
def test_declaring_a_modality_other_than_text_is_refused(declared):
    assert "declared_modality_not_text" in reasons({**OK, "modality": declared})


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "audio/mpeg", "video/mp4", "IMAGE/PNG"])
def test_embedded_media_data_uri_is_refused(mime):
    assert reasons({"text": f"describe data:{mime};base64,{PNG_B64}"}) == ("embedded_media_data_uri",)


def test_several_problems_are_all_reported():
    r = reasons({"text": f"look data:image/png;base64,{PNG_B64}", "image": "x", "modality": "image"})
    assert set(r) == {"embedded_media_data_uri", "non_text_field:image", "declared_modality_not_text"}


# ---- robustness ----

@pytest.mark.parametrize("payload", [None, "text", 5, ["text"], b"x"])
def test_non_object_payload_is_refused(payload):
    assert reasons(payload) == ("payload_not_object",)


def test_never_raises_and_fails_closed_on_hostile_input():
    class Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")
    v = check_modality(Boom(text="x"))
    assert v.supported is False and v.reasons == ("modality_check_error",)


def test_a_huge_text_is_handled_without_scanning_unbounded():
    assert check_modality({"text": "a" * 5_000_000}).supported


def test_non_string_keys_do_not_crash():
    assert check_modality({**OK, 7: "x", None: "y"}).supported


def test_marker_constant_is_stable():
    # api/main.py and the audit trail key on this exact string.
    assert UNSUPPORTED_MODALITY == "unsupported_modality"
