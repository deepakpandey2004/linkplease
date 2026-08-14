import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, secret: str, signature_header: str | None) -> bool:
    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    received_hash = signature_header[7:]

    computed_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_hash, received_hash)