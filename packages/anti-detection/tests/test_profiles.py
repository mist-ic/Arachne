"""
Tests for browser fingerprint profiles and profile rotation.
"""

import pytest

from arachne_stealth.profiles import (
    ALL_PROFILES,
    CHROME_131_WIN,
    EDGE_131_WIN,
    FIREFOX_133_WIN,
    SAFARI_18_MAC,
    BrowserFamily,
    BrowserProfile,
    ProfileRotator,
)


class TestBrowserProfile:
    """Tests for individual browser profiles."""

    def test_all_profiles_exist(self):
        """All 7 pre-configured profiles should be available."""
        assert len(ALL_PROFILES) == 7

    def test_profile_has_required_fields(self):
        """Every profile must have name, family, impersonate, and user_agent."""
        for profile in ALL_PROFILES:
            assert profile.name, f"Profile missing name"
            assert profile.family in BrowserFamily
            assert profile.impersonate, f"{profile.name} missing impersonate string"
            assert profile.user_agent, f"{profile.name} missing user_agent"
            assert profile.weight > 0, f"{profile.name} has non-positive weight"

    def test_chrome_header_order(self):
        """Chrome profiles must have sec-ch-ua before User-Agent (Chromium order)."""
        headers = CHROME_131_WIN.build_headers()
        keys = list(headers.keys())

        assert "sec-ch-ua" in keys
        assert "User-Agent" in keys
        assert keys.index("sec-ch-ua") < keys.index("User-Agent"), \
            "Chrome: sec-ch-ua must come before User-Agent"

    def test_firefox_header_order(self):
        """Firefox profiles must have User-Agent before Accept (Firefox order)."""
        headers = FIREFOX_133_WIN.build_headers()
        keys = list(headers.keys())

        assert "User-Agent" in keys
        assert "Accept" in keys
        assert keys.index("User-Agent") < keys.index("Accept"), \
            "Firefox: User-Agent must come before Accept"

    def test_firefox_has_no_sec_ch_ua(self):
        """Firefox doesn't send sec-ch-ua headers (that's Chromium-only)."""
        headers = FIREFOX_133_WIN.build_headers()
        assert "sec-ch-ua" not in headers

    def test_safari_has_no_sec_ch_ua(self):
        """Safari doesn't send sec-ch-ua headers."""
        headers = SAFARI_18_MAC.build_headers()
        assert "sec-ch-ua" not in headers

    def test_edge_has_sec_ch_ua(self):
        """Edge (Chromium) must include sec-ch-ua headers."""
        headers = EDGE_131_WIN.build_headers()
        assert "sec-ch-ua" in headers
        assert "Microsoft Edge" in headers["sec-ch-ua"]

    def test_profile_immutability(self):
        """Profiles are frozen dataclasses — cannot be modified."""
        with pytest.raises(AttributeError):
            CHROME_131_WIN.name = "Modified"


class TestProfileRotator:
    """Tests for weighted profile rotation with session consistency."""

    def test_select_returns_profile(self):
        """select() should return a valid BrowserProfile."""
        rotator = ProfileRotator()
        profile = rotator.select()
        assert isinstance(profile, BrowserProfile)
        assert profile in ALL_PROFILES

    def test_session_consistency(self):
        """Same session_key should always return the same profile."""
        rotator = ProfileRotator()
        first = rotator.select(session_key="example.com")
        for _ in range(20):
            assert rotator.select(session_key="example.com") is first

    def test_different_sessions_can_differ(self):
        """Different session keys should (eventually) return different profiles.

        With 7 profiles, running 50 sessions should produce at least 2 distinct.
        """
        rotator = ProfileRotator()
        profiles_seen = set()
        for i in range(50):
            p = rotator.select(session_key=f"domain-{i}.com")
            profiles_seen.add(p.name)
        assert len(profiles_seen) >= 2, "All 50 sessions got the same profile (statistically improbable)"

    def test_release_session(self):
        """After releasing a session, the next select may return a different profile."""
        rotator = ProfileRotator()
        first = rotator.select(session_key="test.com")
        rotator.release_session("test.com")
        # After release, the key is no longer locked — new selection is random
        # We just verify it doesn't crash and returns a valid profile
        second = rotator.select(session_key="test.com")
        assert isinstance(second, BrowserProfile)

    def test_clear_all_sessions(self):
        """clear_all_sessions should remove all locks."""
        rotator = ProfileRotator()
        rotator.select(session_key="a.com")
        rotator.select(session_key="b.com")
        rotator.clear_all_sessions()
        assert len(rotator._session_profiles) == 0

    def test_no_session_key_returns_random(self):
        """Without session_key, each call returns a (possibly different) profile."""
        rotator = ProfileRotator()
        profiles_seen = set()
        for _ in range(50):
            p = rotator.select()
            profiles_seen.add(p.name)
        # Should see variety (not all the same)
        assert len(profiles_seen) >= 2

    def test_custom_profiles(self):
        """Rotator should work with a custom profile list."""
        custom = [CHROME_131_WIN, FIREFOX_133_WIN]
        rotator = ProfileRotator(profiles=custom)
        for _ in range(20):
            p = rotator.select()
            assert p in custom
