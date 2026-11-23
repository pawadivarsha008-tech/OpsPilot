import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

DB_FILE = os.path.join(os.path.dirname(__file__), "opspilot.db")

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incidents (
        id TEXT PRIMARY KEY,
        title TEXT,
        service TEXT,
        timeframe TEXT,
        alert_text TEXT,
        description TEXT,
        status TEXT, -- 'created', 'investigating', 'completed', 'failed'
        created_at TEXT,
        updated_at TEXT,
        plan_summary TEXT,
        plan_json TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY,
        incident_id TEXT,
        agent_name TEXT, -- 'coordinator', 'log_investigator', 'research_agent', 'timeline_analyst', 'report_writer'
        role_label TEXT,
        status TEXT, -- 'pending', 'running', 'completed', 'failed', 'retrying'
        retry_count INTEGER DEFAULT 0,
        started_at TEXT,
        completed_at TEXT,
        inputs_json TEXT,
        outputs_json TEXT,
        error_message TEXT,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id TEXT,
        agent_name TEXT,
        timestamp TEXT,
        level TEXT, -- 'INFO', 'WARN', 'ERROR', 'TOOL'
        message TEXT,
        details_json TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incident_reports (
        incident_id TEXT PRIMARY KEY,
        summary TEXT,
        likely_cause TEXT,
        confidence_level TEXT,
        confidence_score REAL,
        timeline_json TEXT,
        evidence_json TEXT,
        recommended_actions_json TEXT,
        unanswered_questions_json TEXT,
        verified_facts_json TEXT,
        hypotheses_json TEXT,
        created_at TEXT,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """)

    conn.commit()
    conn.close()

def save_incident(incident_data: Dict[str, Any]):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.utcnow().isoformat() + "Z"
    c.execute("""
    INSERT OR REPLACE INTO incidents 
    (id, title, service, timeframe, alert_text, description, status, created_at, updated_at, plan_summary, plan_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        incident_data["id"],
        incident_data.get("title", "Untitled Incident"),
        incident_data.get("service", "unknown"),
        incident_data.get("timeframe", ""),
        incident_data.get("alert_text", ""),
        incident_data.get("description", ""),
        incident_data.get("status", "created"),
        incident_data.get("created_at", now),
        now,
        incident_data.get("plan_summary", ""),
        json.dumps(incident_data.get("plan_json", {}))
    ))
    conn.commit()
    conn.close()

def update_incident_status(incident_id: str, status: str, plan_summary: Optional[str] = None, plan_json: Optional[Any] = None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.utcnow().isoformat() + "Z"
    if plan_summary is not None and plan_json is not None:
        c.execute("""
        UPDATE incidents SET status = ?, updated_at = ?, plan_summary = ?, plan_json = ? WHERE id = ?
        """, (status, now, plan_summary, json.dumps(plan_json), incident_id))
    else:
        c.execute("UPDATE incidents SET status = ?, updated_at = ? WHERE id = ?", (status, now, incident_id))
    conn.commit()
    conn.close()

def get_incident(incident_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("plan_json"):
        try:
            d["plan_json"] = json.loads(d["plan_json"])
        except:
            pass
    return d

def list_incidents() -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM incidents ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("plan_json"):
            try:
                d["plan_json"] = json.loads(d["plan_json"])
            except:
                pass
        result.append(d)
    return result

def save_agent_run(run_data: Dict[str, Any]):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO agent_runs
    (id, incident_id, agent_name, role_label, status, retry_count, started_at, completed_at, inputs_json, outputs_json, error_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_data["id"],
        run_data["incident_id"],
        run_data["agent_name"],
        run_data.get("role_label", run_data["agent_name"]),
        run_data.get("status", "pending"),
        run_data.get("retry_count", 0),
        run_data.get("started_at"),
        run_data.get("completed_at"),
        json.dumps(run_data.get("inputs_json", {})),
        json.dumps(run_data.get("outputs_json", {})),
        run_data.get("error_message")
    ))
    conn.commit()
    conn.close()

def update_agent_run(run_id: str, updates: Dict[str, Any]):
    conn = get_connection()
    c = conn.cursor()
    fields = []
    values = []
    for k, v in updates.items():
        if k in ("inputs_json", "outputs_json"):
            fields.append(f"{k} = ?")
            values.append(json.dumps(v))
        else:
            fields.append(f"{k} = ?")
            values.append(v)
    values.append(run_id)
    c.execute(f"UPDATE agent_runs SET {', '.join(fields)} WHERE id = ?", tuple(values))
    conn.commit()
    conn.close()

def get_agent_runs(incident_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM agent_runs WHERE incident_id = ? ORDER BY started_at ASC", (incident_id,))
    rows = c.fetchall()
    conn.close()
    runs = []
    for r in rows:
        d = dict(r)
        if d.get("inputs_json"):
            try:
                d["inputs_json"] = json.loads(d["inputs_json"])
            except:
                pass
        if d.get("outputs_json"):
            try:
                d["outputs_json"] = json.loads(d["outputs_json"])
            except:
                pass
        runs.append(d)
    return runs

def log_agent_activity(incident_id: str, agent_name: str, level: str, message: str, details: Optional[Dict] = None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.utcnow().isoformat() + "Z"
    c.execute("""
    INSERT INTO agent_logs (incident_id, agent_name, timestamp, level, message, details_json)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (incident_id, agent_name, now, level, message, json.dumps(details or {})))
    conn.commit()
    conn.close()

def get_agent_logs(incident_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM agent_logs WHERE incident_id = ? ORDER BY id ASC", (incident_id,))
    rows = c.fetchall()
    conn.close()
    logs = []
    for r in rows:
        d = dict(r)
        if d.get("details_json"):
            try:
                d["details_json"] = json.loads(d["details_json"])
            except:
                pass
        logs.append(d)
    return logs

def save_incident_report(report_data: Dict[str, Any]):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.utcnow().isoformat() + "Z"
    c.execute("""
    INSERT OR REPLACE INTO incident_reports
    (incident_id, summary, likely_cause, confidence_level, confidence_score, timeline_json, evidence_json, recommended_actions_json, unanswered_questions_json, verified_facts_json, hypotheses_json, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        report_data["incident_id"],
        report_data.get("summary", ""),
        report_data.get("likely_cause", ""),
        report_data.get("confidence_level", "Medium"),
        report_data.get("confidence_score", 0.75),
        json.dumps(report_data.get("timeline", [])),
        json.dumps(report_data.get("evidence", [])),
        json.dumps(report_data.get("recommended_actions", [])),
        json.dumps(report_data.get("unanswered_questions", [])),
        json.dumps(report_data.get("verified_facts", [])),
        json.dumps(report_data.get("hypotheses", [])),
        now
    ))
    conn.commit()
    conn.close()

def get_incident_report(incident_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM incident_reports WHERE incident_id = ?", (incident_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for field in ["timeline_json", "evidence_json", "recommended_actions_json", "unanswered_questions_json", "verified_facts_json", "hypotheses_json"]:
        if d.get(field):
            try:
                d[field.replace("_json", "")] = json.loads(d[field])
            except:
                d[field.replace("_json", "")] = []
    return d

init_db()
