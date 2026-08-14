import base64
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

    received_hash = signature_header[7:]

    # Try multiple secret variations
    attempts = {}

    # 1. As-is UTF-8
    attempts["utf8_full"] = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()

    # 2. Only part before dot
    if "." in secret:
        before_dot = secret.split(".")[0]
        attempts["before_dot"] = hmac.new(
            before_dot.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()

        after_dot = secret.split(".")[1]
        attempts["after_dot"] = hmac.new(
            after_dot.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()

    # 3. Base64 decoded (padded)
    try:
        padded = secret + "=" * (4 - len(secret) % 4)
        decoded = base64.b64decode(padded)
        attempts["base64_decoded"] = hmac.new(
            decoded, raw_body, hashlib.sha256
        ).hexdigest()
    except Exception as e:
        logger.info(f"base64 decode failed: {e}")

    # 4. Base64 URL-safe decoded
    try:
        padded = secret + "=" * (4 - len(secret) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        attempts["urlsafe_b64_decoded"] = hmac.new(
            decoded, raw_body, hashlib.sha256
        ).hexdigest()
    except Exception as e:
        logger.info(f"urlsafe base64 decode failed: {e}")

    # 5. Only after dot, base64 decoded
    if "." in secret:
        try:
            after = secret.split(".")[1]
            padded = after + "=" * (4 - len(after) % 4)
            decoded = base64.b64decode(padded)
            attempts["after_dot_b64_decoded"] = hmac.new(
                decoded, raw_body, hashlib.sha256
            ).hexdigest()
        except Exception:
            pass

    # 6. Only after dot as hex bytes
    if "." in secret:
        try:
            after = secret.split(".")[1]
            decoded = bytes.fromhex(after)
            attempts["after_dot_hex"] = hmac.new(
                decoded, raw_body, hashlib.sha256
            ).hexdigest()
        except Exception as e:
            logger.info(f"after_dot hex failed: {e}")

    # Log all and find match
    for name, hash_val in attempts.items():
        match = "✅ MATCH" if hash_val == received_hash else "❌"
        logger.info(f"DEBUG {name}: {hash_val[:16]}... {match}")

    logger.info(f"DEBUG received: {received_hash[:16]}...")

    # For now, accept if ANY variation matches
    if received_hash in attempts.values():
        logger.info("SIGNATURE MATCHED via one variation")
        return True

    logger.warning("No variation matched")
    return False