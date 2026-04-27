import time
import hmac
import hashlib
from src.config.settings import settings


# =========================
# TOKEN GENERATION
# =========================
def generate_token(file_name, expiry_minutes=60):
    """
    Generates a secure token for file download.

    Args:
        file_name: Unique file identifier
        expiry_minutes: Token expiry duration

    Returns:
        Token string (expiry:signature)
    """
    expiry = int(time.time()) + expiry_minutes * 60
    data = f"{file_name}:{expiry}"

    signature = hmac.new(
        settings.download_token_secret.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()

    return f"{expiry}:{signature}"


# =========================
# TOKEN VALIDATION
# =========================
def validate_token(file_name, token):
    """
    Validates token for secure file download.

    Args:
        file_name: File identifier
        token: Token string

    Returns:
        True if valid, False otherwise
    """
    try:
        expiry, signature = token.split(":")
        expiry = int(expiry)

        # Check expiry
        if expiry < time.time():
            return False

        data = f"{file_name}:{expiry}"

        expected = hmac.new(
            settings.download_token_secret.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison (secure)
        return hmac.compare_digest(signature, expected)

    except Exception:
        return False


# =========================
# QUERY VALIDATION (STEP 8)
# =========================
def validate_query(query: str) -> None:
    """
    Basic SQL protection.
    Allows only safe SELECT queries.
    """

    if not query or not query.strip():
        raise ValueError("Query cannot be empty")

    # Remove comments (single line and multi-line) before validation
    import re
    # Remove single line comments starting with --
    q_no_comments = re.sub(r'--.*', '', query)
    # Remove multi-line comments /* ... */
    q_no_comments = re.sub(r'/\*.*?\*/', '', q_no_comments, flags=re.DOTALL)
    
    q = q_no_comments.strip().lower()

    if not q:
        raise ValueError("Query contains only comments or whitespace")

    # Allow only SELECT queries
    if not q.startswith("select"):
        raise Exception("Only SELECT queries are allowed")

    # Block dangerous operations
    forbidden_keywords = [
        "drop",
        "delete",
        "truncate",
        "alter",
        "update",
        "insert",
        "exec",
        "execute",
        "merge"
    ]

    for keyword in forbidden_keywords:
        if re.search(rf'\b{keyword}\b', q):
            raise Exception(f"Forbidden keyword detected: {keyword.upper()}")

    # Prevent multiple statements
    if ";" in q:
        raise Exception("Multiple SQL statements are not allowed")

    return None
