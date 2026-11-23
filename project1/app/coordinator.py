import time
import json
import asyncio
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from app.db import (
    save_agent_run,
    update_agent_run,
    log_agent_activity,
    update_incident_status,
    save_incident_report
)
from app.agents import (
    LogInvestigatorAgent,
    ResearchAgent,
    TimelineAnalystAgent,
    ReportWriterAgent
)

class Coordinator:
    """
    Coordinator Agent:
    - Turns user incident report/alert into a multi-phase investigation plan.
    - Launches, tracks, and monitors specialized agents.
    - Handles retries on agent and tool failures with bounds.
    - Emits real-time WebSocket events for instantaneous updates.
    - Aggregates structured findings into a final verified incident report.
    """
    def __init__(self, incident_id: str, broadcaster: Optional[Callable] = None):
        self.incident_id = incident_id
        self.name = "coordinator"
        self.broadcaster = broadcaster

    def _emit(self, event_type: str, data: Any):
        if self.broadcaster:
            try:
                # Attempt to schedule onto active loop or run in fresh event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.broadcaster(self.incident_id, event_type, data), loop)
                else:
                    loop.run_until_complete(self.broadcaster(self.incident_id, event_type, data))
            except Exception:
                try:
                    new_loop = asyncio.new_event_loop()
                    new_loop.run_until_complete(self.broadcaster(self.incident_id, event_type, data))
                    new_loop.close()
                except Exception:
                    pass

    def log_and_broadcast(self, agent_name: str, level: str, message: str, details: Optional[Dict] = None):
        log_agent_activity(self.incident_id, agent_name, level, message, details)
        self._emit("AGENT_LOG", {
            "incident_id": self.incident_id,
            "agent_name": agent_name,
            "level": level,
            "message": message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "details": details or {}
        })

    def execute_investigation(self, incident: Dict[str, Any], raw_logs: List[str], status_pages: List[Dict[str, Any]]):
        try:
            self.log_and_broadcast(self.name, "INFO", "Coordinator initiating real-time multi-agent investigation.")

            # Phase 1: Planning
            plan = [
                {
                    "step": 1,
                    "agent": "log_investigator",
                    "role": "Log Investigator",
                    "goal": f"Parse raw logs, extract timestamps, error signatures, and affected services for {incident.get('service')}."
                },
                {
                    "step": 2,
                    "agent": "research_agent",
                    "role": "Research Agent",
                    "goal": "Check public & internal status endpoints, fetch latest incident notices, handle retries on flaky probes."
                },
                {
                    "step": 3,
                    "agent": "timeline_analyst",
                    "role": "Timeline Analyst",
                    "goal": "Align logs, status alerts, and deployment markers into chronological sequence with confidence markers."
                },
                {
                    "step": 4,
                    "agent": "report_writer",
                    "role": "Report Writer",
                    "goal": "Draft final evidence-backed report with verified facts, hypotheses, and prioritized non-destructive next steps."
                }
            ]

            plan_summary = "Structured 4-phase investigation plan: Logs Analysis -> Status Page Research -> Timeline Synthesis -> Executive Report."
            update_incident_status(self.incident_id, "investigating", plan_summary, plan)
            self._emit("PLAN_CREATED", {"plan": plan, "plan_summary": plan_summary})
            self.log_and_broadcast(self.name, "INFO", "Investigation plan established and broadcasted to agents.", {"plan": plan})

            # Phase 2: Log Investigator
            log_agent_run_id = f"{self.incident_id}-log-inv"
            run_data = {
                "id": log_agent_run_id,
                "incident_id": self.incident_id,
                "agent_name": "log_investigator",
                "role_label": "Log Investigator",
                "status": "running",
                "started_at": datetime.utcnow().isoformat() + "Z",
                "inputs_json": {"service": incident.get("service"), "log_count": len(raw_logs)}
            }
            save_agent_run(run_data)
            self._emit("AGENT_STATUS", run_data)

            log_investigator = LogInvestigatorAgent(self.incident_id)
            time.sleep(0.7) # visible real-time cadence
            log_findings = log_investigator.run(raw_logs, incident.get("service", "unknown"))

            update_data = {
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat() + "Z",
                "outputs_json": log_findings
            }
            update_agent_run(log_agent_run_id, update_data)
            self._emit("AGENT_STATUS", {"id": log_agent_run_id, "agent_name": "log_investigator", **update_data})

            # Phase 3: Research Agent (Status Pages)
            research_agent_run_id = f"{self.incident_id}-research"
            run_data = {
                "id": research_agent_run_id,
                "incident_id": self.incident_id,
                "agent_name": "research_agent",
                "role_label": "Research Agent",
                "status": "running",
                "started_at": datetime.utcnow().isoformat() + "Z",
                "inputs_json": {"status_pages_count": len(status_pages)}
            }
            save_agent_run(run_data)
            self._emit("AGENT_STATUS", run_data)

            research_agent = ResearchAgent(self.incident_id)
            time.sleep(0.7)
            research_findings = research_agent.run(status_pages, max_retries=2)

            update_data = {
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat() + "Z",
                "outputs_json": research_findings
            }
            update_agent_run(research_agent_run_id, update_data)
            self._emit("AGENT_STATUS", {"id": research_agent_run_id, "agent_name": "research_agent", **update_data})

            # Phase 4: Timeline Analyst
            timeline_run_id = f"{self.incident_id}-timeline"
            run_data = {
                "id": timeline_run_id,
                "incident_id": self.incident_id,
                "agent_name": "timeline_analyst",
                "role_label": "Timeline Analyst",
                "status": "running",
                "started_at": datetime.utcnow().isoformat() + "Z",
                "inputs_json": {"timeframe": incident.get("timeframe")}
            }
            save_agent_run(run_data)
            self._emit("AGENT_STATUS", run_data)

            timeline_analyst = TimelineAnalystAgent(self.incident_id)
            time.sleep(0.7)
            timeline_findings = timeline_analyst.run(
                incident.get("alert_text", ""),
                incident.get("timeframe", ""),
                log_findings,
                research_findings,
                raw_logs
            )

            update_data = {
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat() + "Z",
                "outputs_json": timeline_findings
            }
            update_agent_run(timeline_run_id, update_data)
            self._emit("AGENT_STATUS", {"id": timeline_run_id, "agent_name": "timeline_analyst", **update_data})

            # Phase 5: Report Writer
            report_run_id = f"{self.incident_id}-report"
            run_data = {
                "id": report_run_id,
                "incident_id": self.incident_id,
                "agent_name": "report_writer",
                "role_label": "Report Writer",
                "status": "running",
                "started_at": datetime.utcnow().isoformat() + "Z",
                "inputs_json": {"incident_id": self.incident_id}
            }
            save_agent_run(run_data)
            self._emit("AGENT_STATUS", run_data)

            report_writer = ReportWriterAgent(self.incident_id)
            time.sleep(0.7)
            final_report = report_writer.run(
                incident,
                log_findings,
                research_findings,
                timeline_findings
            )

            update_data = {
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat() + "Z",
                "outputs_json": final_report
            }
            update_agent_run(report_run_id, update_data)
            self._emit("AGENT_STATUS", {"id": report_run_id, "agent_name": "report_writer", **update_data})

            # Save completed report and update status
            save_incident_report(final_report)
            update_incident_status(self.incident_id, "completed")
            self.log_and_broadcast(self.name, "INFO", "Incident investigation successfully concluded. Final report persisted.")
            self._emit("REPORT_COMPLETED", final_report)

        except Exception as e:
            error_str = f"Coordinator encountered critical execution failure: {str(e)}"
            tb = traceback.format_exc()
            self.log_and_broadcast(self.name, "ERROR", error_str, {"traceback": tb})
            update_incident_status(self.incident_id, "failed")
            self._emit("INCIDENT_FAILED", {"error": error_str})

