import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, secret: str, signature_header: str | None) -> bool:
    
    if not signature_header:
        logger.warning("No signature header present")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning(f"Invalid signature format: {signature_header}")
        return False

    received_hash = signature_header[7:]  # Remove "sha256=" prefix

    computed_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    is_valid = hmac.compare_digest(computed_hash, received_hash)

    if not is_valid:
        logger.warning("Webhook signature verification failed")

    return is_valid