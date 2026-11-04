"""Tests for avd_client.security — 100% branch coverage target."""

import logging

import pytest

from avd_client.security import (
    SecurityError,
    TokenRedactionFilter,
    validate_authorize_url,
    validate_feed_url,
    validate_hostname,
    validate_redirect_url,
    validate_token_shape,
    validate_upn,
)


class TestValidateTokenShape:
    def test_valid_jws_3_parts(self):
        assert validate_token_shape("eyJhbGc.eyJzdWI.sig123") == "eyJhbGc.eyJzdWI.sig123"

    def test_valid_jwe_5_parts(self):
        assert validate_token_shape("header.key.iv.cipher.tag") == "header.key.iv.cipher.tag"

    def test_valid_jwe_empty_key(self):
        # alg=dir has empty encrypted-key segment
        assert validate_token_shape("eyJhbGc..iv.ciphertext.tag") == "eyJhbGc..iv.ciphertext.tag"

    def test_strips_whitespace(self):
        assert validate_token_shape("  abc.def.ghi  ") == "abc.def.ghi"

    def test_empty_raises(self):
        with pytest.raises(SecurityError, match="Empty token"):
            validate_token_shape("")

    def test_whitespace_only_raises(self):
        with pytest.raises(SecurityError, match="Empty token"):
            validate_token_shape("   ")

    def test_too_long_raises(self):
        with pytest.raises(SecurityError, match="maximum length"):
            validate_token_shape("a" * 32769 + ".b.c")

    def test_max_length_ok(self):
        token = "a" * 16000 + ".b.c"
        assert validate_token_shape(token) == token

    def test_two_parts_raises(self):
        with pytest.raises(SecurityError, match="invalid shape"):
            validate_token_shape("only.two")

    def test_six_parts_raises(self):
        with pytest.raises(SecurityError, match="invalid shape"):
            validate_token_shape("a.b.c.d.e.f")

    def test_invalid_chars_raises(self):
        with pytest.raises(SecurityError, match="invalid shape"):
            validate_token_shape("abc.def.gh!@#")

    def test_padding_equals_allowed(self):
        assert validate_token_shape("abc=.def=.ghi=") == "abc=.def=.ghi="

    def test_newline_rejected(self):
        with pytest.raises(SecurityError, match="invalid shape"):
            validate_token_shape("abc.def.ghi\ninjected")


class TestValidateHostname:
    def test_valid_wvd(self):
        assert validate_hostname("host.wvd.microsoft.com") == "host.wvd.microsoft.com"

    def test_valid_cloudpc(self):
        assert validate_hostname("host.cloudpc.microsoft.com") == "host.cloudpc.microsoft.com"

    def test_subdomain(self):
        assert validate_hostname("a.b.wvd.microsoft.com") == "a.b.wvd.microsoft.com"

    def test_uppercase_normalized(self):
        assert validate_hostname("HOST.WVD.MICROSOFT.COM") == "host.wvd.microsoft.com"

    def test_trailing_dot_stripped(self):
        assert validate_hostname("host.wvd.microsoft.com.") == "host.wvd.microsoft.com"

    def test_empty_raises(self):
        with pytest.raises(SecurityError, match="Empty hostname"):
            validate_hostname("")

    def test_too_long_raises(self):
        with pytest.raises(SecurityError, match="maximum length"):
            validate_hostname("a" * 250 + ".wvd.microsoft.com")

    def test_idn_rejected(self):
        with pytest.raises(SecurityError, match="IDN"):
            validate_hostname("xn--abc.wvd.microsoft.com")

    def test_idn_subdomain_rejected(self):
        with pytest.raises(SecurityError, match="IDN"):
            validate_hostname("host.xn--evil.wvd.microsoft.com")

    def test_wrong_domain_rejected(self):
        with pytest.raises(SecurityError, match="not in allowlist"):
            validate_hostname("evil.example.com")

    def test_leading_hyphen_rejected(self):
        with pytest.raises(SecurityError, match="not in allowlist"):
            validate_hostname("-host.wvd.microsoft.com")

    def test_bare_suffix_rejected(self):
        with pytest.raises(SecurityError, match="not in allowlist"):
            validate_hostname("wvd.microsoft.com")


class TestValidateUpn:
    def test_valid(self):
        assert validate_upn("user@example.com") == "user@example.com"

    def test_empty_raises(self):
        with pytest.raises(SecurityError, match="Invalid UPN"):
            validate_upn("")

    def test_none_raises(self):
        with pytest.raises(SecurityError):
            validate_upn(None)

    def test_spaces_rejected(self):
        with pytest.raises(SecurityError, match="Invalid UPN"):
            validate_upn("user name@example.com")

    def test_too_long_rejected(self):
        with pytest.raises(SecurityError, match="Invalid UPN"):
            validate_upn("a" * 255 + "@x")


class TestValidateRedirectUrl:
    def test_valid(self):
        url = "ms-appx-web://microsoft.aad.brokerplugin/a85cf173?code=abc"
        assert validate_redirect_url(url) == url

    def test_wrong_scheme_raises(self):
        with pytest.raises(SecurityError, match="must start with"):
            validate_redirect_url("https://evil.com/steal")

    def test_empty_raises(self):
        with pytest.raises(SecurityError, match="Empty"):
            validate_redirect_url("")

    def test_control_chars_raises(self):
        with pytest.raises(SecurityError, match="control characters"):
            validate_redirect_url("ms-appx-web://microsoft.aad.brokerplugin/\r\ninjection")

    def test_too_long_raises(self):
        with pytest.raises(SecurityError, match="too long"):
            validate_redirect_url("ms-appx-web://microsoft.aad.brokerplugin/" + "a" * 9000)


class TestValidateFeedUrl:
    def test_valid_wvd(self):
        url = "https://rdweb.wvd.microsoft.com/api/arm/feeddiscovery"
        assert validate_feed_url(url) == url

    def test_valid_cloudpc(self):
        url = "https://something.cloudpc.microsoft.com/feed"
        assert validate_feed_url(url) == url

    def test_http_rejected(self):
        with pytest.raises(SecurityError, match="HTTPS"):
            validate_feed_url("http://rdweb.wvd.microsoft.com/api")

    def test_wrong_host_rejected(self):
        with pytest.raises(SecurityError, match="not allowed"):
            validate_feed_url("https://evil.example.com/api")

    def test_no_hostname_rejected(self):
        with pytest.raises(SecurityError, match="no hostname"):
            validate_feed_url("https:///path")


class TestValidateAuthorizeUrl:
    VALID = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"

    def test_valid(self):
        assert validate_authorize_url(self.VALID) == self.VALID

    def test_empty(self):
        with pytest.raises(SecurityError, match="Empty authorize"):
            validate_authorize_url("")

    def test_control_characters(self):
        with pytest.raises(SecurityError, match="control"):
            validate_authorize_url(self.VALID + "\x00")

    def test_too_long(self):
        with pytest.raises(SecurityError, match="too long"):
            validate_authorize_url("https://login.microsoftonline.com/" + "a" * 8192)

    def test_wrong_scheme(self):
        with pytest.raises(SecurityError, match="not a Microsoft"):
            validate_authorize_url("http://login.microsoftonline.com/x")

    def test_wrong_host(self):
        with pytest.raises(SecurityError, match="not a Microsoft"):
            validate_authorize_url("https://evil.example/x")


class TestTokenRedactionFilter:
    def test_redacts_jwt_in_msg(self):
        filt = TokenRedactionFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "token: eyJhbGciOiJ.eyJzdWI.sig", (), None
        )
        filt.filter(record)
        assert "eyJ" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_redacts_in_args(self):
        filt = TokenRedactionFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "val: %s",
            ("eyJhbGci.eyJsub.signature",), None
        )
        filt.filter(record)
        assert "[REDACTED]" in record.args[0]

    def test_no_false_positive(self):
        filt = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "normal message", (), None)
        filt.filter(record)
        assert record.msg == "normal message"

    def test_non_dict_non_tuple_args(self):
        filt = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "value: %s", None, None)
        record.args = ["a"]
        assert filt.filter(record) is True

    def test_redacts_5_part_jwe(self):
        filt = TokenRedactionFilter()
        jwe = "eyJhbGciOiJkaXIi..ivdata.ciphertext.authtag"
        record = logging.LogRecord("test", logging.INFO, "", 0, f"tok={jwe}", (), None)
        filt.filter(record)
        assert "eyJ" not in record.msg
