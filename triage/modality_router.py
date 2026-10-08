
"""
triage/modality_router.py -- text-only boundary (OI-079, Sprint 6).

The runtime is TEXT-ONLY. This module does not add multimodal support; it makes the
boundary explicit: a request that carries (or claims to carry) image, audio, video,
file or other non-text input is refused at ingress instead of being silently
answered from its text alone, which would be misleading ("describe this image" with
the image dropped) and would leave cross-modal injection (ARCHITECTURE.md Stage 5 #6;
OWASP LLM01 multimodal injection) as an unexamined surface. Refusing removes the surface
instead of defending it.

It is a PURE function of the request payload: no model, no I/O, no session. The caller
(api/main.py) decides what to do with the verdict: refuse without invoking any stage,
and without charging session risk for the modality problem alone (owner decision).

What it checks (all deterministic):
  * the payload is a JSON object and `text` is a string. A non-string `text` (a list of
    content parts such as [{"type": "image_url", ...}], a number, an object) is non-text input;
  * `modality`, if declared, is "text";
  * no field from the known non-text set (image, audio, video, file(s), attachment(s),
    document(s), media, *_url variants) carries a non-empty value. Empty values (null, "",
    [], {}) are ignored so ordinary client libraries that always send such keys still work;
  * the text itself does not embed media as a base64 data URI (data:image/png;base64,...).

What it does NOT claim [JUDGMENT, stated limits]:
  * It cannot recognise every way a client might smuggle a binary under an unknown field
    name. The pipeline only ever reads `text`, so such fields are never processed; the
    refusal exists for clarity and fail-safety, not as a complete content scanner.
  * Text that merely MENTIONS images ("what is a PNG?") is ordinary text and is not refused.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

UNSUPPORTED_MODALITY = "unsupported_modality"
SUPPORTED_MODALITY = "text"

# Field names that carry non-text input in common request shapes (matched case-insensitively).
NON_TEXT_FIELDS = frozenset({
    "image", "images", "image_url", "image_urls",
    "audio", "audio_url", "voice",
    "video", "video_url",
    "file", "files", "attachment", "attachments",
    "document", "documents", "pdf", "media",
})

# An embedded media payload: a data URI with a media type and a real run of base64.
_DATA_URI = re.compile(r"data:(?:image|audio|video)/[\w.+-]+;base64,[A-Za-z0-9+/=]{32,}", re.IGNORECASE)
_SCAN_LIMIT = 100_000   # bound the work done on a huge string


@dataclass(frozen=True)
class ModalityVerdict:
    supported: bool
    reasons: tuple[str, ...] = ()      # stable codes for the audit trail; never echoed to the caller


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, (str, list, tuple, dict, set, bytes)) and len(value) == 0)


def check_modality(payload: object) -> ModalityVerdict:
    """Return whether the payload is plain text input. Never raises: anything it cannot
    interpret is treated as unsupported (fail closed)."""
    try:
        if not isinstance(payload, Mapping):
            return ModalityVerdict(False, ("payload_not_object",))

        reasons: list[str] = []

        text = payload.get("text")
        if not isinstance(text, str):
            reasons.append("text_not_string")

        declared = payload.get("modality")
        if declared is not None and not (isinstance(declared, str)
                                         and declared.strip().lower() == SUPPORTED_MODALITY):
            reasons.append("declared_modality_not_text")

        for key, value in payload.items():
            if isinstance(key, str) and key.lower() in NON_TEXT_FIELDS and not _is_empty(value):
                reasons.append(f"non_text_field:{key.lower()}")

        if isinstance(text, str) and _DATA_URI.search(text[:_SCAN_LIMIT]):
            reasons.append("embedded_media_data_uri")

        return ModalityVerdict(not reasons, tuple(reasons))
    except Exception:
        return ModalityVerdict(False, ("modality_check_error",))
