"""FastAPI router for the Ops23-NR Intelligent Cloud Operations Center Dashboard.

Phase 9: High-fidelity SRE Command Center dashboard & telemetry aggregation.
Styled in Light Mode with Purple aesthetic inspired by Kiro.
"""

from datetime import datetime, timezone
import os
import random
from typing import Any, Dict, List, Optional

try:
    import psutil
except ImportError:
    psutil = None

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings
from app.remediation.models import ApprovalStatus, ExecutionStatus
from app.remediation.service import RemediationApprovalService

router = APIRouter(tags=["Operations Center Dashboard"])


def get_system_telemetry() -> Dict[str, Any]:
    """Gathers real host metrics where available or generates realistic production baselines."""
    cpu_percent = 12.4
    memory_percent = 44.2

    if psutil:
        try:
            cpu_percent = round(psutil.cpu_percent(interval=None) or 12.4, 1)
            memory_percent = round(psutil.virtual_memory().percent, 1)
        except Exception:
            pass
    else:
        cpu_percent = round(11.8 + random.uniform(0.1, 1.2), 1)
        memory_percent = round(43.9 + random.uniform(0.1, 0.8), 1)

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "requests_per_min": 1284,
        "error_rate_percent": 0.02,
        "system_status": "HEALTHY",
        "system_status_text": "SYSTEM HEALTHY",
    }


def get_services_health() -> List[Dict[str, str]]:
    """Component health status indicators."""
    return [
        {"name": "API", "status": "Healthy", "state": "healthy", "description": "FastAPI port 8000 (Active)"},
        {"name": "Database", "status": "Healthy", "state": "healthy", "description": "DynamoDB tables online"},
        {"name": "EC2", "status": "Healthy", "state": "healthy", "description": "i-066478e6fd6dc22af"},
        {"name": "SSM", "status": "Connected", "state": "healthy", "description": "AWS SSM Agent Online"},
    ]


@router.get(
    "/api/v1/dashboard/overview",
    summary="Get SRE Dashboard Overview Telemetry",
    description="Aggregates telemetry metrics, active incidents, service health, and remediation timeline.",
)
async def get_dashboard_overview(
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    telemetry = get_system_telemetry()
    services = get_services_health()
    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "title": "OPS23-NR — Intelligent Cloud Operations Center",
        "service_name": settings.SERVICE_NAME,
        "environment": settings.ENVIRONMENT,
        "version": settings.VERSION,
        "timestamp": now_iso,
        "telemetry": telemetry,
        "services": services,
        "active_incident": {
            "id": "INC-8143846-992",
            "severity": "CRITICAL",
            "title": "Service degraded",
            "detected_at": "2 min ago",
            "condition": "Service Availability Degradation",
            "status": "OPEN",
        },
        "sample_rca": {
            "root_cause": "FastAPI service stopped responding to health checks",
            "confidence": 0.96,
            "evidence": [
                "Health check failures (HTTP 502 / Connection refused)",
                "Error traces indicate socket exhaustion on worker 2",
                "Service telemetry shows memory peak at 94% prior to crash",
            ],
            "recommended_action": "RESTART_OPS23_SERVICE",
            "target": "i-066478e6fd6dc22af",
            "service": "ops23-nr.service",
            "decision": "ALLOWLISTED_RECOMMENDATION",
            "approval_status": "PENDING",
        },
        "timeline": [
            {"step": 1, "title": "Incident detected", "status": "completed", "detail": "Service degradation alert triggered"},
            {"step": 2, "title": "AI RCA completed", "status": "completed", "detail": "Bedrock Claude 3 Haiku diagnosis (96% confidence)"},
            {"step": 3, "title": "Awaiting Human Approval", "status": "pending", "detail": "Awaiting SRE authorization (Prabhu)"},
            {"step": 4, "title": "Lambda → SSM", "status": "waiting", "detail": "SSM RunShellScript restart command"},
            {"step": 5, "title": "Service recovered", "status": "waiting", "detail": "Health verification passes (HTTP 200)"},
        ],
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OPS23-NR — Intelligent Cloud Operations Center</title>
  <meta name="description" content="Ops23-NR SRE Command Center: Cloud Observability, Bedrock AI RCA, and Human-in-the-Loop Remediation.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      /* Kiro-Inspired Light Mode with Vibrant Purple Accent */
      --bg-page: #FAF8FF;
      --bg-card: rgba(255, 255, 255, 0.96);
      --bg-card-hover: #FFFFFF;
      --border-subtle: #E9D5FF;
      --border-accent: #7C3AED;
      --text-main: #1E1B4B;
      --text-muted: #5B5A75;
      --text-dim: #8B85A8;
      
      --purple-primary: #7C3AED;
      --purple-hover: #6D28D9;
      --purple-light: #F5F3FF;
      --purple-badge: #EDE9FE;
      --purple-glow: rgba(124, 58, 237, 0.16);

      --emerald: #059669;
      --emerald-bg: #ECFDF5;
      --emerald-border: #A7F3D0;
      --emerald-glow: rgba(5, 150, 105, 0.2);

      --rose: #DC2626;
      --rose-bg: #FEF2F2;
      --rose-border: #FECACA;
      --rose-glow: rgba(220, 38, 38, 0.16);

      --blue: #2563EB;
      --blue-bg: #EFF6FF;
      --blue-border: #BFDBFE;

      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-page);
      background-image: 
        radial-gradient(circle at 10% 10%, rgba(124, 58, 237, 0.07) 0%, transparent 45%),
        radial-gradient(circle at 90% 90%, rgba(168, 85, 247, 0.06) 0%, transparent 45%),
        radial-gradient(circle at 50% 50%, rgba(5, 150, 105, 0.03) 0%, transparent 60%);
      color: var(--text-main);
      font-family: var(--font-sans);
      min-height: 100vh;
      padding: 28px 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
    }

    .container {
      width: 100%;
      max-width: 1040px;
      display: flex;
      flex-direction: column;
      gap: 22px;
    }

    /* Kiro Clean Glass Card */
    .glass-panel {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      box-shadow: 0 4px 20px rgba(124, 58, 237, 0.05), 0 1px 3px rgba(0, 0, 0, 0.02);
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }

    .glass-panel:hover {
      border-color: #DDD6FE;
      box-shadow: 0 8px 30px rgba(124, 58, 237, 0.09), 0 2px 6px rgba(0, 0, 0, 0.04);
    }

    /* Header */
    header.header {
      padding: 22px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: relative;
      overflow: hidden;
      border-bottom: 2px solid var(--purple-badge);
    }

    header.header::after {
      content: '';
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      height: 2px;
      background: linear-gradient(90deg, transparent, var(--purple-primary), #C084FC, transparent);
      opacity: 0.6;
    }

    .title-group {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .brand-title {
      font-size: 22px;
      font-weight: 800;
      letter-spacing: 1.5px;
      color: var(--purple-primary);
      font-family: var(--font-mono);
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand-subtitle {
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
      letter-spacing: 0.3px;
    }

    .status-badge {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 18px;
      background: var(--emerald-bg);
      border: 1px solid var(--emerald-border);
      border-radius: 30px;
      font-size: 12px;
      font-weight: 700;
      font-family: var(--font-mono);
      letter-spacing: 0.6px;
      color: var(--emerald);
      box-shadow: 0 2px 8px var(--emerald-glow);
    }

    .pulse-dot {
      width: 9px;
      height: 9px;
      background-color: var(--emerald);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--emerald);
      animation: pulse 2s infinite;
    }

    @keyframes pulse {
      0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(5, 150, 105, 0.6); }
      70% { transform: scale(1.15); box-shadow: 0 0 0 8px rgba(5, 150, 105, 0); }
      100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(5, 150, 105, 0); }
    }

    /* Metrics Bar */
    .metrics-bar {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }

    .metric-card {
      padding: 20px 24px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 1.3px;
      color: var(--text-dim);
      font-weight: 700;
      font-family: var(--font-mono);
    }

    .metric-value {
      font-size: 28px;
      font-weight: 800;
      color: var(--text-main);
      font-family: var(--font-mono);
      display: flex;
      align-items: baseline;
      gap: 4px;
    }

    .metric-progress {
      width: 100%;
      height: 5px;
      background: #F3E8FF;
      border-radius: 3px;
      margin-top: 6px;
      overflow: hidden;
    }

    .metric-progress-bar {
      height: 100%;
      border-radius: 3px;
      background: linear-gradient(90deg, var(--purple-primary), #A855F7);
      transition: width 0.6s ease;
    }

    /* Dashboard Two-Column Grid */
    .dashboard-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 22px;
    }

    .panel-header {
      padding: 18px 24px;
      border-bottom: 1px solid var(--border-subtle);
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 1.2px;
      color: var(--text-main);
      font-family: var(--font-mono);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .panel-body {
      padding: 22px 24px;
    }

    /* Incidents Card */
    .incident-item {
      background: var(--rose-bg);
      border: 1px solid var(--rose-border);
      border-left: 4px solid var(--rose);
      border-radius: 12px;
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      box-shadow: 0 2px 10px var(--rose-glow);
    }

    .incident-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .severity-tag {
      padding: 4px 10px;
      background: var(--rose);
      color: #FFFFFF;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1px;
      border-radius: 4px;
      font-family: var(--font-mono);
    }

    .incident-time {
      font-size: 12px;
      color: var(--rose);
      font-family: var(--font-mono);
      font-weight: 600;
    }

    .incident-title {
      font-size: 16px;
      font-weight: 700;
      color: #991B1B;
    }

    .incident-condition {
      font-size: 12px;
      color: #B91C1C;
    }

    /* Service Health */
    .services-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .service-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      background: #FDFBFF;
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
    }

    .service-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .service-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--emerald);
      box-shadow: 0 0 8px var(--emerald-glow);
    }

    .service-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-main);
    }

    .service-status-text {
      font-size: 12px;
      font-family: var(--font-mono);
      color: var(--emerald);
      font-weight: 700;
    }

    /* AI RCA Panel */
    .rca-section {
      padding: 28px 32px;
      border: 1px solid #DDD6FE;
    }

    .rca-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 22px;
    }

    .rca-title-wrap {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .rca-icon {
      font-size: 22px;
    }

    .rca-title {
      font-size: 17px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      font-family: var(--font-mono);
      color: var(--purple-primary);
    }

    .confidence-badge {
      padding: 6px 16px;
      background: var(--purple-badge);
      border: 1px solid #C4B5FD;
      border-radius: 20px;
      color: var(--purple-primary);
      font-size: 13px;
      font-family: var(--font-mono);
      font-weight: 700;
    }

    .rca-field {
      margin-bottom: 20px;
    }

    .rca-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 1.2px;
      color: var(--text-dim);
      font-weight: 700;
      font-family: var(--font-mono);
      margin-bottom: 8px;
    }

    .rca-root-cause-box {
      background: var(--purple-light);
      border: 1px solid #DDD6FE;
      border-left: 4px solid var(--purple-primary);
      border-radius: 10px;
      padding: 16px 20px;
      font-size: 15px;
      font-weight: 600;
      color: var(--text-main);
      line-height: 1.5;
    }

    .evidence-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .evidence-item {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
    }

    .evidence-check {
      color: var(--emerald);
      font-weight: 800;
      font-size: 15px;
    }

    .recommended-action-box {
      background: #F3E8FF;
      border: 1px solid #D8B4FE;
      border-radius: 10px;
      padding: 14px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .action-code {
      font-family: var(--font-mono);
      font-weight: 800;
      color: var(--purple-primary);
      font-size: 15px;
      letter-spacing: 0.8px;
    }

    .action-badge {
      font-size: 12px;
      padding: 4px 10px;
      background: #FFFFFF;
      border: 1px solid #D8B4FE;
      border-radius: 6px;
      color: var(--purple-hover);
      font-family: var(--font-mono);
      font-weight: 600;
    }

    /* Action Buttons */
    .action-bar {
      display: flex;
      gap: 14px;
      justify-content: flex-end;
      align-items: center;
      margin-top: 26px;
      padding-top: 22px;
      border-top: 1px solid var(--border-subtle);
    }

    .approver-input-wrap {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-right: auto;
    }

    .approver-input-wrap label {
      font-size: 12px;
      color: var(--text-main);
      font-family: var(--font-mono);
      font-weight: 700;
      text-transform: uppercase;
    }

    .approver-input {
      background: #FFFFFF;
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 9px 14px;
      color: var(--text-main);
      font-size: 13px;
      font-family: var(--font-mono);
      font-weight: 600;
      outline: none;
      transition: all 0.2s ease;
    }

    .approver-input:focus {
      border-color: var(--purple-primary);
      box-shadow: 0 0 0 3px var(--purple-glow);
    }

    .btn {
      padding: 11px 24px;
      border-radius: 10px;
      font-size: 12px;
      font-weight: 800;
      font-family: var(--font-mono);
      letter-spacing: 1px;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-transform: uppercase;
      border: none;
    }

    .btn-reject {
      background: var(--rose-bg);
      border: 1px solid var(--rose-border);
      color: var(--rose);
    }

    .btn-reject:hover:not(:disabled) {
      background: #FEE2E2;
      box-shadow: 0 4px 12px var(--rose-glow);
    }

    .btn-approve {
      background: var(--emerald);
      color: #FFFFFF;
      box-shadow: 0 4px 14px var(--emerald-glow);
    }

    .btn-approve:hover:not(:disabled) {
      background: #047857;
      transform: translateY(-1px);
      box-shadow: 0 6px 20px var(--emerald-glow);
    }

    .btn-execute {
      background: var(--purple-primary);
      color: #FFFFFF;
      box-shadow: 0 4px 14px var(--purple-glow);
    }

    .btn-execute:hover:not(:disabled) {
      background: var(--purple-hover);
      transform: translateY(-1px);
      box-shadow: 0 6px 20px var(--purple-glow);
    }

    .btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
      box-shadow: none;
      transform: none;
    }

    /* Remediation Timeline */
    .timeline-section {
      padding: 28px 32px;
    }

    .timeline-header {
      font-size: 14px;
      font-weight: 800;
      letter-spacing: 1.2px;
      text-transform: uppercase;
      font-family: var(--font-mono);
      color: var(--text-main);
      margin-bottom: 26px;
    }

    .timeline-steps {
      display: flex;
      flex-direction: column;
      position: relative;
      padding-left: 24px;
    }

    .timeline-steps::before {
      content: '';
      position: absolute;
      left: 8px;
      top: 14px;
      bottom: 14px;
      width: 2px;
      background: #E9D5FF;
    }

    .timeline-step {
      display: flex;
      align-items: flex-start;
      gap: 20px;
      padding-bottom: 26px;
      position: relative;
    }

    .timeline-step:last-child {
      padding-bottom: 0;
    }

    .step-marker {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #FFFFFF;
      border: 2px solid #C4B5FD;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 2;
      flex-shrink: 0;
      margin-left: -29px;
      font-size: 11px;
      font-weight: 800;
      transition: all 0.3s ease;
    }

    .timeline-step.completed .step-marker {
      border-color: var(--emerald);
      background: var(--emerald);
      color: #FFFFFF;
      box-shadow: 0 0 10px var(--emerald-glow);
    }

    .timeline-step.active .step-marker {
      border-color: var(--purple-primary);
      background: var(--purple-primary);
      box-shadow: 0 0 14px var(--purple-glow);
      animation: pulse-purple 1.8s infinite;
    }

    @keyframes pulse-purple {
      0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(124, 58, 237, 0.6); }
      70% { transform: scale(1.1); box-shadow: 0 0 0 8px rgba(124, 58, 237, 0); }
      100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(124, 58, 237, 0); }
    }

    .step-content {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .step-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--text-main);
      font-family: var(--font-mono);
    }

    .timeline-step.waiting .step-title {
      color: var(--text-dim);
    }

    .step-detail {
      font-size: 12px;
      color: var(--text-muted);
    }

    /* Toast Notification */
    .toast-banner {
      position: fixed;
      bottom: 28px;
      right: 28px;
      padding: 16px 24px;
      border-radius: 12px;
      background: #FFFFFF;
      border: 1px solid var(--border-subtle);
      box-shadow: 0 12px 36px rgba(124, 58, 237, 0.16);
      display: none;
      align-items: center;
      gap: 14px;
      font-size: 13px;
      font-weight: 600;
      z-index: 100;
    }

    .toast-banner.show {
      display: flex;
      animation: slideIn 0.3s ease;
    }

    @keyframes slideIn {
      from { transform: translateY(20px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }

    @media (max-width: 800px) {
      .metrics-bar { grid-template-columns: repeat(2, 1fr); }
      .dashboard-grid { grid-template-columns: 1fr; }
      .action-bar { flex-direction: column; align-items: stretch; }
      .approver-input-wrap { margin-right: 0; margin-bottom: 12px; }
    }
  </style>
</head>
<body>

  <div class="container">
    <!-- Header -->
    <header class="glass-panel header">
      <div class="title-group">
        <h1 class="brand-title">OPS23-NR</h1>
        <div class="brand-subtitle">Intelligent Cloud Operations Center</div>
      </div>
      <div class="status-badge" id="system-status-badge">
        <span class="pulse-dot"></span>
        <span id="system-status-text">SYSTEM HEALTHY</span>
      </div>
    </header>

    <!-- Metrics Bar -->
    <section class="metrics-bar" aria-label="System Metrics">
      <div class="glass-panel metric-card">
        <span class="metric-label">CPU</span>
        <div class="metric-value"><span id="cpu-val">12.4</span>%</div>
        <div class="metric-progress"><div class="metric-progress-bar" id="cpu-bar" style="width: 12.4%"></div></div>
      </div>

      <div class="glass-panel metric-card">
        <span class="metric-label">Memory</span>
        <div class="metric-value"><span id="mem-val">44.2</span>%</div>
        <div class="metric-progress"><div class="metric-progress-bar" id="mem-bar" style="width: 44.2%"></div></div>
      </div>

      <div class="glass-panel metric-card">
        <span class="metric-label">Requests</span>
        <div class="metric-value"><span id="req-val">1,284</span><span style="font-size: 13px; color: var(--text-dim);">/min</span></div>
        <div class="metric-progress"><div class="metric-progress-bar" style="width: 65%"></div></div>
      </div>

      <div class="glass-panel metric-card">
        <span class="metric-label">Error Rate</span>
        <div class="metric-value"><span id="err-val">0.02</span>%</div>
        <div class="metric-progress"><div class="metric-progress-bar" style="width: 2%; background: var(--emerald);"></div></div>
      </div>
    </section>

    <!-- Incidents & Service Health Grid -->
    <div class="dashboard-grid">
      <!-- Incidents Panel -->
      <section class="glass-panel" aria-label="Active Incidents">
        <div class="panel-header">
          <span>Incidents</span>
          <span style="font-size: 11px; color: var(--rose); font-weight: 800;">1 ACTIVE</span>
        </div>
        <div class="panel-body">
          <div class="incident-item">
            <div class="incident-header">
              <span class="severity-tag">CRITICAL</span>
              <span class="incident-time">2 min ago</span>
            </div>
            <div class="incident-title">Service degraded</div>
            <div class="incident-condition">Condition: Service Availability Degradation</div>
          </div>
        </div>
      </section>

      <!-- Service Health Panel -->
      <section class="glass-panel" aria-label="Service Health Status">
        <div class="panel-header">
          <span>Service Health</span>
          <span style="font-size: 11px; color: var(--emerald); font-weight: 800;">ALL NORMAL</span>
        </div>
        <div class="panel-body">
          <div class="services-list">
            <div class="service-row">
              <div class="service-left">
                <span class="service-dot"></span>
                <span class="service-name">API</span>
              </div>
              <span class="service-status-text">Healthy</span>
            </div>
            <div class="service-row">
              <div class="service-left">
                <span class="service-dot"></span>
                <span class="service-name">Database</span>
              </div>
              <span class="service-status-text">Healthy</span>
            </div>
            <div class="service-row">
              <div class="service-left">
                <span class="service-dot"></span>
                <span class="service-name">EC2</span>
              </div>
              <span class="service-status-text">Healthy</span>
            </div>
            <div class="service-row">
              <div class="service-left">
                <span class="service-dot"></span>
                <span class="service-name">SSM</span>
              </div>
              <span class="service-status-text">Connected</span>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- AI Root Cause Analysis -->
    <section class="glass-panel rca-section" aria-label="AI Root Cause Analysis">
      <div class="rca-header">
        <div class="rca-title-wrap">
          <span class="rca-icon">🤖</span>
          <span class="rca-title">AI Root Cause Analysis</span>
        </div>
        <div class="confidence-badge">Confidence: <span id="conf-val">96%</span></div>
      </div>

      <div class="rca-field">
        <div class="rca-label">Root Cause</div>
        <div class="rca-root-cause-box" id="rca-root-cause-text">
          FastAPI service stopped responding to health checks
        </div>
      </div>

      <div class="rca-field">
        <div class="rca-label">Evidence</div>
        <ul class="evidence-list" id="evidence-list-container">
          <li class="evidence-item"><span class="evidence-check">✓</span> Health check failures</li>
          <li class="evidence-item"><span class="evidence-check">✓</span> Error traces</li>
          <li class="evidence-item"><span class="evidence-check">✓</span> Service telemetry</li>
        </ul>
      </div>

      <div class="rca-field">
        <div class="rca-label">Recommended Action</div>
        <div class="recommended-action-box">
          <span class="action-code">RESTART_OPS23_SERVICE</span>
          <span class="action-badge">TARGET: i-066478e6fd6dc22af</span>
        </div>
      </div>

      <!-- Human Approval Controls -->
      <div class="action-bar">
        <div class="approver-input-wrap">
          <label for="approver-name">Approver:</label>
          <input type="text" id="approver-name" class="approver-input" value="Prabhu" placeholder="Operator name">
        </div>
        <button id="btn-reject" class="btn btn-reject" onclick="handleReject()">Reject</button>
        <button id="btn-approve" class="btn btn-approve" onclick="handleApprove()">Approve</button>
        <button id="btn-execute" class="btn btn-execute" onclick="handleExecute()" disabled>Execute</button>
      </div>
    </section>

    <!-- Remediation Timeline -->
    <section class="glass-panel timeline-section" aria-label="Remediation Timeline">
      <div class="timeline-header">Remediation Timeline</div>
      <div class="timeline-steps" id="timeline-container">
        <div class="timeline-step completed" id="step-1">
          <div class="step-marker">✓</div>
          <div class="step-content">
            <div class="step-title">● Incident detected</div>
            <div class="step-detail">Alert: Service Availability Degradation</div>
          </div>
        </div>

        <div class="timeline-step completed" id="step-2">
          <div class="step-marker">✓</div>
          <div class="step-content">
            <div class="step-title">● AI RCA completed</div>
            <div class="step-detail">Bedrock Claude 3 Haiku diagnosis (Confidence 96%)</div>
          </div>
        </div>

        <div class="timeline-step active" id="step-3">
          <div class="step-marker"></div>
          <div class="step-content">
            <div class="step-title" id="step-3-title">● Awaiting Human Approval</div>
            <div class="step-detail" id="step-3-detail">Action required by SRE Operator</div>
          </div>
        </div>

        <div class="timeline-step waiting" id="step-4">
          <div class="step-marker"></div>
          <div class="step-content">
            <div class="step-title">● Lambda → SSM</div>
            <div class="step-detail">Dispatch systemctl restart ops23-nr.service</div>
          </div>
        </div>

        <div class="timeline-step waiting" id="step-5">
          <div class="step-marker"></div>
          <div class="step-content">
            <div class="step-title">✓ Service recovered</div>
            <div class="step-detail">Health verification & incident resolved</div>
          </div>
        </div>
      </div>
    </section>
  </div>

  <!-- Toast Notification -->
  <div id="toast" class="toast-banner">
    <span id="toast-icon">ℹ️</span>
    <span id="toast-message">Message</span>
  </div>

  <script>
    let currentApprovalId = null;
    const authHeaders = {
      'Content-Type': 'application/json',
      'X-Approval-Token': 'ops23-dev-approval-token',
    };

    function showToast(msg, icon = 'ℹ️') {
      const toast = document.getElementById('toast');
      document.getElementById('toast-message').innerText = msg;
      document.getElementById('toast-icon').innerText = icon;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 4000);
    }

    async function initDashboard() {
      try {
        // Load live overview
        const res = await fetch('/api/v1/dashboard/overview');
        if (res.ok) {
          const data = await res.json();
          document.getElementById('cpu-val').innerText = data.telemetry.cpu_percent;
          document.getElementById('cpu-bar').style.width = data.telemetry.cpu_percent + '%';
          document.getElementById('mem-val').innerText = data.telemetry.memory_percent;
          document.getElementById('mem-bar').style.width = data.telemetry.memory_percent + '%';
        }

        // Initialize active pending approval in backend
        await createOrFetchApproval();
      } catch (err) {
        console.error('Failed to init dashboard:', err);
      }
    }

    async function createOrFetchApproval() {
      try {
        const payload = {
          incident_id: "INC-8143846-992",
          service: "ops23-nr.service",
          target: "i-066478e6fd6dc22af",
          recommended_action: "RESTART_OPS23_SERVICE",
          root_cause: "FastAPI service stopped responding to health checks",
          confidence: 0.96,
          decision: "ALLOWLISTED_RECOMMENDATION",
          execution_allowed: false,
          evidence: [
            "Health check failures (HTTP 502)",
            "Error traces indicate socket exhaustion",
            "Service telemetry shows memory peak at 94%"
          ],
          reasoning_summary: "Deterministic allowlisted restart will safely clear transient worker failure."
        };

        const res = await fetch('/api/v1/remediation/approvals', {
          method: 'POST',
          headers: authHeaders,
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          const rec = await res.json();
          currentApprovalId = rec.approval_id;
          console.log("Active Approval ID initialized:", currentApprovalId);
          return currentApprovalId;
        } else {
          const err = await res.json().catch(() => ({}));
          console.error("Failed to initialize approval record:", res.status, err);
          return null;
        }
      } catch (err) {
        console.error('Approval creation network error:', err);
        return null;
      }
    }

    async function handleApprove() {
      const approver = document.getElementById('approver-name').value.trim() || 'Prabhu';
      const btnApprove = document.getElementById('btn-approve');
      const btnReject = document.getElementById('btn-reject');
      const btnExecute = document.getElementById('btn-execute');

      btnApprove.disabled = true;
      btnReject.disabled = true;

      try {
        if (!currentApprovalId) {
          currentApprovalId = await createOrFetchApproval();
        }

        if (!currentApprovalId) {
          showToast('Failed to create pending approval in backend.', '❌');
          btnApprove.disabled = false;
          btnReject.disabled = false;
          return;
        }

        const res = await fetch(`/api/v1/remediation/approvals/${currentApprovalId}/approve`, {
          method: 'POST',
          headers: { ...authHeaders, 'X-Approver-Id': approver },
          body: JSON.stringify({ approved_by: approver, notes: "Authorized via Operations Center" })
        });

        if (res.ok) {
          showToast(`Remediation approved by ${approver}`, '✅');
          // Update timeline
          const step3 = document.getElementById('step-3');
          step3.classList.remove('active');
          step3.classList.add('completed');
          step3.querySelector('.step-marker').innerText = '✓';
          document.getElementById('step-3-title').innerText = `● Approved by ${approver}`;
          document.getElementById('step-3-detail').innerText = `Explicit human authorization granted`;

          const step4 = document.getElementById('step-4');
          step4.classList.remove('waiting');
          step4.classList.add('active');

          btnExecute.disabled = false;
        } else {
          const err = await res.json().catch(() => ({ detail: 'Approval request failed' }));
          showToast(err.detail || 'Approval failed', '❌');
          btnApprove.disabled = false;
          btnReject.disabled = false;
        }
      } catch (err) {
        showToast('Approval request error: ' + err.message, '❌');
        btnApprove.disabled = false;
      }
    }

    async function handleReject() {
      const rejector = document.getElementById('approver-name').value.trim() || 'Prabhu';
      try {
        if (!currentApprovalId) {
          currentApprovalId = await createOrFetchApproval();
        }

        if (!currentApprovalId) {
          showToast('No active approval found to reject.', '❌');
          return;
        }

        const res = await fetch(`/api/v1/remediation/approvals/${currentApprovalId}/reject`, {
          method: 'POST',
          headers: { ...authHeaders, 'X-Approver-Id': rejector },
          body: JSON.stringify({ rejected_by: rejector, reason: "Operator manual override" })
        });

        if (res.ok) {
          showToast(`Remediation rejected by ${rejector}`, '🛑');
          document.getElementById('btn-approve').disabled = true;
          document.getElementById('btn-reject').disabled = true;
          document.getElementById('btn-execute').disabled = true;

          const step3 = document.getElementById('step-3');
          step3.classList.remove('active');
          document.getElementById('step-3-title').innerText = `● Rejected by ${rejector}`;
          document.getElementById('step-3-detail').innerText = `Manual operator intervention required`;
        }
      } catch (err) {
        showToast('Rejection error: ' + err.message, '❌');
      }
    }

    async function handleExecute() {
      const executor = document.getElementById('approver-name').value.trim() || 'Prabhu';
      const btnExecute = document.getElementById('btn-execute');
      btnExecute.disabled = true;

      showToast('Dispatching to Phase 6 Remediation Lambda...', '⚡');

      try {
        const res = await fetch(`/api/v1/remediation/approvals/${currentApprovalId}/execute`, {
          method: 'POST',
          headers: { ...authHeaders, 'X-Approver-Id': executor },
          body: JSON.stringify({ executed_by: executor })
        });

        if (res.ok) {
          const rec = await res.json();
          showToast('SSM Command Executed: ' + (rec.ssm_command_id || 'Success'), '🚀');

          // Advance timeline step 4
          const step4 = document.getElementById('step-4');
          step4.classList.remove('active');
          step4.classList.add('completed');
          step4.querySelector('.step-marker').innerText = '✓';

          // Advance timeline step 5
          const step5 = document.getElementById('step-5');
          step5.classList.remove('waiting');
          step5.classList.add('completed');
          step5.querySelector('.step-marker').innerText = '✓';

          // Update Status
          document.getElementById('system-status-text').innerText = 'SYSTEM RECOVERED';
        } else {
          const err = await res.json().catch(() => ({ detail: 'Execution dispatch failed' }));
          showToast(err.detail || 'Execution failed', '❌');
          btnExecute.disabled = false;
        }
      } catch (err) {
        showToast('Execution error: ' + err.message, '❌');
        btnExecute.disabled = false;
      }
    }

    // Auto-refresh telemetry every 10 seconds
    setInterval(async () => {
      try {
        const res = await fetch('/api/v1/dashboard/overview');
        if (res.ok) {
          const data = await res.json();
          document.getElementById('cpu-val').innerText = data.telemetry.cpu_percent;
          document.getElementById('cpu-bar').style.width = data.telemetry.cpu_percent + '%';
          document.getElementById('mem-val').innerText = data.telemetry.memory_percent;
          document.getElementById('mem-bar').style.width = data.telemetry.memory_percent + '%';
        }
      } catch (e) {}
    }, 10000);

    window.addEventListener('DOMContentLoaded', initDashboard);
  </script>
</body>
</html>
"""


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Ops23-NR Intelligent Cloud Operations Center",
    description="Interactive Human-in-the-Loop SRE Command Center dashboard.",
)
async def dashboard_page() -> HTMLResponse:
    """Renders the single-page Operations Center dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML, status_code=status.HTTP_200_OK)
