"""
DuckDB-based ad-hoc analytics for Arachne telemetry data.

Provides SQL-based analytics over scraped data, extraction metrics,
and benchmark results. DuckDB runs in-process (no server) and
can query Parquet/JSON files directly — perfect for ad-hoc analysis
without a full analytics warehouse.

Use cases:
    - Generate benchmark reports from extraction run data
    - Analyze extraction accuracy per domain, model, and schema
    - Compare model cost/performance tradeoffs
    - Build dashboard data summaries

References:
    - Phase4.md Step 5.6: DuckDB for ad-hoc analytics
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class QueryResult:
    """Result of a DuckDB query."""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None

    def to_dicts(self) -> list[dict]:
        """Convert result to a list of dicts for JSON serialization."""
        return [dict(zip(self.columns, row)) for row in self.rows]

    def to_markdown_table(self) -> str:
        """Format result as a Markdown table."""
        if not self.columns:
            return "_No results_"

        lines = [
            "| " + " | ".join(str(c) for c in self.columns) + " |",
            "| " + " | ".join("---" for _ in self.columns) + " |",
        ]
        for row in self.rows:
            lines.append("| " + " | ".join(str(v) for v in row) + " |")

        return "\n".join(lines)


# ============================================================================
# Analytics Engine
# ============================================================================


class AnalyticsEngine:
    """DuckDB-based analytics engine for Arachne telemetry.

    Queries extraction results, benchmark data, and system metrics
    stored as JSON/Parquet files.

    Usage:
        analytics = AnalyticsEngine()

        # Load extraction results
        analytics.load_json("extraction_results", "/path/to/results/*.json")

        # Run ad-hoc queries
        result = analytics.query(
            "SELECT model_used, AVG(confidence), COUNT(*) "
            "FROM extraction_results GROUP BY model_used"
        )

        print(result.to_markdown_table())
    """

    def __init__(self, database: str = ":memory:"):
        """Initialize DuckDB analytics engine.

        Args:
            database: DuckDB database path. ":memory:" for in-memory.
        """
        self.database = database
        self._conn = None

    def _get_connection(self):
        """Lazy-initialize DuckDB connection."""
        if self._conn is None:
            try:
                import duckdb

                self._conn = duckdb.connect(self.database)
                logger.info("duckdb_connected", database=self.database)
            except ImportError:
                raise ImportError(
                    "DuckDB not installed. Install with: pip install duckdb"
                )
        return self._conn

    def query(self, sql: str) -> QueryResult:
        """Execute a SQL query and return results.

        Args:
            sql: SQL query string.

        Returns:
            QueryResult with columns and rows.
        """
        try:
            conn = self._get_connection()
            result = conn.execute(sql)

            columns = [desc[0] for desc in result.description] if result.description else []
            rows = result.fetchall()

            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
            )

        except Exception as e:
            logger.error("duckdb_query_error", error=str(e), sql=sql[:200])
            return QueryResult(error=str(e))

    def load_json(self, table_name: str, path: str) -> None:
        """Load JSON files into a DuckDB table.

        Args:
            table_name: Table name to create.
            path: Path to JSON file(s), supports glob patterns.
        """
        conn = self._get_connection()
        conn.execute(f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_json_auto('{path}')
        """)
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        logger.info("duckdb_loaded_json", table=table_name, rows=count, path=path)

    def load_parquet(self, table_name: str, path: str) -> None:
        """Load Parquet files into a DuckDB table."""
        conn = self._get_connection()
        conn.execute(f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_parquet('{path}')
        """)
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        logger.info("duckdb_loaded_parquet", table=table_name, rows=count)

    def load_records(self, table_name: str, records: list[dict]) -> None:
        """Load in-memory records into a DuckDB table.

        Args:
            table_name: Table name to create.
            records: List of dicts to insert.
        """
        if not records:
            return

        conn = self._get_connection()

        # Write records as JSON, then read into DuckDB
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(records, f)
            tmp_path = f.name

        conn.execute(f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_json_auto('{tmp_path}')
        """)

        Path(tmp_path).unlink(missing_ok=True)
        logger.info("duckdb_loaded_records", table=table_name, rows=len(records))

    # =========================================================================
    # Pre-built Analytics Queries
    # =========================================================================

    def extraction_accuracy_by_model(self) -> QueryResult:
        """Analyze extraction accuracy grouped by model."""
        return self.query("""
            SELECT
                model_used,
                COUNT(*) as total_extractions,
                AVG(confidence) as avg_confidence,
                MIN(confidence) as min_confidence,
                MAX(confidence) as max_confidence,
                SUM(estimated_cost_usd) as total_cost_usd,
                AVG(tokens_input + tokens_output) as avg_tokens
            FROM extraction_results
            GROUP BY model_used
            ORDER BY avg_confidence DESC
        """)

    def cost_per_field_by_model(self) -> QueryResult:
        """Analyze cost efficiency per extracted field."""
        return self.query("""
            SELECT
                model_used,
                COUNT(*) as extractions,
                SUM(estimated_cost_usd) as total_cost,
                SUM(estimated_cost_usd) / NULLIF(SUM(field_count), 0) as cost_per_field,
                AVG(elapsed_ms) as avg_latency_ms
            FROM extraction_results
            WHERE field_count > 0
            GROUP BY model_used
            ORDER BY cost_per_field ASC
        """)

    def domain_success_rates(self) -> QueryResult:
        """Analyze success rates per domain."""
        return self.query("""
            SELECT
                regexp_extract(source_url, '^https?://([^/]+)', 1) as domain,
                COUNT(*) as total_crawls,
                SUM(CASE WHEN confidence > 0.5 THEN 1 ELSE 0 END) as successful,
                AVG(confidence) as avg_confidence
            FROM extraction_results
            GROUP BY domain
            ORDER BY total_crawls DESC
        """)

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
