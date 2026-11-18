"""Tests for input validation per Master Prompt Part 1 and Part 4 requirements.

Covers all 10 mandatory validation test cases:
1. Valid message.
2. Empty message.
3. Message longer than 200 characters.
4. Missing URL.
5. Multiple URLs.
6. Invalid URL.
7. URL without hostname.
8. Unsupported URL scheme.
9. Message with valid punctuation.
10. Message containing whitespace and a URL.
Plus extra field rejection (forbidding client platform selection).
"""

import pytest
from pydantic import ValidationError

from autopost_nexus.schemas.posting import (
    StandardPostingRequest,
    clean_candidate_url,
    is_valid_hostname,
    validate_posting_message,
)


class TestMessageValidationRules:
    """Direct unit tests for the reusable validation engine."""

    def test_case_1_valid_message(self):
        """Case 1: Standard valid message with content and exactly one CTA URL."""
        msg = "Check out our latest business platform and grow your online visibility. https://example.com"
        clean_text, url = validate_posting_message(msg)
        assert clean_text == msg
        assert url == "https://example.com"

    def test_case_2_empty_message(self):
        """Case 2: Reject completely empty message or whitespace only."""
        with pytest.raises(ValueError, match="cannot be empty or whitespace only"):
            validate_posting_message("")

        with pytest.raises(ValueError, match="cannot be empty or whitespace only"):
            validate_posting_message("    \t\n   ")

    def test_case_3_message_longer_than_200_chars(self):
        """Case 3: Reject message exceeding 200 characters including the URL."""
        # 185 chars prefix + space + 20 chars url = 206 chars > 200
        long_prefix = "A" * 185
        msg = f"{long_prefix} https://example.com"
        assert len(msg) > 200

        with pytest.raises(ValueError, match="exceeds maximum allowed length of 200"):
            validate_posting_message(msg)

    def test_case_4_missing_url(self):
        """Case 4: Reject message missing a CTA URL entirely."""
        msg = "Check out our amazing products and services available globally today!"
        with pytest.raises(ValueError, match="Message must contain exactly one CTA URL"):
            validate_posting_message(msg)

    def test_case_5_multiple_urls(self):
        """Case 5: Reject message containing more than one URL."""
        msg = "Visit our site https://first.example.com and check docs https://second.example.com"
        with pytest.raises(ValueError, match="Message contains 2 URLs. Exactly one CTA URL is permitted"):
            validate_posting_message(msg)

    def test_case_6_invalid_url(self):
        """Case 6: Reject malformed or invalid URL structures."""
        # Missing hostname / invalid chars
        msg1 = "Visit our portal https://"
        with pytest.raises(ValueError, match="missing a valid hostname"):
            validate_posting_message(msg1)

        msg2 = "Check out https://???"
        with pytest.raises(ValueError, match="missing a valid hostname"):
            validate_posting_message(msg2)

    def test_case_7_url_without_hostname(self):
        """Case 7: Reject URL without a valid hostname."""
        msg = "Download resource from https:///path/to/file.zip"
        with pytest.raises(ValueError, match="missing a valid hostname"):
            validate_posting_message(msg)

    def test_case_8_unsupported_url_scheme(self):
        """Case 8: Reject unsupported URL schemes (only HTTP and HTTPS allowed)."""
        msg_ftp = "Download file via ftp://files.example.com/archive.tar.gz"
        with pytest.raises(ValueError, match="Unsupported URL scheme 'ftp'"):
            validate_posting_message(msg_ftp)

        msg_mailto = "Contact us at mailto:support@example.com for help"
        with pytest.raises(ValueError, match="Unsupported URL scheme 'mailto'"):
            validate_posting_message(msg_mailto)

    def test_case_9_message_with_valid_punctuation(self):
        """Case 9: Correctly extract URL when surrounded by valid natural language punctuation."""
        msg = "Explore our exciting updates! (Available at: https://example.com/updates)."
        clean_text, url = validate_posting_message(msg)
        assert url == "https://example.com/updates"
        assert clean_text == msg

    def test_case_10_message_with_whitespace_and_url(self):
        """Case 10: Message containing extra spaces around text and URL."""
        msg = "   Special announcement:   https://example.com/promo   "
        clean_text, url = validate_posting_message(msg)
        assert clean_text == "Special announcement:   https://example.com/promo"
        assert url == "https://example.com/promo"


class TestHostnameAndUrlCleaning:
    """Unit tests for hostname validation and punctuation cleaning helpers."""

    def test_valid_hostnames(self):
        assert is_valid_hostname("example.com") is True
        assert is_valid_hostname("sub.example.co.uk") is True
        assert is_valid_hostname("localhost") is True
        assert is_valid_hostname("127.0.0.1") is True
        assert is_valid_hostname("192.168.1.1") is True

    def test_invalid_hostnames(self):
        assert is_valid_hostname("") is False
        assert is_valid_hostname("justoneword") is False
        assert is_valid_hostname("bad..dots") is False
        assert is_valid_hostname(".startswithdot.com") is False
        assert is_valid_hostname("999.999.999.999") is False

    def test_clean_candidate_url_brackets_and_punctuation(self):
        assert clean_candidate_url("https://example.com.") == "https://example.com"
        assert clean_candidate_url("https://example.com,") == "https://example.com"
        assert clean_candidate_url("https://example.com!") == "https://example.com"
        assert clean_candidate_url("https://example.com?") == "https://example.com"
        assert clean_candidate_url("(https://example.com)") == "https://example.com"
        assert clean_candidate_url("https://example.com)") == "https://example.com"


class TestStandardPostingRequestSchema:
    """Pydantic model validation tests for StandardPostingRequest."""

    def test_pydantic_accepts_valid_request(self):
        payload = {
            "message": "Check out our latest platform https://example.com"
        }
        req = StandardPostingRequest(**payload)
        assert req.message == payload["message"]

    def test_pydantic_rejects_extra_fields_including_platforms(self):
        """Master Prompt Part 1 & Part 4: Client must NOT select platforms; extra fields forbidden."""
        payload = {
            "message": "Check out our latest platform https://example.com",
            "platforms": ["twitter", "telegram"],
        }
        with pytest.raises(ValidationError) as exc_info:
            StandardPostingRequest(**payload)

        errors = exc_info.value.errors()
        assert any(e["type"] == "extra_forbidden" and e["loc"] == ("platforms",) for e in errors)

    def test_pydantic_rejects_empty_message(self):
        with pytest.raises(ValidationError):
            StandardPostingRequest(message="")

    def test_pydantic_rejects_missing_url(self):
        with pytest.raises(ValidationError):
            StandardPostingRequest(message="No URL here")

    def test_pydantic_rejects_over_200_chars(self):
        long_msg = "X" * 190 + " https://example.com"
        with pytest.raises(ValidationError):
            StandardPostingRequest(message=long_msg)
