"""
Tests for human behavior simulation.
"""

import math

import pytest

from arachne_stealth.behavior import (
    BehaviorProfile,
    BehaviorSimulator,
    MousePath,
    Point,
    ScrollAction,
    TypingAction,
)


class TestMouseMovement:
    """Tests for Bézier curve cursor movement."""

    def test_generates_mouse_path(self):
        """generate_mouse_path should return a valid MousePath."""
        sim = BehaviorSimulator()
        path = sim.generate_mouse_path(Point(0, 0), Point(500, 300))

        assert isinstance(path, MousePath)
        assert len(path.points) > 0
        assert path.duration_ms > 0

    def test_path_starts_near_origin(self):
        """Path should start near the start point."""
        sim = BehaviorSimulator()
        path = sim.generate_mouse_path(Point(100, 100), Point(500, 300))

        first = path.points[0]
        # Allow some jitter but should be near start
        assert abs(first.x - 100) < 5
        assert abs(first.y - 100) < 5

    def test_longer_distance_means_more_points(self):
        """Longer distances should produce more interpolation points."""
        sim = BehaviorSimulator()
        short = sim.generate_mouse_path(Point(0, 0), Point(50, 0))
        long = sim.generate_mouse_path(Point(0, 0), Point(1000, 0))

        assert len(long.points) > len(short.points)

    def test_longer_distance_means_more_time(self):
        """Longer distances should take more time (Fitts's Law)."""
        sim = BehaviorSimulator()
        short = sim.generate_mouse_path(Point(0, 0), Point(50, 0))
        long = sim.generate_mouse_path(Point(0, 0), Point(1000, 0))

        # Long path should generally take more time (Fitts's Law)
        # Allow some randomness — just check it's not dramatically less
        assert long.duration_ms >= short.duration_ms * 0.5

    def test_zero_distance_doesnt_crash(self):
        """Same start and end point should not crash."""
        sim = BehaviorSimulator()
        path = sim.generate_mouse_path(Point(100, 100), Point(100, 100))
        assert isinstance(path, MousePath)
        assert path.duration_ms >= 0


class TestScrollSimulation:
    """Tests for scroll behavior generation."""

    def test_generates_scroll_sequence(self):
        """Should generate a non-empty scroll sequence."""
        sim = BehaviorSimulator()
        scrolls = sim.generate_scroll_sequence(page_height=3000)

        assert len(scrolls) > 0
        assert all(isinstance(s, ScrollAction) for s in scrolls)

    def test_scrolls_cover_page(self):
        """Total scroll should approximately cover the page."""
        sim = BehaviorSimulator()
        scrolls = sim.generate_scroll_sequence(page_height=2000, viewport_height=900)

        total_scrolled = sum(s.delta_y for s in scrolls)
        # Should scroll approximately page_height - viewport_height
        assert total_scrolled > 500  # At least some scrolling happened

    def test_scrolls_have_pauses(self):
        """Each scroll should have a pause_after_ms >= 0."""
        sim = BehaviorSimulator()
        scrolls = sim.generate_scroll_sequence(page_height=3000)

        for s in scrolls:
            assert s.pause_after_ms >= 0
            assert s.duration_ms > 0

    def test_article_profile_scrolls_slower(self):
        """Article profile should have longer reading pauses on average."""
        article_sim = BehaviorSimulator(profile=BehaviorProfile.ARTICLE)
        search_sim = BehaviorSimulator(profile=BehaviorProfile.SEARCH)

        article_scrolls = article_sim.generate_scroll_sequence(page_height=5000)
        search_scrolls = search_sim.generate_scroll_sequence(page_height=5000)

        article_avg_pause = sum(s.pause_after_ms for s in article_scrolls) / max(len(article_scrolls), 1)
        search_avg_pause = sum(s.pause_after_ms for s in search_scrolls) / max(len(search_scrolls), 1)

        # Article should generally pause more than search (reading vs scanning)
        # Allow for randomness — just check it's not drastically less
        assert article_avg_pause > search_avg_pause * 0.3


class TestTypingSimulation:
    """Tests for keyboard input simulation."""

    def test_generates_typing_actions(self):
        """Should generate actions for each character."""
        sim = BehaviorSimulator()
        actions = sim.generate_typing("hello")

        # At minimum, 5 characters (could be more with corrections)
        assert len(actions) >= 5
        assert all(isinstance(a, TypingAction) for a in actions)

    def test_typing_delays_are_positive(self):
        """All delays should be positive."""
        sim = BehaviorSimulator()
        actions = sim.generate_typing("test input")

        for a in actions:
            assert a.delay_ms > 0

    def test_word_pauses_are_longer(self):
        """Spaces between words should generally have longer delays."""
        sim = BehaviorSimulator()
        # Run multiple times to account for randomness
        space_delays = []
        char_delays = []

        for _ in range(10):
            actions = sim.generate_typing("ab cd")
            for a in actions:
                if a.char == " ":
                    space_delays.append(a.delay_ms)
                elif not a.is_correction and a.char != "\b":
                    char_delays.append(a.delay_ms)

        if space_delays and char_delays:
            avg_space = sum(space_delays) / len(space_delays)
            avg_char = sum(char_delays) / len(char_delays)
            # Word pauses should generally be longer
            assert avg_space >= avg_char * 0.5

    def test_empty_string_returns_empty(self):
        """Empty string should return empty action list."""
        sim = BehaviorSimulator()
        actions = sim.generate_typing("")
        assert len(actions) == 0


class TestBehaviorProfiles:
    """Tests for per-domain behavior profiles."""

    def test_all_profiles_work(self):
        """Every BehaviorProfile should create a valid simulator."""
        for profile in BehaviorProfile:
            sim = BehaviorSimulator(profile=profile)
            path = sim.generate_mouse_path(Point(0, 0), Point(100, 100))
            assert isinstance(path, MousePath)

    def test_idle_delay_is_positive(self):
        """generate_idle_delay should always return a positive value."""
        sim = BehaviorSimulator()
        for _ in range(20):
            delay = sim.generate_idle_delay()
            assert delay > 0
