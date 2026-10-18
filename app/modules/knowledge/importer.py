"""Knowledge base import/export and log parsing."""
import json
import re
from datetime import datetime
from typing import Any

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC, KnowledgeFormula, KnowledgeTerm


def parse_elm_log(content: str) -> list[dict]:
    """Parse ELM327/AT command log (request/response pairs with timestamps)."""
    lines = content.strip().split("\n")
    pairs = []
    current_req = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Try to extract timestamp and hex command
        # Format: "2024-10-18 10:30:45 > 01 00" or "> 01 00"
        match = re.match(r"(?:(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+)?([><])\s+(.+)", line)
        if match:
            timestamp, direction, data = match.groups()
            if direction == ">":
                current_req = {"timestamp": timestamp, "request": data.upper().strip(), "response": None}
            elif direction == "<" and current_req:
                current_req["response"] = data.upper().strip()
                pairs.append(current_req)
                current_req = None
    return pairs


def parse_gscan_log(content: str) -> list[dict]:
    """Parse G-Scan output (simplified: extract hex request/response lines)."""
    lines = content.strip().split("\n")
    pairs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Look for patterns like "REQ: 22 1050" or "RES: 62 1050 12 34"
        req_match = re.match(r"(?:REQ|Request|발신|>)\s*[:：]?\s*([0-9A-Fa-f\s]+)", line)
        res_match = re.match(r"(?:RES|Response|수신|<)\s*[:：]?\s*([0-9A-Fa-f\s]+)", line)
        if req_match:
            pairs.append({"request": req_match.group(1).upper().strip(), "response": None})
        elif res_match and pairs and pairs[-1]["response"] is None:
            pairs[-1]["response"] = res_match.group(1).upper().strip()
    return pairs


def diff_against_known(parsed_pairs: list[dict], maker: str | None = None) -> dict:
    """Compare parsed request/response pairs against known commands and formulas."""
    from app.modules.knowledge.service import list_commands, list_formulas
    
    known_commands = {c.command: c for c in list_commands(status="verified", maker=maker, limit=1000)}
    known_formulas = {f.command: f for f in list_formulas(status="verified", maker=maker, limit=1000)}
    
    results = {
        "known": [],
        "unknown_request": [],
        "unknown_response": [],
        "new_did_pid": [],
    }
    
    for pair in parsed_pairs:
        req = pair.get("request", "").replace(" ", "")
        resp = pair.get("response", "").replace(" ", "") if pair.get("response") else None
        
        if not req:
            continue
        
        # Check if request is known
        matched = False
        for cmd_str, cmd_obj in known_commands.items():
            if cmd_str.replace(" ", "").upper() in req:
                results["known"].append({
                    "request": req,
                    "response": resp,
                    "matched_command": cmd_str,
                    "label": cmd_obj.label,
                })
                matched = True
                break
        
        if not matched:
            # Unknown request
            results["unknown_request"].append({"request": req, "response": resp})
            
            # Check for potential DIDs/PIDs (service 22 or 01)
            if req.startswith("22") and len(req) >= 6:
                did = req[2:6]
                results["new_did_pid"].append({
                    "service": "22",
                    "pid": did,
                    "request": req,
                    "response": resp,
                })
            elif req.startswith("01") and len(req) >= 4:
                pid = req[2:4]
                results["new_did_pid"].append({
                    "service": "01",
                    "pid": pid,
                    "request": req,
                    "response": resp,
                })
    
    return results


def seed_standard_obd2() -> int:
    """Seed knowledge base with standard OBD2 data (SAE J1979 mode 01 PIDs, DTCs, NRCs)."""
    count = 0
    
    # Standard OBD2 Mode 01 PIDs (공개 표준)
    standard_pids = [
        {"pid": "00", "label": "PIDs supported [01-20]", "formula": "bitmask", "unit": None},
        {"pid": "04", "label": "Calculated engine load", "formula": "A * 100 / 255", "unit": "%"},
        {"pid": "05", "label": "Engine coolant temperature", "formula": "A - 40", "unit": "°C"},
        {"pid": "0C", "label": "Engine RPM", "formula": "((A * 256) + B) / 4", "unit": "rpm"},
        {"pid": "0D", "label": "Vehicle speed", "formula": "A", "unit": "km/h"},
        {"pid": "11", "label": "Throttle position", "formula": "A * 100 / 255", "unit": "%"},
        {"pid": "1F", "label": "Run time since engine start", "formula": "(A * 256) + B", "unit": "s"},
        {"pid": "21", "label": "Distance traveled with MIL on", "formula": "(A * 256) + B", "unit": "km"},
        {"pid": "2F", "label": "Fuel Tank Level Input", "formula": "A * 100 / 255", "unit": "%"},
        {"pid": "A6", "label": "Odometer", "formula": "((A * 16777216) + (B * 65536) + (C * 256) + D) / 10", "unit": "km"},
    ]
    
    for pid_data in standard_pids:
        existing = db.session.query(KnowledgeFormula).filter_by(
            command=f"01 {pid_data['pid']}", source="SAE_J1979"
        ).first()
        if not existing:
            formula = KnowledgeFormula(
                maker=None,
                command=f"01 {pid_data['pid']}",
                pid=pid_data["pid"],
                label=pid_data["label"],
                formula=pid_data["formula"],
                unit=pid_data["unit"],
                source="SAE_J1979",
                source_detail="SAE J1979 standard OBD2 PID",
                status="verified",
                confidence=1.0,
            )
            db.session.add(formula)
            count += 1
    
    # Common UDS services
    uds_services = [
        {"command": "10 01", "label": "Diagnostic Session Control - Default Session"},
        {"command": "10 03", "label": "Diagnostic Session Control - Extended Diagnostic Session"},
        {"command": "14 FF FF FF", "label": "Clear Diagnostic Information"},
        {"command": "19 02 FF", "label": "Read DTC by status mask"},
        {"command": "3E 00", "label": "Tester Present"},
    ]
    
    for svc in uds_services:
        existing = db.session.query(KnowledgeCommand).filter_by(
            command=svc["command"], source="ISO_14229"
        ).first()
        if not existing:
            cmd = KnowledgeCommand(
                command=svc["command"],
                label=svc["label"],
                source="ISO_14229",
                source_detail="ISO 14229 (UDS) standard service",
                status="verified",
                confidence=1.0,
            )
            db.session.add(cmd)
            count += 1
    
    # Common NRC codes as terms
    nrc_codes = [
        {"term": "NRC 7F", "definition": "Service Not Supported", "category": "UDS NRC"},
        {"term": "NRC 78", "definition": "Response Pending", "category": "UDS NRC"},
        {"term": "NRC 22", "definition": "Conditions Not Correct", "category": "UDS NRC"},
        {"term": "NRC 31", "definition": "Request Out Of Range", "category": "UDS NRC"},
    ]
    
    for nrc in nrc_codes:
        existing = db.session.query(KnowledgeTerm).filter_by(term=nrc["term"]).first()
        if not existing:
            term = KnowledgeTerm(
                term=nrc["term"],
                definition=nrc["definition"],
                category=nrc["category"],
                source="ISO_14229",
                status="verified",
            )
            db.session.add(term)
            count += 1
    
    # Generic P0xxx DTCs (OBD2 standard, 공개)
    generic_dtcs = [
        {"code": "P0000", "description": "No fault detected"},
        {"code": "P0100", "description": "Mass or Volume Air Flow Circuit Malfunction"},
        {"code": "P0171", "description": "System Too Lean (Bank 1)"},
        {"code": "P0300", "description": "Random/Multiple Cylinder Misfire Detected"},
    ]
    
    for dtc in generic_dtcs:
        existing = db.session.query(KnowledgeDTC).filter_by(code=dtc["code"], source="SAE_J2012").first()
        if not existing:
            dtc_obj = KnowledgeDTC(
                code=dtc["code"],
                description=dtc["description"],
                category="Powertrain",
                source="SAE_J2012",
                source_detail="SAE J2012 generic OBD2 DTC",
                status="verified",
                confidence=1.0,
            )
            db.session.add(dtc_obj)
            count += 1
    
    db.session.commit()
    return count


def export_knowledge_json() -> dict:
    """Export all verified knowledge to JSON."""
    commands = db.session.query(KnowledgeCommand).filter_by(status="verified").all()
    formulas = db.session.query(KnowledgeFormula).filter_by(status="verified").all()
    dtcs = db.session.query(KnowledgeDTC).filter_by(status="verified").all()
    terms = db.session.query(KnowledgeTerm).filter_by(status="verified").all()
    
    return {
        "exported_at": datetime.utcnow().isoformat(),
        "commands": [
            {
                "maker": c.maker,
                "model": c.model,
                "ecu_name": c.ecu_name,
                "command": c.command,
                "label": c.label,
                "description": c.description,
                "source": c.source,
            }
            for c in commands
        ],
        "formulas": [
            {
                "maker": f.maker,
                "model": f.model,
                "ecu_name": f.ecu_name,
                "command": f.command,
                "pid": f.pid,
                "label": f.label,
                "formula": f.formula,
                "unit": f.unit,
                "source": f.source,
            }
            for f in formulas
        ],
        "dtcs": [
            {
                "maker": d.maker,
                "model": d.model,
                "code": d.code,
                "description": d.description,
                "severity": d.severity,
                "source": d.source,
            }
            for d in dtcs
        ],
        "terms": [
            {
                "term": t.term,
                "abbreviation": t.abbreviation,
                "definition": t.definition,
                "category": t.category,
                "source": t.source,
            }
            for t in terms
        ],
    }


def import_knowledge_json(data: dict) -> int:
    """Import knowledge from JSON (as draft)."""
    count = 0
    
    for cmd_data in data.get("commands", []):
        existing = db.session.query(KnowledgeCommand).filter_by(
            command=cmd_data["command"],
            maker=cmd_data.get("maker"),
            model=cmd_data.get("model"),
        ).first()
        if not existing:
            cmd = KnowledgeCommand(
                maker=cmd_data.get("maker"),
                model=cmd_data.get("model"),
                ecu_name=cmd_data.get("ecu_name"),
                command=cmd_data["command"],
                label=cmd_data.get("label"),
                description=cmd_data.get("description"),
                source=cmd_data.get("source", "import"),
                status="draft",
            )
            db.session.add(cmd)
            count += 1
    
    for f_data in data.get("formulas", []):
        existing = db.session.query(KnowledgeFormula).filter_by(
            command=f_data.get("command"),
            pid=f_data.get("pid"),
            maker=f_data.get("maker"),
        ).first()
        if not existing:
            formula = KnowledgeFormula(
                maker=f_data.get("maker"),
                model=f_data.get("model"),
                ecu_name=f_data.get("ecu_name"),
                command=f_data.get("command"),
                pid=f_data.get("pid"),
                label=f_data["label"],
                formula=f_data["formula"],
                unit=f_data.get("unit"),
                source=f_data.get("source", "import"),
                status="draft",
            )
            db.session.add(formula)
            count += 1
    
    for d_data in data.get("dtcs", []):
        existing = db.session.query(KnowledgeDTC).filter_by(
            code=d_data["code"],
            maker=d_data.get("maker"),
        ).first()
        if not existing:
            dtc = KnowledgeDTC(
                maker=d_data.get("maker"),
                model=d_data.get("model"),
                code=d_data["code"],
                description=d_data["description"],
                severity=d_data.get("severity"),
                source=d_data.get("source", "import"),
                status="draft",
            )
            db.session.add(dtc)
            count += 1
    
    for t_data in data.get("terms", []):
        existing = db.session.query(KnowledgeTerm).filter_by(term=t_data["term"]).first()
        if not existing:
            term = KnowledgeTerm(
                term=t_data["term"],
                abbreviation=t_data.get("abbreviation"),
                definition=t_data["definition"],
                category=t_data.get("category"),
                source=t_data.get("source", "import"),
                status="draft",
            )
            db.session.add(term)
            count += 1
    
    db.session.commit()
    return count
