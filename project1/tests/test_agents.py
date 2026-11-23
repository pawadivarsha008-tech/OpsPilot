import time
from app.db import init_db, save_incident, get_incident, get_agent_runs, get_agent_logs, get_incident_report
from app.coordinator import Coordinator
from app.tools import OpsTools

def test_tools():
    print("Testing OpsTools...")
    logs = [
        "2026-11-23T13:45:18.892Z [checkout-service] [ERROR] POST /v1/orders/checkout failed - 504 Gateway Timeout",
        "2026-11-23T13:46:01.012Z [checkout-service] [WARN] High memory usage"
    ]
    res = OpsTools.search_logs(logs, level_filter="ERROR")
    assert res["error_count"] == 1
    assert len(res["matches"]) == 1
    print(" OpsTools.search_logs verified.")

    status_res = OpsTools.check_status_page("Stripe Status", "https://status.stripe.com", mock_data={"status": "Degraded"})
    assert status_res["status"] == "Degraded"
    print(" OpsTools.check_status_page verified.")

    fail_probe = OpsTools.check_status_page("Internal Hub", "https://status.internal-payment.corp/healthz", mock_data={"status": "Unreachable / 503"})
    assert fail_probe["is_available"] == False
    print(" OpsTools resilient failure probe verified.")

def test_full_coordinator_flow():
    print("\nTesting Full Coordinator & Multi-Agent Flow...")
    init_db()
    incident_data = {
        "id": "test-inc-001",
        "title": "Test Checkout Outage",
        "service": "checkout-service",
        "timeframe": "Last 30 mins",
        "alert_text": "504 Spike on Checkout API",
        "description": "Integration test incident run",
        "status": "created"
    }

    raw_logs = [
        "2026-11-23T13:42:15.102Z [checkout-service] [INFO] Deployment canary v2.14.0 promoted",
        "2026-11-23T13:45:02.431Z [checkout-service] [WARN] ConnectionPoolTimeoutException: Timeout waiting for idle connection",
        "2026-11-23T13:45:18.892Z [checkout-service] [ERROR] POST /v1/orders/checkout failed - 504 Gateway Timeout",
        "2026-11-23T13:46:01.012Z [checkout-service] [ERROR] CircuitBreaker 'StripeClient' OPEN: failure rate 85.0%",
        "2026-11-23T13:52:45.918Z [checkout-service] [FATAL] OOMKilled container checkout-service-pod"
    ]

    status_pages = [
        {"name": "Stripe Status", "url": "https://status.stripe.com", "status": "Degraded Performance", "recent_incident": "Simulated latency"},
        {"name": "Internal Legacy Hub", "url": "https://status.internal.corp/healthz", "status": "Unreachable / 503"}
    ]

    save_incident(incident_data)
    coordinator = Coordinator(incident_data["id"])
    coordinator.execute_investigation(incident_data, raw_logs, status_pages)

    # Assertions
    inc = get_incident("test-inc-001")
    assert inc["status"] == "completed", f"Expected completed, got {inc['status']}"

    runs = get_agent_runs("test-inc-001")
    assert len(runs) == 4, f"Expected 4 agent runs, got {len(runs)}"
    for r in runs:
        assert r["status"] == "completed", f"Agent {r['agent_name']} failed: {r['error_message']}"
    print(f" Verified all {len(runs)} agents executed successfully.")

    logs = get_agent_logs("test-inc-001")
    assert len(logs) > 5, "Expected activity logs from agents."
    print(f" Verified {len(logs)} activity events recorded on telemetry bus.")

    report = get_incident_report("test-inc-001")
    assert report is not None
    assert report["likely_cause"] != ""
    assert len(report["timeline"]) > 0
    assert len(report["verified_facts"]) > 0
    assert len(report["hypotheses"]) > 0
    assert len(report["recommended_actions"]) > 0
    print(" Verified structured incident report generated with verified facts, hypotheses, and actions.")
    print("\nALL BACKEND & AGENT TESTS PASSED!")

if __name__ == "__main__":
    test_tools()
    test_full_coordinator_flow()
