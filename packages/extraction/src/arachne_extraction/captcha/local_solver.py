"""
Local CAPTCHA solver using Qwen3-VL via Ollama.

Sends CAPTCHA screenshots to a local vision-language model for solving.
This is the cost-free tier of CAPTCHA solving — no API calls, no per-solve
charges. Requires a GPU for inference.

Supported CAPTCHA types:
    - IMAGE_GRID: Identifies which cells contain the target object
    - TEXT_MATH: Reads distorted text or solves math CAPTCHAs
    - SLIDER: Estimates slider offset distance
    - ROTATE: Estimates rotation angle

References:
    - Research.md §1.4: "Multimodal models (Qwen-VL) solve basic CAPTCHAs"
    - Phase3.md Step 4: Local CAPTCHA solving with vision models
"""

from __future__ import annotations

import base64
import time

import structlog

from arachne_extraction.captcha.solver import (
    CaptchaSolution,
    CaptchaSolver,
    CaptchaType,
    SolveMethod,
)

logger = structlog.get_logger(__name__)


# ============================================================================
# Prompt Templates (per CAPTCHA type)
# ============================================================================


_IMAGE_GRID_PROMPT = """You are solving a CAPTCHA. The image shows a grid of cells (usually 3x3 or 4x4).

Your task: Identify which cells contain "{target_object}" and return their positions.

Grid numbering (3x3 example):
  0 | 1 | 2
  3 | 4 | 5
  6 | 7 | 8

Rules:
- ONLY report cells that clearly contain the target object
- Return a JSON object with key "selected_cells" containing a list of cell numbers
- If unsure about a cell, DO NOT include it

Example response: {{"selected_cells": [0, 3, 6]}}"""


_TEXT_MATH_PROMPT = """You are solving a CAPTCHA. The image shows distorted text or a math problem.

Your task: Read the text or solve the math problem and return the answer.

Rules:
- For text CAPTCHAs: return the exact characters shown (letter case matters)
- For math CAPTCHAs: solve the equation and return the numerical result
- Be precise — one wrong character means failure

Return a JSON object with key "text" containing your answer.

Example responses:
- Text CAPTCHA: {{"text": "7G9Kp"}}
- Math CAPTCHA: {{"text": "42"}}"""


_SLIDER_PROMPT = """You are solving a slider CAPTCHA. The image shows a puzzle piece that needs to slide into the correct position.

Your task: Estimate the horizontal distance (in pixels) that the puzzle piece needs to move to fit into the target slot.

Look for:
- The puzzle piece outline on the left side
- The matching slot/shadow on the right side
- Estimate the pixel distance between them

Return a JSON object with key "offset_x" containing the pixel distance.

Example response: {{"offset_x": 142}}"""


_ROTATE_PROMPT = """You are solving a rotation CAPTCHA. The image shows a rotated picture that needs to be rotated to the correct orientation.

Your task: Estimate the clockwise rotation angle (in degrees) needed to make the image upright/correct.

Return a JSON object with key "angle" containing the angle in degrees (0-360).

Example response: {{"angle": 127}}"""


_PROMPTS: dict[CaptchaType, str] = {
    CaptchaType.IMAGE_GRID: _IMAGE_GRID_PROMPT,
    CaptchaType.RECAPTCHA_V2: _IMAGE_GRID_PROMPT,
    CaptchaType.HCAPTCHA: _IMAGE_GRID_PROMPT,
    CaptchaType.TEXT_MATH: _TEXT_MATH_PROMPT,
    CaptchaType.SLIDER: _SLIDER_PROMPT,
    CaptchaType.GEETEST: _SLIDER_PROMPT,
    CaptchaType.ROTATE: _ROTATE_PROMPT,
}


# ============================================================================
# Local Vision Solver
# ============================================================================


class LocalVisionSolver(CaptchaSolver):
    """CAPTCHA solver using a local vision-language model via Ollama.

    Sends CAPTCHA screenshots to Qwen3-VL (or compatible VLM) running
    locally on Ollama. Free inference — no per-solve API charges.

    Prerequisites:
        - Ollama running: `ollama serve`
        - Model pulled: `ollama pull qwen3-vl:32b`
        - GPU with ≥12GB VRAM (for 32B model)

    Usage:
        solver = LocalVisionSolver(
            model="qwen3-vl:32b",
            ollama_base_url="http://localhost:11434",
        )

        if await solver.is_available():
            solution = await solver.solve(
                image=screenshot_bytes,
                captcha_type=CaptchaType.IMAGE_GRID,
                extra_params={"target_object": "traffic lights"},
            )
    """

    def __init__(
        self,
        *,
        model: str = "qwen3-vl:32b",
        ollama_base_url: str = "http://localhost:11434",
        timeout_seconds: int = 30,
    ):
        self._model = model
        self._base_url = ollama_base_url.rstrip("/")
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return f"LocalVisionSolver({self._model})"

    async def is_available(self) -> bool:
        """Check if Ollama is running and the model is loaded."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                if response.status_code != 200:
                    return False

                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                available = any(self._model in m for m in models)

                if not available:
                    logger.info(
                        "local_vision_model_not_loaded",
                        model=self._model,
                        available_models=models,
                    )

                return available

        except Exception as e:
            logger.debug("ollama_unavailable", error=str(e))
            return False

    async def solve(
        self,
        image: bytes,
        captcha_type: CaptchaType,
        *,
        site_key: str | None = None,
        page_url: str | None = None,
        extra_params: dict | None = None,
    ) -> CaptchaSolution:
        """Solve a CAPTCHA using the local vision model.

        Sends the screenshot to Ollama's vision API with a type-specific
        prompt, then parses the structured response.
        """
        start_time = time.monotonic()
        extra_params = extra_params or {}

        # Get the appropriate prompt
        prompt_template = _PROMPTS.get(captcha_type, _TEXT_MATH_PROMPT)
        target_object = extra_params.get("target_object", "the target object")
        prompt = prompt_template.format(target_object=target_object)

        try:
            import httpx
            import json

            # Encode image as base64
            image_b64 = base64.b64encode(image).decode("utf-8")

            # Call Ollama vision API
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "images": [image_b64],
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 256,
                        },
                    },
                )

            if response.status_code != 200:
                raise RuntimeError(f"Ollama API error: {response.status_code}")

            result = response.json()
            raw_text = result.get("response", "")

            # Parse the JSON response
            solution_data = _parse_solution(raw_text, captcha_type)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            solved = bool(solution_data)
            confidence = 0.7 if solved else 0.0  # Vision models are ~70% on CAPTCHAs

            logger.info(
                "captcha_solved_locally",
                captcha_type=captcha_type,
                solved=solved,
                elapsed_ms=elapsed_ms,
                model=self._model,
            )

            return CaptchaSolution(
                solved=solved,
                captcha_type=captcha_type,
                method=SolveMethod.LOCAL_VISION,
                solution_data=solution_data,
                solve_time_ms=elapsed_ms,
                confidence=confidence,
                cost_usd=0.0,
            )

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(
                "local_captcha_solve_failed",
                captcha_type=captcha_type,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )
            return CaptchaSolution(
                solved=False,
                captcha_type=captcha_type,
                method=SolveMethod.LOCAL_VISION,
                solve_time_ms=elapsed_ms,
                error=str(e),
            )


# ============================================================================
# Response Parsing
# ============================================================================


def _parse_solution(raw_text: str, captcha_type: CaptchaType) -> dict:
    """Parse the VLM's response into structured solution data.

    Handles JSON extraction from potentially noisy model output.
    """
    import json
    import re

    # Try to extract JSON from the response
    json_match = re.search(r"\{[^{}]*\}", raw_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: try to parse specific patterns
    if captcha_type in (CaptchaType.IMAGE_GRID, CaptchaType.RECAPTCHA_V2, CaptchaType.HCAPTCHA):
        # Look for numbers that could be cell indices
        numbers = re.findall(r"\d+", raw_text)
        if numbers:
            cells = [int(n) for n in numbers if int(n) < 16]
            if cells:
                return {"selected_cells": cells}

    elif captcha_type == CaptchaType.TEXT_MATH:
        # The answer is probably the last word/number
        text = raw_text.strip().split()[-1] if raw_text.strip() else ""
        if text:
            return {"text": text}

    elif captcha_type in (CaptchaType.SLIDER, CaptchaType.GEETEST):
        # Look for a pixel offset number
        numbers = re.findall(r"\d+", raw_text)
        if numbers:
            offset = int(numbers[0])
            if 10 < offset < 500:  # Reasonable slider offset
                return {"offset_x": offset}

    elif captcha_type == CaptchaType.ROTATE:
        numbers = re.findall(r"\d+", raw_text)
        if numbers:
            angle = int(numbers[0])
            if 0 <= angle <= 360:
                return {"angle": angle}

    return {}
