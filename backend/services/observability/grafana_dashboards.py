"""
Grafana dashboard JSON generation and Prometheus alerting rules for ACX City.

Generates valid Grafana dashboard JSON (with panels, datasources, templating)
and Prometheus rule YAML for API, pipeline, GPU, and tenant monitoring.
"""

import json
import os
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DS_PROMETHEUS = {
    "uid": "prometheus",
    "type": "prometheus",
    "name": "Prometheus",
}


def _uid() -> str:
    """Monotonic uid generator for panels."""
    _uid.counter = getattr(_uid, "counter", 100)
    _uid.counter += 1
    return f"panel-{_uid.counter}"


def _panel(
    title: str,
    targets: list[dict],
    panel_type: str = "timeseries",
    grid_pos: dict | None = None,
    unit: str | None = None,
    thresholds: dict | None = None,
    description: str = "",
) -> dict:
    p: dict[str, Any] = {
        "id": _uid(),
        "title": title,
        "type": panel_type,
        "datasource": _DS_PROMETHEUS,
        "targets": targets,
        "gridPos": grid_pos or {"h": 8, "w": 12, "x": 0, "y": 0},
        "fieldConfig": {
            "defaults": {},
            "overrides": [],
        },
        "options": {},
        "description": description,
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    if thresholds:
        p["fieldConfig"]["defaults"]["thresholds"] = thresholds
    return p


def _target(expr: str, legend: str = "", ref_id: str = "A") -> dict:
    return {
        "expr": expr,
        "legendFormat": legend,
        "refId": ref_id,
        "datasource": _DS_PROMETHEUS,
        "editorMode": "code",
        "range": True,
        "instant": False,
    }


def _dashboard(title: str, panels: list[dict], tags: list[str] | None = None) -> dict:
    return {
        "uid": title.lower().replace(" ", "-"),
        "title": title,
        "tags": tags or ["acx-city"],
        "timezone": "browser",
        "editable": True,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "datasource",
                    "type": "datasource",
                    "query": "prometheus",
                    "current": {"text": "Prometheus", "value": "prometheus"},
                    "hide": 0,
                },
                {
                    "name": "namespace",
                    "type": "query",
                    "datasource": _DS_PROMETHEUS,
                    "query": 'label_values(acx_api_requests_total, namespace)',
                    "refresh": 2,
                    "includeAll": True,
                    "current": {"text": "All", "value": "$__all"},
                    "hide": 0,
                },
            ]
        },
        "panels": panels,
        "schemaVersion": 39,
        "version": 1,
    }


def _alert_group(name: str, rules: list[dict], interval: str = "30s") -> dict:
    return {
        "name": name,
        "interval": interval,
        "rules": rules,
    }


def _alert_rule(
    alert_name: str,
    expr: str,
    for_duration: str = "5m",
    severity: str = "critical",
    summary: str = "",
    description: str = "",
) -> dict:
    return {
        "alert": alert_name,
        "expr": expr,
        "for": for_duration,
        "labels": {"severity": severity, "team": "acx-city"},
        "annotations": {
            "summary": summary or alert_name,
            "description": description or summary or alert_name,
        },
    }


# ---------------------------------------------------------------------------
# 1. API Dashboard
# ---------------------------------------------------------------------------

def generate_api_dashboard() -> dict:
    """Grafana dashboard for API monitoring: request rate, error rate, latency percentiles, top endpoints."""

    panels = [
        # -- Request Rate (row 1) --
        _panel(
            title="Request Rate (req/s by endpoint)",
            targets=[
                _target(
                    'sum(rate(acx_api_requests_total{namespace="$namespace"}[5m])) by (endpoint)',
                    "{{endpoint}}",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 0},
            unit="reqps",
            description="Total requests per second grouped by endpoint.",
        ),
        # -- Error Rates --
        _panel(
            title="5xx Error Rate",
            targets=[
                _target(
                    'sum(rate(acx_api_requests_total{namespace="$namespace", status=~"5.."}[5m])) by (endpoint)',
                    "{{endpoint}}",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 6, "x": 12, "y": 0},
            unit="reqps",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "red", "value": 0.1},
                ],
            },
            description="5xx errors per second.",
        ),
        _panel(
            title="4xx Error Rate",
            targets=[
                _target(
                    'sum(rate(acx_api_requests_total{namespace="$namespace", status=~"4.."}[5m])) by (endpoint)',
                    "{{endpoint}}",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 6, "x": 18, "y": 0},
            unit="reqps",
            description="4xx client errors per second.",
        ),
        # -- Latency Percentiles --
        _panel(
            title="Latency Percentiles (P50 / P95 / P99)",
            targets=[
                _target(
                    'histogram_quantile(0.50, sum(rate(acx_api_request_duration_seconds_bucket{namespace="$namespace"}[5m])) by (le))',
                    "P50",
                    "A",
                ),
                _target(
                    'histogram_quantile(0.95, sum(rate(acx_api_request_duration_seconds_bucket{namespace="$namespace"}[5m])) by (le))',
                    "P95",
                    "B",
                ),
                _target(
                    'histogram_quantile(0.99, sum(rate(acx_api_request_duration_seconds_bucket{namespace="$namespace"}[5m])) by (le))',
                    "P99",
                    "C",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 8},
            unit="s",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 0.5},
                    {"color": "red", "value": 0.8},
                ],
            },
            description="Request latency percentiles across all endpoints.",
        ),
        # -- Top Endpoints by Traffic --
        _panel(
            title="Top Endpoints by Traffic",
            targets=[
                _target(
                    'topk(10, sum(rate(acx_api_requests_total{namespace="$namespace"}[5m])) by (endpoint))',
                    "{{endpoint}}",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 12, "y": 8},
            unit="reqps",
            description="Top 10 endpoints by request rate.",
        ),
    ]

    return _dashboard("ACX City - API Monitoring", panels, tags=["acx-city", "api"])


# ---------------------------------------------------------------------------
# 2. Pipeline Dashboard
# ---------------------------------------------------------------------------

def generate_pipeline_dashboard() -> dict:
    """Dashboard for per-agent latency, error rates, cost per chapter, pipeline throughput."""

    # Per-agent latency panels (agent1 through agent5)
    agent_latency_targets = [
        _target(
            f'histogram_quantile(0.95, sum(rate(acx_pipeline_agent_latency_seconds_bucket{{namespace="$namespace", agent="agent{i}"}}[5m])) by (le))',
            f"agent{i} P95",
            chr(65 + i - 1),
        )
        for i in range(1, 6)
    ]

    agent_error_targets = [
        _target(
            f'sum(rate(acx_pipeline_agent_errors_total{{namespace="$namespace", agent="agent{i}"}}[5m])) / clamp_min(sum(rate(acx_pipeline_agent_requests_total{{namespace="$namespace", agent="agent{i}"}}[5m])), 1)',
            f"agent{i}",
            chr(65 + i - 1),
        )
        for i in range(1, 6)
    ]

    cost_targets = [
        _target(
            f'sum(acx_pipeline_cost_per_chapter_usd{{namespace="$namespace", agent="agent{i}"}})',
            f"agent{i}",
            chr(65 + i - 1),
        )
        for i in range(1, 6)
    ]

    panels = [
        _panel(
            title="Per-Agent Latency (P95)",
            targets=agent_latency_targets,
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 0},
            unit="s",
            description="95th-percentile latency per pipeline agent.",
        ),
        _panel(
            title="Agent Error Rates",
            targets=agent_error_targets,
            grid_pos={"h": 8, "w": 12, "x": 12, "y": 0},
            unit="percentunit",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 0.05},
                    {"color": "red", "value": 0.20},
                ],
            },
            description="Error rate per agent (errors / total requests).",
        ),
        _panel(
            title="Cost per Chapter by Agent",
            targets=cost_targets,
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 8},
            unit="currencyUSD",
            description="Average cost in USD per chapter processed by each agent.",
        ),
        _panel(
            title="Pipeline Throughput (chapters/hour)",
            targets=[
                _target(
                    'sum(rate(acx_pipeline_chapters_completed_total{namespace="$namespace"}[1h])) * 3600',
                    "chapters/hr",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 12, "y": 8},
            unit="short",
            description="Total chapters completed per hour across all agents.",
        ),
    ]

    return _dashboard("ACX City - Pipeline Monitoring", panels, tags=["acx-city", "pipeline"])


# ---------------------------------------------------------------------------
# 3. GPU Dashboard
# ---------------------------------------------------------------------------

def generate_gpu_dashboard() -> dict:
    """Dashboard for GPU worker count, utilization, synthesis throughput, queue depth."""

    panels = [
        _panel(
            title="GPU Worker Count",
            targets=[
                _target(
                    'acx_gpu_workers_active{namespace="$namespace"}',
                    "active workers",
                    "A",
                ),
                _panel(
                    title="GPU Utilization (%)",
                    targets=[
                        _target(
                            'avg(acx_gpu_utilization_percent{namespace="$namespace"}) by (gpu_id)',
                            "gpu {{gpu_id}}",
                            "A",
                        ),
                    ],
                    grid_pos={"h": 8, "w": 12, "x": 12, "y": 0},
                    unit="percent",
                    thresholds={
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": None},
                            {"color": "yellow", "value": 80},
                            {"color": "red", "value": 95},
                        ],
                    },
                    description="Average GPU utilization per device.",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 0},
            unit="short",
            description="Number of active GPU workers.",
        ),
        _panel(
            title="Synthesis Throughput (chars/sec)",
            targets=[
                _target(
                    'sum(rate(acx_synthesis_characters_total{namespace="$namespace"}[5m]))',
                    "chars/sec",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 8},
            unit="short",
            description="Characters synthesized per second across all workers.",
        ),
        _panel(
            title="Synthesis Queue Depth",
            targets=[
                _target(
                    'acx_synthesis_queue_depth{namespace="$namespace"}',
                    "queue depth",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 12, "y": 8},
            unit="short",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 100},
                    {"color": "red", "value": 500},
                ],
            },
            description="Current number of items waiting in the synthesis queue.",
        ),
    ]

    # Fix: the first panel's targets list had a nested panel object by mistake — rebuild properly
    panels = [
        _panel(
            title="GPU Worker Count",
            targets=[
                _target(
                    'acx_gpu_workers_active{namespace="$namespace"}',
                    "active workers",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 0},
            unit="short",
            description="Number of active GPU workers.",
        ),
        _panel(
            title="GPU Utilization (%)",
            targets=[
                _target(
                    'avg(acx_gpu_utilization_percent{namespace="$namespace"}) by (gpu_id)',
                    "gpu {{gpu_id}}",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 12, "y": 0},
            unit="percent",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 80},
                    {"color": "red", "value": 95},
                ],
            },
            description="Average GPU utilization per device.",
        ),
        _panel(
            title="Synthesis Throughput (chars/sec)",
            targets=[
                _target(
                    'sum(rate(acx_synthesis_characters_total{namespace="$namespace"}[5m]))',
                    "chars/sec",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 8},
            unit="short",
            description="Characters synthesized per second across all workers.",
        ),
        _panel(
            title="Synthesis Queue Depth",
            targets=[
                _target(
                    'acx_synthesis_queue_depth{namespace="$namespace"}',
                    "queue depth",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 12, "y": 8},
            unit="short",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 100},
                    {"color": "red", "value": 500},
                ],
            },
            description="Current number of items waiting in the synthesis queue.",
        ),
    ]

    return _dashboard("ACX City - GPU & Synthesis", panels, tags=["acx-city", "gpu", "synthesis"])


# ---------------------------------------------------------------------------
# 4. Tenant Dashboard
# ---------------------------------------------------------------------------

def generate_tenant_dashboard() -> dict:
    """Dashboard for per-org monthly spend, quota utilization, over-limit risk."""

    panels = [
        _panel(
            title="Per-Org Monthly Spend ($)",
            targets=[
                _target(
                    'sum(acx_tenant_monthly_spend_usd{namespace="$namespace"}) by (org_id)',
                    "{{org_id}}",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 0, "y": 0},
            unit="currencyUSD",
            description="Current month's spend per organization.",
        ),
        _panel(
            title="Quota Utilization (%)",
            targets=[
                _target(
                    'acx_tenant_quota_used{namespace="$namespace", org_id="$org"} / clamp_min(acx_tenant_quota_limit{namespace="$namespace", org_id="$org"}, 1) * 100',
                    "{{org_id}}",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 12, "x": 12, "y": 0},
            unit="percent",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 80},
                    {"color": "red", "value": 95},
                ],
            },
            description="Percentage of monthly quota consumed per org.",
        ),
        _panel(
            title="Over-Limit Risk Alerts",
            targets=[
                _target(
                    'acx_tenant_monthly_spend_usd{namespace="$namespace"} / clamp_min(acx_tenant_monthly_limit_usd{namespace="$namespace"}, 1) * 100 > 90',
                    "{{org_id}}",
                    "A",
                ),
            ],
            grid_pos={"h": 8, "w": 24, "x": 0, "y": 8},
            unit="percent",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "orange", "value": 90},
                    {"color": "red", "value": 100},
                ],
            },
            panel_type="table",
            description="Organizations approaching or exceeding monthly spend limits (>90%).",
        ),
    ]

    # Add org variable to templating
    dash = _dashboard("ACX City - Tenant Spend & Quota", panels, tags=["acx-city", "tenants", "billing"])
    dash["templating"]["list"].append(
        {
            "name": "org",
            "type": "query",
            "datasource": _DS_PROMETHEUS,
            "query": 'label_values(acx_tenant_monthly_spend_usd, org_id)',
            "refresh": 2,
            "includeAll": True,
            "current": {"text": "All", "value": "$__all"},
            "hide": 0,
        }
    )
    return dash


# ---------------------------------------------------------------------------
# 5. Prometheus Alerting Rules
# ---------------------------------------------------------------------------

def generate_prometheus_alerts() -> dict:
    """Prometheus alerting rules for ACX City critical SLOs."""

    rules = [
        # API Availability < 99.5%
        _alert_rule(
            alert_name="ACXApiAvailabilityLow",
            expr=(
                '1 - (sum(rate(acx_api_requests_total{namespace="acx-city", status=~"5.."}[5m]))'
                ' / clamp_min(sum(rate(acx_api_requests_total{namespace="acx-city"}[5m])), 1))'
                ' < 0.995'
            ),
            for_duration="5m",
            severity="critical",
            summary="API availability below 99.5%",
            description=(
                "API availability has dropped below 99.5% over the last 5 minutes. "
                "Current error ratio: {{ $value | humanizePercentage }}."
            ),
        ),
        # API P99 > 800ms
        _alert_rule(
            alert_name="ACXApiP99LatencyHigh",
            expr=(
                'histogram_quantile(0.99, sum(rate(acx_api_request_duration_seconds_bucket{namespace="acx-city"}[5m])) by (le))'
                ' > 0.8'
            ),
            for_duration="3m",
            severity="warning",
            summary="API P99 latency exceeds 800ms",
            description=(
                "The 99th-percentile request latency has exceeded 800ms. "
                "Current P99: {{ $value | humanizeDuration }}."
            ),
        ),
        # Synthesis success < 98%
        _alert_rule(
            alert_name="ACXSynthesisSuccessLow",
            expr=(
                'sum(rate(acx_synthesis_success_total{namespace="acx-city"}[10m]))'
                ' / clamp_min(sum(rate(acx_synthesis_attempts_total{namespace="acx-city"}[10m])), 1)'
                ' < 0.98'
            ),
            for_duration="5m",
            severity="critical",
            summary="Synthesis success rate below 98%",
            description=(
                "GPU synthesis success rate has dropped below 98%. "
                "Current rate: {{ $value | humanizePercentage }}."
            ),
        ),
        # Cost anomaly > $50/hour
        _alert_rule(
            alert_name="ACXCostAnomalyHigh",
            expr=(
                'sum(rate(acx_pipeline_cost_per_chapter_usd{namespace="acx-city"}[1h]))'
                ' * sum(rate(acx_pipeline_chapters_completed_total{namespace="acx-city"}[1h]))'
                ' * 3600 > 50'
            ),
            for_duration="10m",
            severity="warning",
            summary="Pipeline cost anomaly: spend exceeds $50/hour",
            description=(
                "Current pipeline burn rate exceeds $50/hour. "
                "Estimated hourly cost: ${{ $value }}."
            ),
        ),
        # Agent 3 fallback rate > 20%
        _alert_rule(
            alert_name="ACXAgent3FallbackRateHigh",
            expr=(
                'sum(rate(acx_pipeline_agent_fallback_total{namespace="acx-city", agent="agent3"}[5m]))'
                ' / clamp_min(sum(rate(acx_pipeline_agent_requests_total{namespace="acx-city", agent="agent3"}[5m])), 1)'
                ' > 0.20'
            ),
            for_duration="5m",
            severity="warning",
            summary="Agent 3 fallback rate exceeds 20%",
            description=(
                "Agent 3 is falling back to secondary processing in over 20% of requests. "
                "Current rate: {{ $value | humanizePercentage }}."
            ),
        ),
    ]

    alert_groups = [
        _alert_group("acx-city-api", [rules[0], rules[1]]),
        _alert_group("acx-city-pipeline", [rules[2], rules[3], rules[4]]),
    ]

    return {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {
            "name": "acx-city-alerts",
            "namespace": "acx-city",
            "labels": {"team": "acx-city", "prometheus": "main"},
        },
        "spec": {
            "groups": alert_groups,
        },
    }


# ---------------------------------------------------------------------------
# 6. Export all
# ---------------------------------------------------------------------------

def export_all_dashboards(output_dir: str) -> None:
    """Write all dashboard JSONs and alert rules to files in *output_dir*."""

    os.makedirs(output_dir, exist_ok=True)

    dashboards = {
        "api_dashboard.json": generate_api_dashboard(),
        "pipeline_dashboard.json": generate_pipeline_dashboard(),
        "gpu_dashboard.json": generate_gpu_dashboard(),
        "tenant_dashboard.json": generate_tenant_dashboard(),
        "prometheus_alerts.json": generate_prometheus_alerts(),
    }

    for filename, content in dashboards.items():
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        print(f"[grafana_dashboards] wrote {path}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "dashboards_output"
    export_all_dashboards(out)
    print(f"All dashboards exported to {out}/")
