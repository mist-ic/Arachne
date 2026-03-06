# Observability

OpenTelemetry instrumentation, structured logging, and Prometheus metrics for all Arachne services.

- **Logging**: `structlog` with JSON output and context binding
- **Tracing**: OpenTelemetry SDK with console export (dev) and OTLP gRPC export (production)
- **Metrics**: Prometheus client with pre-defined counters and histograms for job lifecycle, crawl performance, and extraction
