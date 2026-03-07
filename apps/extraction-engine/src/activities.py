"""
Temporal activities for the AI extraction engine.

Each activity is retryable and idempotent. They execute on the
"extract-ai" task queue and are called from ScrapeWorkflow (worker-http)
or directly by the API gateway.

Activities:
    extract_with_llm     — Full AI extraction pipeline (with vision fallback)
    extract_with_vision   — Vision-only extraction from screenshots
    discover_page_schema — Auto-schema discovery for unknown sites
    solve_page_captcha   — CAPTCHA solving (local → external fallback)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


# ============================================================================
# Activity Data Classes (must be serializable)
# ============================================================================


@dataclass
class LLMExtractionInput:
    """Input for the extract_with_llm activity."""

    job_id: str
    raw_html_ref: str  # MinIO reference to raw HTML
    url: str
    extraction_schema: dict | None = None  # Pydantic schema as dict
    model_preference: str | None = None  # Override model selection
    cost_mode: str | None = None  # "minimize" | "balanced" | "accuracy"


@dataclass
class LLMExtractionResult:
    """Output of the extract_with_llm activity."""

    result_ref: str  # MinIO reference to extraction result
    field_count: int
    elapsed_ms: int
    model_used: str
    tokens_input: int = 0
    tokens_output: int = 0
    estimated_cost_usd: float = 0.0
    confidence: float = 0.0
    extraction_method: str = "llm"


@dataclass
class VisionExtractionInput:
    """Input for the extract_with_vision activity."""

    job_id: str
    url: str
    extraction_schema: dict | None = None
    screenshot_ref: str | None = None  # Pre-captured screenshot in MinIO
    model_preference: str | None = None


@dataclass
class VisionExtractionResult:
    """Output of the extract_with_vision activity."""

    result_ref: str
    field_count: int
    elapsed_ms: int
    model_used: str
    confidence: float = 0.0
    extraction_method: str = "vision"
    screenshot_ref: str = ""


@dataclass
class SchemaDiscoveryInput:
    """Input for the discover_page_schema activity."""

    job_id: str
    raw_html_ref: str  # MinIO reference to raw HTML
    url: str
    model: str | None = None


@dataclass
class SchemaDiscoveryResult:
    """Output of the discover_page_schema activity."""

    entity_type: str
    field_count: int
    is_listing: bool
    estimated_entity_count: int
    confidence: float
    schema_json: str  # JSON serialized DiscoveredSchema
    pydantic_model_code: str  # Generated Pydantic model as Python code


@dataclass
class CaptchaSolveInput:
    """Input for the solve_page_captcha activity."""

    job_id: str
    screenshot_ref: str  # MinIO reference to CAPTCHA screenshot
    captcha_type: str  # CaptchaType value
    site_key: str | None = None
    page_url: str | None = None


@dataclass
class CaptchaSolveResult:
    """Output of the solve_page_captcha activity."""

    solved: bool
    solution_data: dict
    method: str  # "local_vision" | "external_api" | "unsolvable"
    solve_time_ms: int
    cost_usd: float = 0.0


# ============================================================================
# Activities
# ============================================================================


@activity.defn
async def extract_with_llm(params: LLMExtractionInput) -> LLMExtractionResult:
    """Full AI extraction pipeline.

    Pipeline: MinIO HTML → preprocess → route model → extract → validate → store

    1. Pull raw HTML from MinIO (Claim-Check)
    2. Preprocess: prune DOM → convert HTML to Markdown
    3. Route to optimal model based on complexity
    4. Extract structured data using instructor/Pydantic
    5. Store results in MinIO and PostgreSQL
    6. Return extraction metadata

    This activity runs on the "extract-ai" task queue and is called when
    LLM-based extraction is requested (vs css_xpath extraction from worker-http).
    """
    start = perf_counter()

    activity.logger.info(f"Starting LLM extraction for job {params.job_id}")

    # Step 1: Pull raw HTML from MinIO
    from arachne_storage.minio_client import get_minio_client

    minio = get_minio_client()
    raw_html = await minio.get_object_text(params.raw_html_ref)

    # Step 2: Preprocess (prune DOM, convert to Markdown)
    from arachne_extraction.preprocessor import preprocess

    preprocess_result = preprocess(raw_html, extract_metadata=True)

    activity.logger.info(
        f"Preprocessed: {preprocess_result.raw_char_count} chars → "
        f"{preprocess_result.markdown_char_count} chars "
        f"({preprocess_result.reduction_ratio:.1f}x reduction)"
    )

    # Step 3: Route to optimal model and extract
    from config import ExtractionEngineSettings

    settings = ExtractionEngineSettings()

    from arachne_extraction.model_router import CostConfig, CostMode, ExtractionRouter

    cost_config = CostConfig(
        cost_mode=CostMode(params.cost_mode or settings.cost_mode),
        max_cost_per_page_usd=settings.max_cost_per_page_usd,
        max_latency_ms=settings.max_latency_ms,
    )

    router = ExtractionRouter(
        cost_config=cost_config,
        api_keys=settings.get_api_keys(),
        ollama_base_url=settings.ollama_base_url,
    )

    # Build the extraction schema (Pydantic model)
    if params.extraction_schema:
        # User provided a schema — use it directly
        from pydantic import create_model, Field as PydanticField

        fields = {}
        for name, config in params.extraction_schema.get("fields", {}).items():
            field_type = config.get("type", "str")
            type_map = {"str": str, "int": int, "float": float, "bool": bool}
            python_type = type_map.get(field_type, str)
            fields[name] = (python_type | None, PydanticField(default=None))

        schema_model = create_model("ExtractionTarget", **fields)
    else:
        # No schema provided — use auto-discovery
        from arachne_extraction.schema_discovery import (
            discover_schema,
            generate_pydantic_model,
        )

        discovered = await discover_schema(
            preprocess_result.markdown,
            html=raw_html,
            model=params.model_preference or settings.default_model,
            api_key=settings.gemini_api_key,
        )
        schema_model = generate_pydantic_model(discovered)

    # Step 4: Extract with the router
    from urllib.parse import urlparse

    domain = urlparse(params.url).netloc if params.url else None

    extraction_output = await router.extract(
        markdown=preprocess_result.markdown,
        schema=schema_model,
        url=params.url,
        domain=domain,
    )

    # Step 5: Vision fallback if confidence is low
    VISION_FALLBACK_THRESHOLD = 0.5
    final_data = extraction_output.data
    extraction_method = extraction_output.extraction_method

    if extraction_output.confidence < VISION_FALLBACK_THRESHOLD:
        activity.logger.info(
            f"Low confidence ({extraction_output.confidence:.2f}) for job {params.job_id}, "
            f"triggering vision fallback"
        )

        try:
            from arachne_extraction.vision_extractor import (
                VisionExtractor,
                VisionExtractionConfig,
                capture_screenshot,
            )
            from arachne_extraction.result_merger import ResultMerger

            # Capture screenshot
            screenshot_bytes, screenshot_ref = await capture_screenshot(
                url=params.url,
                minio_client=minio,
                job_id=params.job_id,
            )

            # Vision extraction
            vision_config = VisionExtractionConfig(
                ollama_base_url=settings.ollama_base_url,
                api_key=settings.gemini_api_key,
            )
            vision_extractor = VisionExtractor(config=vision_config)
            vision_output = await vision_extractor.extract_from_screenshot(
                screenshot=screenshot_bytes,
                schema=schema_model,
                url=params.url,
            )

            # Merge HTML + vision results
            if vision_output.data is not None:
                merger = ResultMerger()
                merge_result = merger.merge(
                    html_result=extraction_output.data,
                    vision_result=vision_output.data,
                    schema=schema_model,
                    html_confidence=extraction_output.confidence,
                    vision_confidence=vision_output.confidence,
                )

                if merge_result.merged_data is not None:
                    final_data = merge_result.merged_data
                    extraction_method = "llm+vision"
                    activity.logger.info(
                        f"Vision merge complete: {merge_result.fields_agreed} agreed, "
                        f"{merge_result.fields_from_vision} from vision, "
                        f"{merge_result.fields_conflicted} conflicts"
                    )

        except Exception as vision_err:
            activity.logger.warning(
                f"Vision fallback failed for job {params.job_id}: {vision_err}"
            )

    # Step 6: Store results in MinIO
    result_data = {
        "job_id": params.job_id,
        "source_url": params.url,
        "extracted_data": final_data.model_dump() if final_data else {},
        "model_used": extraction_output.model_used,
        "tokens_input": extraction_output.tokens_input,
        "tokens_output": extraction_output.tokens_output,
        "estimated_cost_usd": extraction_output.estimated_cost_usd,
        "confidence": extraction_output.confidence,
        "extraction_method": extraction_method,
        "cascade_path": extraction_output.cascade_path,
        "metadata": preprocess_result.metadata,
    }

    result_json = json.dumps(result_data, indent=2, default=str)
    result_ref = f"minio://arachne-results/extraction/{params.job_id}/llm_result.json"
    await minio.put_object(result_ref, result_json.encode())

    elapsed_ms = int((perf_counter() - start) * 1000)

    field_count = len(final_data.model_fields) if final_data else 0

    activity.logger.info(
        f"LLM extraction complete for job {params.job_id}: "
        f"{field_count} fields, {extraction_output.model_used}, "
        f"{extraction_output.confidence:.2f} confidence, "
        f"${extraction_output.estimated_cost_usd:.4f} cost"
    )

    return LLMExtractionResult(
        result_ref=result_ref,
        field_count=field_count,
        elapsed_ms=elapsed_ms,
        model_used=extraction_output.model_used,
        tokens_input=extraction_output.tokens_input,
        tokens_output=extraction_output.tokens_output,
        estimated_cost_usd=extraction_output.estimated_cost_usd,
        confidence=extraction_output.confidence,
        extraction_method=extraction_method,
    )


@activity.defn
async def extract_with_vision(params: VisionExtractionInput) -> VisionExtractionResult:
    """Vision-only extraction from a page screenshot.

    Captures a screenshot (or uses a pre-captured one) and extracts
    structured data using a vision model. Used when HTML extraction
    is completely unavailable or the DOM is obfuscated.
    """
    start = perf_counter()

    activity.logger.info(f"Starting vision extraction for job {params.job_id}")

    from arachne_storage.minio_client import get_minio_client

    minio = get_minio_client()

    # Get or capture screenshot
    if params.screenshot_ref:
        screenshot_bytes = await minio.get_object_bytes(params.screenshot_ref)
        screenshot_ref = params.screenshot_ref
    else:
        from arachne_extraction.vision_extractor import capture_screenshot

        screenshot_bytes, screenshot_ref = await capture_screenshot(
            url=params.url,
            minio_client=minio,
            job_id=params.job_id,
        )

    # Build schema model
    if params.extraction_schema:
        from pydantic import create_model, Field as PydanticField

        fields = {}
        for name, config in params.extraction_schema.get("fields", {}).items():
            field_type = config.get("type", "str")
            type_map = {"str": str, "int": int, "float": float, "bool": bool}
            python_type = type_map.get(field_type, str)
            fields[name] = (python_type | None, PydanticField(default=None))

        schema_model = create_model("ExtractionTarget", **fields)
    else:
        from pydantic import create_model, Field as PydanticField

        # Generic schema for auto-discovery
        schema_model = create_model(
            "GenericExtraction",
            title=(str | None, PydanticField(default=None)),
            description=(str | None, PydanticField(default=None)),
            content=(str | None, PydanticField(default=None)),
        )

    # Extract with vision
    from config import ExtractionEngineSettings

    settings = ExtractionEngineSettings()

    from arachne_extraction.vision_extractor import VisionExtractor, VisionExtractionConfig

    vision_config = VisionExtractionConfig(
        ollama_base_url=settings.ollama_base_url,
        api_key=settings.gemini_api_key,
        local_model=params.model_preference or "qwen3-vl",
    )
    extractor = VisionExtractor(config=vision_config)
    output = await extractor.extract_from_screenshot(
        screenshot=screenshot_bytes,
        schema=schema_model,
        url=params.url,
    )

    # Store results
    result_data = {
        "job_id": params.job_id,
        "source_url": params.url,
        "extracted_data": output.data.model_dump() if output.data else {},
        "model_used": output.model_used,
        "confidence": output.confidence,
        "extraction_method": "vision",
    }

    result_json = json.dumps(result_data, indent=2, default=str)
    result_ref = f"minio://arachne-results/extraction/{params.job_id}/vision_result.json"
    await minio.put_object(result_ref, result_json.encode())

    elapsed_ms = int((perf_counter() - start) * 1000)
    field_count = len(output.data.model_fields) if output.data else 0

    activity.logger.info(
        f"Vision extraction complete for job {params.job_id}: "
        f"{field_count} fields, {output.model_used}, "
        f"{output.confidence:.2f} confidence"
    )

    return VisionExtractionResult(
        result_ref=result_ref,
        field_count=field_count,
        elapsed_ms=elapsed_ms,
        model_used=output.model_used,
        confidence=output.confidence,
        extraction_method="vision",
        screenshot_ref=screenshot_ref,
    )


@activity.defn
async def discover_page_schema(params: SchemaDiscoveryInput) -> SchemaDiscoveryResult:
    """Auto-discover extraction schema for a page.

    Analyzes page structure and content to propose a typed Pydantic schema.
    The discovered schema can be cached per-domain for reuse.
    """
    activity.logger.info(f"Starting schema discovery for job {params.job_id}")

    # Pull raw HTML from MinIO
    from arachne_storage.minio_client import get_minio_client

    minio = get_minio_client()
    raw_html = await minio.get_object_text(params.raw_html_ref)

    # Preprocess
    from arachne_extraction.preprocessor import preprocess

    preprocess_result = preprocess(raw_html, extract_metadata=True)

    # Discover schema
    from config import ExtractionEngineSettings

    settings = ExtractionEngineSettings()

    from arachne_extraction.schema_discovery import discover_schema

    schema = await discover_schema(
        preprocess_result.markdown,
        html=raw_html,
        model=params.model or settings.default_model,
        api_key=settings.gemini_api_key,
    )

    # Generate Pydantic model code for the API response
    model_code = _generate_model_code(schema)

    return SchemaDiscoveryResult(
        entity_type=schema.entity_type,
        field_count=len(schema.fields),
        is_listing=schema.is_listing,
        estimated_entity_count=schema.estimated_entity_count,
        confidence=schema.confidence,
        schema_json=schema.model_dump_json(),
        pydantic_model_code=model_code,
    )


@activity.defn
async def solve_page_captcha(params: CaptchaSolveInput) -> CaptchaSolveResult:
    """Solve a CAPTCHA detected during scraping.

    Uses the fallback chain: local vision → external API → unsolvable.
    Called by the Evasion Router when a CAPTCHA is encountered.
    """
    activity.logger.info(
        f"Starting CAPTCHA solving for job {params.job_id}, "
        f"type={params.captcha_type}"
    )

    # Pull screenshot from MinIO
    from arachne_storage.minio_client import get_minio_client

    minio = get_minio_client()
    screenshot_bytes = await minio.get_object_bytes(params.screenshot_ref)

    # Build the fallback chain
    from config import ExtractionEngineSettings

    settings = ExtractionEngineSettings()
    solvers = []

    # Try local vision first (free)
    from arachne_extraction.captcha.local_solver import LocalVisionSolver

    solvers.append(LocalVisionSolver(
        model=settings.captcha_local_model,
        ollama_base_url=settings.ollama_base_url,
    ))

    # External API fallback
    if settings.captcha_2captcha_key:
        from arachne_extraction.captcha.api_solver import ExternalAPISolver

        solvers.append(ExternalAPISolver(
            provider="2captcha",
            api_key=settings.captcha_2captcha_key,
        ))

    if settings.captcha_capsolver_key:
        from arachne_extraction.captcha.api_solver import ExternalAPISolver

        solvers.append(ExternalAPISolver(
            provider="capsolver",
            api_key=settings.captcha_capsolver_key,
        ))

    from arachne_extraction.captcha.api_solver import CaptchaFallbackChain
    from arachne_extraction.captcha.solver import CaptchaType

    chain = CaptchaFallbackChain(solvers=solvers)
    solution = await chain.solve(
        image=screenshot_bytes,
        captcha_type=CaptchaType(params.captcha_type),
        site_key=params.site_key,
        page_url=params.page_url,
    )

    return CaptchaSolveResult(
        solved=solution.solved,
        solution_data=solution.solution_data,
        method=solution.method,
        solve_time_ms=solution.solve_time_ms,
        cost_usd=solution.cost_usd,
    )


# ============================================================================
# Helpers
# ============================================================================


def _generate_model_code(schema) -> str:
    """Generate Python code for a Pydantic model from a discovered schema."""
    lines = [
        "from pydantic import BaseModel, Field",
        "",
        "",
    ]

    class_name = "".join(w.capitalize() for w in schema.entity_type.split("_"))
    lines.append(f"class {class_name}(BaseModel):")
    lines.append(f'    """Auto-discovered schema for {schema.entity_type}."""')
    lines.append("")

    type_map = {
        "str": "str", "string": "str",
        "int": "int", "integer": "int",
        "float": "float", "number": "float",
        "bool": "bool", "boolean": "bool",
        "list[str]": "list[str]",
        "list[int]": "list[int]",
        "datetime": "str",
    }

    for field_def in schema.fields:
        python_type = type_map.get(field_def.type.lower(), "str")
        if field_def.required:
            lines.append(
                f'    {field_def.name}: {python_type} = Field(description="{field_def.description}")'
            )
        else:
            lines.append(
                f'    {field_def.name}: {python_type} | None = Field(default=None, description="{field_def.description}")'
            )

    return "\n".join(lines)
