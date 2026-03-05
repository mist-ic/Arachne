"""
ScrapeWorkflow — Temporal durable workflow for the full scrape lifecycle.

This is the most impressive infrastructure piece in Phase 1. It demonstrates
understanding of durable execution: if the worker crashes mid-execution,
Temporal resumes at the exact activity on another worker. No lost work,
no duplicate requests.

The workflow orchestrates:
    1. Update job status → "running"
    2. Fetch URL via HTTP
    3. Store raw HTML in MinIO (Claim-Check pattern)
    4. Publish crawl result to Redpanda
    5. Basic CSS/XPath extraction (if schema provided)
    6. Update job status → "completed" or "failed"

Each step is a separate activity with its own timeout and retry policy.
Temporal handles the orchestration, state persistence, and failure recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Activity imports must use workflow.unsafe.imports() in Temporal
# to avoid sandbox restrictions
with workflow.unsafe.imports_passed_through():
    from activities import (
        ExtractionActivityResult,
        FetchResult,
        StoreResult,
        extract_with_selectors,
        fetch_url,
        publish_crawl_result,
        store_raw_html,
        update_job_status,
    )


@dataclass
class ScrapeWorkflowParams:
    """Input parameters for the scrape workflow.

    Passed from the API gateway when starting the workflow via
    temporal.start_workflow(ScrapeWorkflow.run, params, ...).
    """

    job_id: str
    url: str
    max_retries: int = 3
    headers: dict[str, str] | None = None
    extraction_schema: dict | None = None


@dataclass
class ScrapeWorkflowResult:
    """Output of a completed scrape workflow."""

    job_id: str
    url: str
    success: bool
    raw_html_ref: str | None = None
    result_ref: str | None = None
    status_code: int | None = None
    elapsed_ms: int = 0
    error: str | None = None


@workflow.defn
class ScrapeWorkflow:
    """Durable workflow orchestrating the full scrape lifecycle.

    If the worker crashes at ANY point, Temporal resumes execution
    on another worker from the exact activity that was in progress.
    Activity results are durably persisted — completed steps are
    never re-executed.

    Retry policy:
        - Retryable errors (403, 429, 503, network): exponential backoff
          with 1s initial → 2x coefficient → 60s max → up to max_retries
        - Non-retryable errors (404, 401, 407): immediate workflow failure

    Visible in Temporal UI as a workflow execution with full activity
    history, timings, and error details.
    """

    @workflow.run
    async def run(self, params: ScrapeWorkflowParams) -> ScrapeWorkflowResult:
        """Execute the complete scrape pipeline."""

        # Define the retry policy for HTTP fetching
        fetch_retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=params.max_retries,
            # These error types SKIP retries and fail immediately
            non_retryable_error_types=[
                "HTTP404Error",
                "HTTP401Error",
                "HTTP407Error",
            ],
        )

        # --- Step 1: Mark job as running ---
        await workflow.execute_activity(
            update_job_status,
            args=[params.job_id, "running"],
            start_to_close_timeout=timedelta(seconds=5),
        )

        try:
            # --- Step 2: Fetch the URL ---
            fetch_result: FetchResult = await workflow.execute_activity(
                fetch_url,
                args=[params.url, params.headers],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=fetch_retry_policy,
            )

            # --- Step 3: Store raw HTML in MinIO (Claim-Check) ---
            store_result: StoreResult = await workflow.execute_activity(
                store_raw_html,
                args=[params.job_id, fetch_result.html],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # --- Step 4: Publish crawl result to Redpanda ---
            await workflow.execute_activity(
                publish_crawl_result,
                args=[
                    params.job_id,
                    params.url,
                    True,  # success
                    fetch_result.status_code,
                    store_result.raw_html_ref,
                    fetch_result.elapsed_ms,
                    None,  # no error
                ],
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # --- Step 5: Extract data (if schema provided) ---
            result_ref = None
            if params.extraction_schema:
                extraction_result: ExtractionActivityResult = await workflow.execute_activity(
                    extract_with_selectors,
                    args=[
                        params.job_id,
                        store_result.raw_html_ref,
                        params.extraction_schema,
                        params.url,
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                result_ref = extraction_result.result_ref
                workflow.logger.info(
                    f"Extracted {extraction_result.field_count} fields "
                    f"in {extraction_result.elapsed_ms}ms for job {params.job_id}"
                )

            # --- Step 6: Mark job as completed ---
            await workflow.execute_activity(
                update_job_status,
                args=[
                    params.job_id,
                    "completed",
                    None,  # no error
                    store_result.raw_html_ref,
                    result_ref,
                ],
                start_to_close_timeout=timedelta(seconds=5),
            )

            return ScrapeWorkflowResult(
                job_id=params.job_id,
                url=params.url,
                success=True,
                raw_html_ref=store_result.raw_html_ref,
                result_ref=result_ref,
                status_code=fetch_result.status_code,
                elapsed_ms=fetch_result.elapsed_ms,
            )

        except Exception as e:
            # --- Failure path: mark job as failed ---
            error_msg = f"{type(e).__name__}: {e}"
            workflow.logger.error(f"Workflow failed for job {params.job_id}: {error_msg}")

            await workflow.execute_activity(
                update_job_status,
                args=[params.job_id, "failed", error_msg],
                start_to_close_timeout=timedelta(seconds=5),
            )

            # Publish failure event to Redpanda
            await workflow.execute_activity(
                publish_crawl_result,
                args=[
                    params.job_id,
                    params.url,
                    False,  # failure
                    0,  # no status code
                    None,  # no HTML ref
                    0,  # no elapsed time
                    error_msg,
                ],
                start_to_close_timeout=timedelta(seconds=5),
            )

            return ScrapeWorkflowResult(
                job_id=params.job_id,
                url=params.url,
                success=False,
                error=error_msg,
            )
