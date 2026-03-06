"""
Human behavior simulation for stealth browser sessions.

Generates realistic mouse, scroll, keyboard, and timing patterns that
pass behavioral anti-bot analysis (especially DataDome, which classifies
human vs. bot within 50ms using cursor trajectories, scroll velocity,
dwell times, click timing, and form-fill cadence).

Key algorithms:
    - Bézier curve cursor movement with Fitts's Law timing
    - Variable-velocity scroll with overshoot and reading pauses
    - Burst-pattern typing with occasional corrections
    - Per-domain behavior policies (e-commerce, search, article, form)

Research ref: Research.md §1.3 — "Traditional random delays are trivially
detectable. Modern behavioral analysis demands realistic interaction patterns."
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class BehaviorProfile(StrEnum):
    """Pre-configured behavior profiles for different site types."""
    ECOMMERCE = "ecommerce"   # Product catalogs: lots of scrolling, item clicks
    SEARCH = "search"         # Search results: rapid scanning, page navigation
    ARTICLE = "article"       # Content pages: slow scroll, reading pauses
    FORM = "form"             # Login/forms: typing focus, tab between fields
    DEFAULT = "default"       # Generic browsing behavior


@dataclass
class Point:
    """2D coordinate."""
    x: float
    y: float


@dataclass
class MousePath:
    """A generated mouse movement path."""
    points: list[Point]
    duration_ms: int
    target: Point


@dataclass
class ScrollAction:
    """A generated scroll action."""
    delta_y: int          # Pixels to scroll (negative = up)
    duration_ms: int      # Time to complete the scroll
    pause_after_ms: int   # Pause after scrolling (reading time)


@dataclass
class TypingAction:
    """A generated typing action for a single character."""
    char: str
    delay_ms: int         # Delay before typing this character
    is_correction: bool = False  # Whether this is a backspace correction


# =============================================================================
# Bézier curve generation for realistic cursor movement
# =============================================================================

def _bezier_point(t: float, p0: Point, p1: Point, p2: Point, p3: Point) -> Point:
    """Calculate a point on a cubic Bézier curve at parameter t."""
    u = 1 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0.x + 3 * uu * t * p1.x + 3 * u * tt * p2.x + ttt * p3.x
    y = uuu * p0.y + 3 * uu * t * p1.y + 3 * u * tt * p2.y + ttt * p3.y

    return Point(x, y)


def _fitts_law_time(distance: float, target_size: float = 20.0) -> float:
    """Calculate movement time using Fitts's Law.

    Fitts's Law: MT = a + b * log2(D/W + 1)
    Where D = distance, W = target width.

    Real humans move faster over long distances and decelerate
    near the target. This formula models that.

    Args:
        distance: Distance to target in pixels.
        target_size: Target element size in pixels.

    Returns:
        Movement time in milliseconds.
    """
    if distance <= 0:
        return 50.0

    a = 50.0   # Base time (ms) — minimum reaction time
    b = 150.0  # Scaling factor
    index_of_difficulty = math.log2(distance / target_size + 1)
    return a + b * index_of_difficulty


class BehaviorSimulator:
    """Generates human-like interaction patterns for browser sessions.

    Creates realistic cursor movements, scroll patterns, typing sequences,
    and timing that are statistically similar to real human behavior.
    This defeats behavioral anti-bot systems like DataDome.

    Usage:
        sim = BehaviorSimulator(profile=BehaviorProfile.ECOMMERCE)
        path = sim.generate_mouse_path(Point(100, 100), Point(500, 300))
        scrolls = sim.generate_scroll_sequence(page_height=3000)
        typing = sim.generate_typing("Hello World")
    """

    def __init__(self, profile: BehaviorProfile = BehaviorProfile.DEFAULT) -> None:
        self.profile = profile
        self._config = _PROFILE_CONFIGS.get(profile, _PROFILE_CONFIGS[BehaviorProfile.DEFAULT])

    def generate_mouse_path(
        self,
        start: Point,
        end: Point,
        target_size: float = 20.0,
    ) -> MousePath:
        """Generate a realistic Bézier curve mouse path.

        Uses cubic Bézier curves with Fitts's Law timing:
        - Acceleration toward target
        - Deceleration on approach
        - Slight overshoot and correction
        - Random micro-movements mid-path

        Args:
            start: Starting cursor position.
            end: Target cursor position.
            target_size: Size of the target element (affects timing).

        Returns:
            MousePath with interpolated points and duration.
        """
        distance = math.sqrt((end.x - start.x) ** 2 + (end.y - start.y) ** 2)
        duration_ms = int(_fitts_law_time(distance, target_size))

        # Add randomness to duration (±20%)
        duration_ms = int(duration_ms * random.uniform(0.8, 1.2))
        duration_ms = max(duration_ms, 30)

        # Generate control points with natural deviation
        mid_x = (start.x + end.x) / 2
        mid_y = (start.y + end.y) / 2
        spread = distance * 0.3  # Control point spread proportional to distance

        cp1 = Point(
            mid_x + random.gauss(0, spread * 0.3),
            mid_y + random.gauss(0, spread * 0.3),
        )
        cp2 = Point(
            (mid_x + end.x) / 2 + random.gauss(0, spread * 0.2),
            (mid_y + end.y) / 2 + random.gauss(0, spread * 0.2),
        )

        # Generate points along the curve
        num_points = max(int(distance / 5), 10)
        points = []

        for i in range(num_points + 1):
            t = i / num_points
            # Apply easing (slow start, fast middle, slow end)
            eased_t = _ease_in_out_cubic(t)
            point = _bezier_point(eased_t, start, cp1, cp2, end)

            # Add micro-jitter (real humans aren't perfectly smooth)
            point.x += random.gauss(0, 0.5)
            point.y += random.gauss(0, 0.5)

            points.append(point)

        # Optional overshoot and correction (30% chance)
        if random.random() < 0.3 and distance > 50:
            overshoot_dist = random.uniform(3, 8)
            direction = math.atan2(end.y - start.y, end.x - start.x)
            overshoot = Point(
                end.x + overshoot_dist * math.cos(direction),
                end.y + overshoot_dist * math.sin(direction),
            )
            points.append(overshoot)
            points.append(end)  # Correct back to target
            duration_ms += random.randint(30, 80)

        return MousePath(points=points, duration_ms=duration_ms, target=end)

    def generate_scroll_sequence(
        self,
        page_height: int = 3000,
        viewport_height: int = 900,
    ) -> list[ScrollAction]:
        """Generate a realistic scroll sequence for a page.

        Features:
        - Variable velocity (not constant speed)
        - Over-scroll and correction (humans overshoot)
        - Reading pauses at content sections
        - Direction changes (occasional scroll back up)
        """
        scrolls: list[ScrollAction] = []
        current_y = 0
        target_y = page_height - viewport_height

        cfg = self._config

        while current_y < target_y:
            # Variable scroll amount based on profile
            scroll_amount = random.randint(cfg["scroll_min"], cfg["scroll_max"])

            # Occasional over-scroll (20% chance)
            if random.random() < 0.2:
                scroll_amount = int(scroll_amount * 1.3)

            # Ensure we don't scroll past the bottom
            scroll_amount = min(scroll_amount, target_y - current_y)
            if scroll_amount <= 0:
                break

            duration = random.randint(cfg["scroll_duration_min"], cfg["scroll_duration_max"])

            # Reading pause
            if random.random() < cfg["reading_pause_chance"]:
                pause = random.randint(cfg["reading_pause_min"], cfg["reading_pause_max"])
            else:
                pause = random.randint(100, 400)

            scrolls.append(ScrollAction(
                delta_y=scroll_amount,
                duration_ms=duration,
                pause_after_ms=pause,
            ))

            current_y += scroll_amount

            # Occasional scroll back up (10% chance)
            if random.random() < 0.1 and current_y > viewport_height:
                back_amount = random.randint(50, 200)
                scrolls.append(ScrollAction(
                    delta_y=-back_amount,
                    duration_ms=random.randint(200, 500),
                    pause_after_ms=random.randint(500, 1500),
                ))
                current_y -= back_amount

        return scrolls

    def generate_typing(self, text: str) -> list[TypingAction]:
        """Generate realistic typing with burst patterns and corrections.

        Humans type in bursts (words), not character-by-character at
        uniform speed. Occasional backspace corrections are included.
        """
        actions: list[TypingAction] = []
        cfg = self._config

        i = 0
        while i < len(text):
            char = text[i]

            # Inter-keystroke delay
            if char == " ":
                # Pause between words
                delay = random.randint(cfg["word_pause_min"], cfg["word_pause_max"])
            else:
                # Character within a word (burst pattern)
                delay = random.randint(cfg["keystroke_min"], cfg["keystroke_max"])

            # Occasional typo + correction (3% chance per character)
            if random.random() < 0.03 and i < len(text) - 1:
                # Type wrong character
                wrong_char = chr(ord(char) + random.choice([-1, 1]))
                actions.append(TypingAction(
                    char=wrong_char,
                    delay_ms=delay,
                ))
                # Brief pause (recognizing the mistake)
                actions.append(TypingAction(
                    char="\b",  # Backspace
                    delay_ms=random.randint(100, 300),
                    is_correction=True,
                ))
                # Type correct character
                actions.append(TypingAction(
                    char=char,
                    delay_ms=random.randint(50, 150),
                ))
            else:
                actions.append(TypingAction(char=char, delay_ms=delay))

            i += 1

        return actions

    def generate_idle_delay(self) -> int:
        """Generate a realistic idle delay between actions (ms).

        Real users have a long tail of idle times (15-90 seconds)
        that bots never produce.
        """
        cfg = self._config
        if random.random() < cfg["long_idle_chance"]:
            return random.randint(15000, 90000)  # Long idle
        return random.randint(cfg["idle_min"], cfg["idle_max"])


def _ease_in_out_cubic(t: float) -> float:
    """Cubic easing function for smooth acceleration/deceleration."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2


# =============================================================================
# Per-profile configuration
# =============================================================================

_PROFILE_CONFIGS: dict[BehaviorProfile, dict[str, Any]] = {
    BehaviorProfile.ECOMMERCE: {
        "scroll_min": 100, "scroll_max": 400,
        "scroll_duration_min": 200, "scroll_duration_max": 600,
        "reading_pause_chance": 0.4,
        "reading_pause_min": 1000, "reading_pause_max": 5000,
        "keystroke_min": 50, "keystroke_max": 150,
        "word_pause_min": 100, "word_pause_max": 300,
        "idle_min": 2000, "idle_max": 8000,
        "long_idle_chance": 0.15,
    },
    BehaviorProfile.SEARCH: {
        "scroll_min": 200, "scroll_max": 500,
        "scroll_duration_min": 150, "scroll_duration_max": 400,
        "reading_pause_chance": 0.2,
        "reading_pause_min": 500, "reading_pause_max": 2000,
        "keystroke_min": 40, "keystroke_max": 120,
        "word_pause_min": 80, "word_pause_max": 250,
        "idle_min": 1000, "idle_max": 5000,
        "long_idle_chance": 0.05,
    },
    BehaviorProfile.ARTICLE: {
        "scroll_min": 50, "scroll_max": 200,
        "scroll_duration_min": 300, "scroll_duration_max": 800,
        "reading_pause_chance": 0.6,
        "reading_pause_min": 2000, "reading_pause_max": 10000,
        "keystroke_min": 60, "keystroke_max": 180,
        "word_pause_min": 150, "word_pause_max": 400,
        "idle_min": 3000, "idle_max": 15000,
        "long_idle_chance": 0.2,
    },
    BehaviorProfile.FORM: {
        "scroll_min": 30, "scroll_max": 100,
        "scroll_duration_min": 200, "scroll_duration_max": 500,
        "reading_pause_chance": 0.3,
        "reading_pause_min": 500, "reading_pause_max": 3000,
        "keystroke_min": 60, "keystroke_max": 200,
        "word_pause_min": 150, "word_pause_max": 500,
        "idle_min": 1000, "idle_max": 5000,
        "long_idle_chance": 0.1,
    },
    BehaviorProfile.DEFAULT: {
        "scroll_min": 100, "scroll_max": 350,
        "scroll_duration_min": 200, "scroll_duration_max": 600,
        "reading_pause_chance": 0.35,
        "reading_pause_min": 1000, "reading_pause_max": 5000,
        "keystroke_min": 50, "keystroke_max": 160,
        "word_pause_min": 100, "word_pause_max": 350,
        "idle_min": 2000, "idle_max": 10000,
        "long_idle_chance": 0.1,
    },
}
