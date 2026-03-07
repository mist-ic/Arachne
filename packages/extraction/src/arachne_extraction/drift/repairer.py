"""
LLM-powered schema auto-repair for extraction drift.

When drift is detected:
    1. Fetch a fresh sample page from the drifted domain
    2. Run through HTML → Markdown preprocessing
    3. Prompt the LLM: "This schema used to work but is now failing.
       Analyze the new page and propose an updated schema."
    4. Validate the proposed schema against the sample page
    5. If validation passes → auto-deploy the updated schema
    6. Log for human review (non-blocking)

References:
    - Research.md §2.3: Schema drift self-healing
    - Phase4.md Step 3.2: Auto-repair workflow
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class RepairProposal:
    """A proposed schema repair from the LLM."""

    old_schema_fields: list[str]
    new_schema_fields: list[str]
    added_fields: list[str]
    removed_fields: list[str]
    modified_fields: list[str]
    reasoning: str = ""
    confidence: float = 0.0
    schema_json: dict = field(default_factory=dict)


@dataclass
class RepairResult:
    """Result of a schema repair attempt."""

    success: bool
    proposal: RepairProposal | None = None
    validation_passed: bool = False
    sample_extraction_confidence: float = 0.0
    error: str | None = None
    auto_deployed: bool = False


# ============================================================================
# Repair Prompt Templates
# ============================================================================


REPAIR_SYSTEM_PROMPT = """You are a schema engineering assistant. An existing extraction schema has stopped working on a website because the site's structure changed. Your job is to analyze the new page structure and propose an updated schema.

You will receive:
1. The OLD schema that used to work (field names and types)
2. The CURRENT page content (in Markdown format) where the old schema fails

Your task:
1. Identify what changed in the page structure
2. Propose updated field mappings
3. Add any new fields that appeared
4. Remove fields that no longer exist
5. Keep field names consistent with the old schema where possible

Return a valid JSON schema proposal."""


REPAIR_USER_PROMPT = """The following extraction schema USED TO WORK on this site but is now failing with high error rates.

--- OLD SCHEMA ---
{old_schema}
--- END OLD SCHEMA ---

--- CURRENT PAGE CONTENT (Markdown) ---
{page_content}
--- END PAGE CONTENT ---

URL: {url}
Domain: {domain}

Analyze the page content and propose an updated schema that will extract data correctly from this new page structure. Explain what changed."""


# ============================================================================
# Schema Repairer
# ============================================================================


class SchemaRepairer:
    """LLM-powered auto-repair of broken extraction schemas.

    When drift detection fires, this repairer fetches fresh content,
    analyzes the structural changes, and proposes a new schema.

    Usage:
        repairer = SchemaRepairer(model="gemini/gemini-2.5-flash")

        result = await repairer.repair(
            domain="example.com",
            url="https://example.com/products",
            old_schema={"name": "str", "price": "float", "rating": "str"},
            page_content=new_markdown_content,
        )

        if result.success:
            print(f"Auto-repaired schema: {result.proposal.new_schema_fields}")
    """

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash",
        api_key: str | None = None,
        api_base: str | None = None,
        validate_proposal: bool = True,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.validate_proposal = validate_proposal

    async def repair(
        self,
        domain: str,
        url: str,
        old_schema: dict[str, str],
        page_content: str,
    ) -> RepairResult:
        """Attempt to auto-repair a broken schema.

        Args:
            domain: Target domain.
            url: Page URL for context.
            old_schema: The broken schema (field_name → type).
            page_content: Current page content in Markdown.

        Returns:
            RepairResult with the proposed changes and validation status.
        """
        logger.info(
            "schema_repair_start",
            domain=domain,
            old_fields=list(old_schema.keys()),
        )

        try:
            # Step 1: Ask LLM to propose a repair
            proposal = await self._propose_repair(
                domain=domain,
                url=url,
                old_schema=old_schema,
                page_content=page_content,
            )

            if proposal is None:
                return RepairResult(
                    success=False,
                    error="LLM failed to propose a repair",
                )

            # Step 2: Validate the proposed schema
            validation_passed = False
            sample_confidence = 0.0

            if self.validate_proposal:
                validation_passed, sample_confidence = await self._validate_proposal(
                    proposal=proposal,
                    page_content=page_content,
                    url=url,
                )

            result = RepairResult(
                success=validation_passed or not self.validate_proposal,
                proposal=proposal,
                validation_passed=validation_passed,
                sample_extraction_confidence=sample_confidence,
                auto_deployed=validation_passed,
            )

            if validation_passed:
                logger.info(
                    "schema_repair_success",
                    domain=domain,
                    added=proposal.added_fields,
                    removed=proposal.removed_fields,
                    confidence=sample_confidence,
                )
            else:
                logger.warning(
                    "schema_repair_validation_failed",
                    domain=domain,
                    confidence=sample_confidence,
                )

            return result

        except Exception as e:
            logger.error("schema_repair_error", domain=domain, error=str(e))
            return RepairResult(
                success=False,
                error=str(e),
            )

    async def _propose_repair(
        self,
        domain: str,
        url: str,
        old_schema: dict[str, str],
        page_content: str,
    ) -> RepairProposal | None:
        """Ask the LLM to propose a schema repair."""
        import json

        # Format old schema for the prompt
        old_schema_str = json.dumps(old_schema, indent=2)

        # Truncate page content to stay within context window
        max_content_len = 8000
        if len(page_content) > max_content_len:
            page_content = page_content[:max_content_len] + "\n... [truncated]"

        user_prompt = REPAIR_USER_PROMPT.format(
            old_schema=old_schema_str,
            page_content=page_content,
            url=url,
            domain=domain,
        )

        try:
            import instructor
            import litellm

            if self.api_key:
                litellm.api_key = self.api_key

            from pydantic import BaseModel, Field

            class SchemaRepairResponse(BaseModel):
                """LLM response for schema repair."""

                reasoning: str = Field(description="What changed on the page")
                fields: dict[str, str] = Field(
                    description="Updated schema: {field_name: type_string}",
                )
                confidence: float = Field(
                    default=0.5,
                    description="How confident you are in this repair (0-1)",
                )

            client = instructor.from_litellm(litellm.completion)

            response = client.chat.completions.create(
                model=self.model,
                response_model=SchemaRepairResponse,
                messages=[
                    {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )

            old_fields = set(old_schema.keys())
            new_fields = set(response.fields.keys())

            return RepairProposal(
                old_schema_fields=list(old_fields),
                new_schema_fields=list(new_fields),
                added_fields=list(new_fields - old_fields),
                removed_fields=list(old_fields - new_fields),
                modified_fields=[
                    f for f in old_fields & new_fields
                    if old_schema.get(f) != response.fields.get(f)
                ],
                reasoning=response.reasoning,
                confidence=response.confidence,
                schema_json=response.fields,
            )

        except Exception as e:
            logger.error("schema_repair_llm_error", error=str(e))
            return None

    async def _validate_proposal(
        self,
        proposal: RepairProposal,
        page_content: str,
        url: str,
    ) -> tuple[bool, float]:
        """Validate the proposed schema by attempting extraction.

        Returns (passed, confidence).
        """
        try:
            from pydantic import create_model, Field as PydanticField

            # Build a Pydantic model from the proposed schema
            type_map = {
                "str": str, "string": str,
                "int": int, "integer": int,
                "float": float, "number": float,
                "bool": bool, "boolean": bool,
                "list[str]": list[str],
            }

            fields = {}
            for name, type_str in proposal.schema_json.items():
                python_type = type_map.get(type_str.lower(), str)
                fields[name] = (python_type | None, PydanticField(default=None))

            schema_model = create_model("RepairedSchema", **fields)

            # Attempt extraction with the new schema
            from arachne_extraction.llm_extractor import (
                ExtractionConfig,
                LLMExtractor,
                _calculate_confidence,
            )

            extractor = LLMExtractor(config=ExtractionConfig(
                model=self.model,
                api_key=self.api_key,
                api_base=self.api_base,
            ))

            result = await extractor.extract(
                markdown=page_content,
                schema=schema_model,
                url=url,
            )

            if result.data is not None:
                confidence = _calculate_confidence(result.data)
                # Consider it passing if confidence > 0.6
                return confidence > 0.6, confidence
            else:
                return False, 0.0

        except Exception as e:
            logger.error("schema_repair_validation_error", error=str(e))
            return False, 0.0
