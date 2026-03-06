"""
External CAPTCHA API solver and fallback chain.

When local vision solving fails or isn't available (no GPU), falls back
to external CAPTCHA solving services. Supports 2Captcha and CapSolver
as backends, with a configurable fallback chain.

Cost model:
    - 2Captcha: ~$2.99 per 1000 reCAPTCHA v2 solves
    - CapSolver: ~$2.50 per 1000 reCAPTCHA v2 solves
    - Both: ~60-120 seconds per solve (human workers)

References:
    - Phase3.md Step 6: External CAPTCHA API integration
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
# External API Solver
# ============================================================================


class ExternalAPISolver(CaptchaSolver):
    """CAPTCHA solver using external solving services.

    Wraps 2Captcha and CapSolver APIs behind the CaptchaSolver interface.
    Used as fallback when local vision solving fails or isn't available.

    Usage:
        solver = ExternalAPISolver(
            provider="2captcha",
            api_key="your-2captcha-key",
        )
        solution = await solver.solve(
            image=screenshot_bytes,
            captcha_type=CaptchaType.RECAPTCHA_V2,
            site_key="6Le...",
            page_url="https://example.com",
        )
    """

    def __init__(
        self,
        *,
        provider: str = "2captcha",
        api_key: str,
        timeout_seconds: int = 120,
        poll_interval_seconds: int = 5,
    ):
        self._provider = provider
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds

    @property
    def name(self) -> str:
        return f"ExternalAPISolver({self._provider})"

    async def is_available(self) -> bool:
        """Check if the external service is reachable and key is valid."""
        try:
            if self._provider == "2captcha":
                return await self._check_2captcha_balance()
            elif self._provider == "capsolver":
                return await self._check_capsolver_balance()
            return False
        except Exception as e:
            logger.debug("external_solver_unavailable", provider=self._provider, error=str(e))
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
        """Solve a CAPTCHA using the external API.

        For token-based CAPTCHAs (reCAPTCHA, hCaptcha), uses the site_key
        and page_url instead of the image. For image CAPTCHAs, sends the
        screenshot.
        """
        start_time = time.monotonic()

        try:
            if self._provider == "2captcha":
                result = await self._solve_2captcha(image, captcha_type, site_key, page_url, extra_params)
            elif self._provider == "capsolver":
                result = await self._solve_capsolver(image, captcha_type, site_key, page_url, extra_params)
            else:
                raise ValueError(f"Unknown provider: {self._provider}")

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "captcha_solved_externally",
                provider=self._provider,
                captcha_type=captcha_type,
                elapsed_ms=elapsed_ms,
            )

            return CaptchaSolution(
                solved=True,
                captcha_type=captcha_type,
                method=SolveMethod.EXTERNAL_API,
                solution_data=result,
                solve_time_ms=elapsed_ms,
                confidence=0.95,  # External services have high accuracy
                cost_usd=self._estimate_cost(captcha_type),
            )

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(
                "external_captcha_solve_failed",
                provider=self._provider,
                captcha_type=captcha_type,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )
            return CaptchaSolution(
                solved=False,
                captcha_type=captcha_type,
                method=SolveMethod.EXTERNAL_API,
                solve_time_ms=elapsed_ms,
                error=str(e),
            )

    # ========================================================================
    # 2Captcha Implementation
    # ========================================================================

    async def _check_2captcha_balance(self) -> bool:
        """Check 2Captcha account balance."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://2captcha.com/res.php",
                params={"key": self._api_key, "action": "getbalance", "json": 1},
            )
            data = response.json()
            balance = float(data.get("request", 0))
            logger.debug("2captcha_balance", balance=balance)
            return balance > 0.01

    async def _solve_2captcha(
        self,
        image: bytes,
        captcha_type: CaptchaType,
        site_key: str | None,
        page_url: str | None,
        extra_params: dict | None,
    ) -> dict:
        """Solve via 2Captcha API."""
        import asyncio
        import httpx

        extra_params = extra_params or {}

        # Build the request based on CAPTCHA type
        params: dict = {
            "key": self._api_key,
            "json": 1,
        }

        if captcha_type in (CaptchaType.RECAPTCHA_V2,) and site_key:
            # Token-based solving (no image needed)
            params.update({
                "method": "userrecaptcha",
                "googlekey": site_key,
                "pageurl": page_url or "",
            })
        elif captcha_type == CaptchaType.HCAPTCHA and site_key:
            params.update({
                "method": "hcaptcha",
                "sitekey": site_key,
                "pageurl": page_url or "",
            })
        else:
            # Image-based solving
            image_b64 = base64.b64encode(image).decode("utf-8")
            params.update({
                "method": "base64",
                "body": image_b64,
            })

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # Submit the CAPTCHA
            response = await client.post(
                "https://2captcha.com/in.php",
                data=params,
            )
            data = response.json()

            if data.get("status") != 1:
                raise RuntimeError(f"2Captcha submit failed: {data.get('request')}")

            task_id = data["request"]

            # Poll for the solution
            elapsed = 0
            while elapsed < self._timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval

                result_response = await client.get(
                    "https://2captcha.com/res.php",
                    params={
                        "key": self._api_key,
                        "action": "get",
                        "id": task_id,
                        "json": 1,
                    },
                )
                result_data = result_response.json()

                if result_data.get("status") == 1:
                    solution_text = result_data["request"]
                    return self._format_solution(solution_text, captcha_type)

                if result_data.get("request") != "CAPCHA_NOT_READY":
                    raise RuntimeError(f"2Captcha error: {result_data.get('request')}")

            raise TimeoutError(f"2Captcha solve timeout after {self._timeout}s")

    # ========================================================================
    # CapSolver Implementation
    # ========================================================================

    async def _check_capsolver_balance(self) -> bool:
        """Check CapSolver account balance."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.capsolver.com/getBalance",
                json={"clientKey": self._api_key},
            )
            data = response.json()
            balance = data.get("balance", 0)
            logger.debug("capsolver_balance", balance=balance)
            return float(balance) > 0.01

    async def _solve_capsolver(
        self,
        image: bytes,
        captcha_type: CaptchaType,
        site_key: str | None,
        page_url: str | None,
        extra_params: dict | None,
    ) -> dict:
        """Solve via CapSolver API."""
        import asyncio
        import httpx

        extra_params = extra_params or {}

        # Build the task based on CAPTCHA type
        task: dict = {}

        if captcha_type == CaptchaType.RECAPTCHA_V2 and site_key:
            task = {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": page_url or "",
                "websiteKey": site_key,
            }
        elif captcha_type == CaptchaType.HCAPTCHA and site_key:
            task = {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": page_url or "",
                "websiteKey": site_key,
            }
        else:
            # Image-based solving
            image_b64 = base64.b64encode(image).decode("utf-8")
            task = {
                "type": "ImageToTextTask",
                "body": image_b64,
            }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # Create the task
            response = await client.post(
                "https://api.capsolver.com/createTask",
                json={
                    "clientKey": self._api_key,
                    "task": task,
                },
            )
            data = response.json()

            if data.get("errorId", 0) != 0:
                raise RuntimeError(f"CapSolver submit failed: {data.get('errorDescription')}")

            task_id = data["taskId"]

            # Poll for the result
            elapsed = 0
            while elapsed < self._timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval

                result_response = await client.post(
                    "https://api.capsolver.com/getTaskResult",
                    json={
                        "clientKey": self._api_key,
                        "taskId": task_id,
                    },
                )
                result_data = result_response.json()

                status = result_data.get("status")
                if status == "ready":
                    solution = result_data.get("solution", {})
                    return self._format_capsolver_solution(solution, captcha_type)

                if status == "failed":
                    raise RuntimeError(f"CapSolver failed: {result_data.get('errorDescription')}")

            raise TimeoutError(f"CapSolver solve timeout after {self._timeout}s")

    # ========================================================================
    # Solution Formatting
    # ========================================================================

    def _format_solution(self, solution_text: str, captcha_type: CaptchaType) -> dict:
        """Format 2Captcha response into our solution format."""
        if captcha_type in (CaptchaType.RECAPTCHA_V2,):
            return {"g-recaptcha-response": solution_text}
        elif captcha_type == CaptchaType.HCAPTCHA:
            return {"h-captcha-response": solution_text}
        else:
            return {"text": solution_text}

    def _format_capsolver_solution(self, solution: dict, captcha_type: CaptchaType) -> dict:
        """Format CapSolver response into our solution format."""
        if captcha_type in (CaptchaType.RECAPTCHA_V2,):
            return {"g-recaptcha-response": solution.get("gRecaptchaResponse", "")}
        elif captcha_type == CaptchaType.HCAPTCHA:
            return {"h-captcha-response": solution.get("token", "")}
        else:
            return {"text": solution.get("text", "")}

    def _estimate_cost(self, captcha_type: CaptchaType) -> float:
        """Estimate the cost of solving this CAPTCHA type."""
        # Approximate per-solve costs (USD)
        cost_map = {
            CaptchaType.RECAPTCHA_V2: 0.003,
            CaptchaType.HCAPTCHA: 0.003,
            CaptchaType.IMAGE_GRID: 0.002,
            CaptchaType.TEXT_MATH: 0.001,
            CaptchaType.SLIDER: 0.002,
            CaptchaType.GEETEST: 0.004,
            CaptchaType.ROTATE: 0.002,
            CaptchaType.FUNCAPTCHA: 0.005,
        }
        return cost_map.get(captcha_type, 0.003)


# ============================================================================
# Fallback Chain
# ============================================================================


class CaptchaFallbackChain:
    """Cascading CAPTCHA solver: local → external → dead letter.

    Tries solvers in order of preference (cheapest first). If all solvers
    fail, returns an unsolvable result for the Evasion Router to handle
    (typically escalate to a higher stealth tier or abandon the request).

    Usage:
        chain = CaptchaFallbackChain(
            solvers=[
                LocalVisionSolver(model="qwen3-vl:32b"),
                ExternalAPISolver(provider="2captcha", api_key="..."),
            ]
        )
        solution = await chain.solve(image, captcha_type)
    """

    def __init__(self, solvers: list[CaptchaSolver]):
        self._solvers = solvers

    async def solve(
        self,
        image: bytes,
        captcha_type: CaptchaType,
        *,
        site_key: str | None = None,
        page_url: str | None = None,
        extra_params: dict | None = None,
    ) -> CaptchaSolution:
        """Try each solver in order until one succeeds.

        Returns the first successful solution, or an unsolvable result
        if all solvers fail.
        """
        for solver in self._solvers:
            # Check availability first (skip unavailable solvers)
            if not await solver.is_available():
                logger.debug("solver_unavailable", solver=solver.name)
                continue

            logger.info("trying_captcha_solver", solver=solver.name, captcha_type=captcha_type)

            solution = await solver.solve(
                image=image,
                captcha_type=captcha_type,
                site_key=site_key,
                page_url=page_url,
                extra_params=extra_params,
            )

            if solution.solved:
                logger.info(
                    "captcha_solved",
                    solver=solver.name,
                    captcha_type=captcha_type,
                    elapsed_ms=solution.solve_time_ms,
                    cost_usd=solution.cost_usd,
                )
                return solution

            logger.info(
                "solver_failed_trying_next",
                solver=solver.name,
                error=solution.error,
            )

        # All solvers failed — dead letter
        logger.warning(
            "all_captcha_solvers_failed",
            captcha_type=captcha_type,
            solvers_tried=[s.name for s in self._solvers],
        )

        return CaptchaSolution(
            solved=False,
            captcha_type=captcha_type,
            method=SolveMethod.UNSOLVABLE,
            error="All solvers exhausted",
        )
