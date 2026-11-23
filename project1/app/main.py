import os
import json
import uuid
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.db import (
    init_db,
    save_incident,
    get_incident,
    list_incidents,
    get_agent_runs,
    get_agent_logs,
    get_incident_report
)
from app.coordinator import Coordinator

# Initialize database schema
init_db()

app = FastAPI(title="OpsPilot - Multi-Agent Incident Response", version="1.0.0")

# WebSocket Connection Manager for instantaneous Real-Time streaming
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, incident_id: str, websocket: WebSocket):
        await websocket.accept()
        if incident_id not in self.active_connections:
            self.active_connections[incident_id] = []
        self.active_connections[incident_id].append(websocket)

    def disconnect(self, incident_id: str, websocket: WebSocket):
        if incident_id in self.active_connections:
            if websocket in self.active_connections[incident_id]:
                self.active_connections[incident_id].remove(websocket)
            if not self.active_connections[incident_id]:
                del self.active_connections[incident_id]

    async def broadcast_event(self, incident_id: str, event_type: str, data: Any):
        if incident_id in self.active_connections:
            dead_connections = []
            payload = json.dumps({"type": event_type, "data": data})
            for connection in self.active_connections[incident_id]:
                try:
                    await connection.send_text(payload)
                except Exception:
                    dead_connections.append(connection)
            for dead in dead_connections:
                if dead in self.active_connections.get(incident_id, []):
                    self.active_connections[incident_id].remove(dead)

ws_manager = ConnectionManager()

# Setup template and static file directories
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Load seeded scenarios
SCENARIOS_PATH = os.path.join(BASE_DIR, "data", "scenarios.json")
def load_scenarios():
    if os.path.exists(SCENARIOS_PATH):
        with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# Request Models
class CreateIncidentRequest(BaseModel):
    title: str
    service: str
    timeframe: Optional[str] = "Last 60 minutes"
    alert_text: str
    description: Optional[str] = ""
    logs_text: Optional[str] = ""
    scenario_id: Optional[str] = None

@app.websocket("/ws/incidents/{incident_id}")
async def websocket_endpoint(websocket: WebSocket, incident_id: str):
    await ws_manager.connect(incident_id, websocket)
    try:
        # Send initial snapshot immediately upon connection
        inc = get_incident(incident_id)
        if inc:
            runs = get_agent_runs(incident_id)
            logs = get_agent_logs(incident_id)
            report = get_incident_report(incident_id)
            await websocket.send_text(json.dumps({
                "type": "SNAPSHOT",
                "data": {
                    "incident": inc,
                    "agent_runs": runs,
                    "logs": logs,
                    "report": report
                }
            }))
        while True:
            # Keep socket alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(incident_id, websocket)
    except Exception:
        ws_manager.disconnect(incident_id, websocket)

@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    scenarios = load_scenarios()
    incidents = list_incidents()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "scenarios": scenarios,
        "incidents": incidents
    })

@app.get("/api/scenarios")
def api_get_scenarios():
    return load_scenarios()

@app.get("/api/incidents")
def api_list_incidents():
    return list_incidents()

def run_coordinator_job(incident_id: str, incident_data: dict, raw_logs: list, status_pages: list):
    coordinator = Coordinator(incident_id, broadcaster=ws_manager.broadcast_event)
    coordinator.execute_investigation(incident_data, raw_logs, status_pages)

@app.post("/api/incidents")
def api_create_incident(payload: CreateIncidentRequest, background_tasks: BackgroundTasks):
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    
    # Process scenario defaults or custom user logs
    scenarios = load_scenarios()
    selected_scenario = next((s for s in scenarios if s.get("id") == payload.scenario_id), None)
    
    raw_logs = []
    status_pages = []

    if payload.logs_text and payload.logs_text.strip():
        raw_logs = [line.strip() for line in payload.logs_text.strip().split("\n") if line.strip()]
    elif selected_scenario:
        raw_logs = selected_scenario.get("logs", [])
    else:
        # Default fallback log simulation
        raw_logs = [
            f"2026-11-23T14:00:00.000Z [{payload.service}] [INFO] Normal traffic flow recorded",
            f"2026-11-23T14:05:12.100Z [{payload.service}] [WARN] Latency threshold warning: 450ms > 200ms",
            f"2026-11-23T14:10:04.550Z [{payload.service}] [ERROR] Request dropped: 504 Gateway Timeout while contacting upstream dependency",
            f"2026-11-23T14:12:30.900Z [{payload.service}] [ERROR] CircuitBreaker tripped: failure rate 85%"
        ]

    if selected_scenario:
        status_pages = selected_scenario.get("status_pages", [])
    else:
        status_pages = [
            {"name": "Cloud Provider Health", "url": "https://health.aws.amazon.com", "status": "Operational"},
            {"name": "Payment Gateway Status", "url": "https://status.stripe.com", "status": "Degraded Performance", "recent_incident": "Simulated upstream latency on payment processing API"},
            {"name": "Auth Identity Provider", "url": "https://status.auth0.com", "status": "Operational"},
            {"name": "Downstream Telemetry Gateway", "url": "https://status.internal-monitoring.corp/healthz", "status": "Unreachable / 503"}
        ]

    incident_data = {
        "id": incident_id,
        "title": payload.title,
        "service": payload.service,
        "timeframe": payload.timeframe or "Recent window",
        "alert_text": payload.alert_text,
        "description": payload.description or "",
        "status": "created"
    }

    save_incident(incident_data)

    # Launch coordinator workflow in background task with real-time websocket broadcasting
    background_tasks.add_task(run_coordinator_job, incident_id, incident_data, raw_logs, status_pages)

    return {"incident_id": incident_id, "status": "started", "message": "Coordinator has initiated real-time investigation plan."}

@app.get("/api/incidents/{incident_id}")
def api_get_incident_detail(incident_id: str):
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    agent_runs = get_agent_runs(incident_id)
    logs = get_agent_logs(incident_id)
    report = get_incident_report(incident_id)

    return {
        "incident": inc,
        "agent_runs": agent_runs,
        "logs": logs,
        "report": report
    }

