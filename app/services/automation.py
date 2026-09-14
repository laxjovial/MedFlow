"""Automation rules: tiny, safe "if X then Y" workflows.

A rule watches one fact about the database (count, age, presence) and
fires an action when its condition holds. Rules are data, not code —
users create them in Settings, and the engine logs every run so nothing
happens silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.utils.dates import to_iso, utcnow

FACTS = {
    "patients_total": "Total active patients",
    "appointments_today": "Appointments scheduled today",
    "critical_labs": "Critical lab results",
    "active_diagnoses": "Active or chronic diagnoses",
    "deleted_patients": "Soft-deleted patient records",
}

OPERATORS = {
    ">": "is greater than",
    ">=": "is at least",
    "<": "is less than",
    "==": "equals",
}

ACTIONS = {
    "backup": "Create a database backup",
    "log": "Write an entry to the log",
}

OPERATION_FUNCTIONS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


@dataclass
class Rule:
    """One declarative automation rule."""

    rule_id: str
    name: str
    fact: str                    # key of FACTS
    operator: str                # key of OPERATORS
    threshold: float
    action: str                  # key of ACTIONS
    enabled: bool = True
    last_run_at: str | None = None
    last_run_result: str | None = None
    run_count: int = 0

    def describe(self) -> str:
        return (f"When {FACTS.get(self.fact, self.fact)} "
                f"{OPERATORS.get(self.operator, self.operator)} "
                f"{self.threshold:g} → {ACTIONS.get(self.action, self.action)}")

    def to_row(self) -> dict:
        return {
            "rule_id": self.rule_id, "name": self.name, "fact": self.fact,
            "operator": self.operator, "threshold": self.threshold,
            "action": self.action, "enabled": self.enabled,
            "last_run_at": self.last_run_at,
            "last_run_result": self.last_run_result,
            "run_count": self.run_count,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Rule":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in row.items() if k in known})


class AutomationEngine:
    """Evaluates rules against live metrics and runs matched actions."""

    def __init__(self, repos, backup_service=None, log_sink=None):
        self.repos = repos
        self.backup = backup_service
        self.log_sink = log_sink or (lambda msg: None)
        self.rules: dict[str, Rule] = {}
        self._next_id = 1

    # ------------------------------------------------------------------ #
    # rule management

    def add_rule(self, name: str, fact: str, operator: str,
                 threshold: float, action: str) -> Rule:
        if fact not in FACTS:
            raise ValueError(f"Unknown fact '{fact}'. Choose from: {', '.join(FACTS)}")
        if operator not in OPERATORS:
            raise ValueError(f"Unknown operator '{operator}'.")
        if action not in ACTIONS:
            raise ValueError(f"Unknown action '{action}'.")
        rule = Rule(
            rule_id=f"rule-{self._next_id}", name=name.strip() or "Untitled rule",
            fact=fact, operator=operator, threshold=threshold, action=action,
        )
        self._next_id += 1
        self.rules[rule.rule_id] = rule
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        return self.rules.pop(rule_id, None) is not None

    def set_enabled(self, rule_id: str, enabled: bool) -> Rule | None:
        rule = self.rules.get(rule_id)
        if rule:
            rule.enabled = bool(enabled)
        return rule

    def list_rules(self) -> list[Rule]:
        return list(self.rules.values())

    # ------------------------------------------------------------------ #
    # evaluation

    def _current_fact(self, fact: str):
        if fact == "patients_total":
            return self.repos["patients"].count()
        if fact == "appointments_today":
            return self.repos["stats"].dashboard()["appointments_today"]
        if fact == "critical_labs":
            return self.repos["stats"].dashboard()["critical_labs"]
        if fact == "active_diagnoses":
            return self.repos["stats"].dashboard()["active_diagnoses"]
        if fact == "deleted_patients":
            return self.repos["stats"].dashboard()["deleted_patients"]
        return None

    def _run_action(self, rule: Rule) -> str:
        if rule.action == "backup":
            if self.backup is None:
                return "skipped: no backup service configured"
            path = self.backup.create_backup(label=f"auto_{rule.rule_id}")
            return f"backup created: {path.name}"
        if rule.action == "log":
            self.log_sink(f"Automation '{rule.name}' fired: {rule.describe()}")
            return "logged"
        return "unknown action"

    def run_once(self) -> list[dict]:
        """Evaluate every enabled rule once; returns a run report."""
        report = []
        for rule in self.rules.values():
            if not rule.enabled:
                continue
            value = self._current_fact(rule.fact)
            fired = value is not None and OPERATION_FUNCTIONS[rule.operator](value, rule.threshold)
            result = "condition not met"
            if fired:
                try:
                    result = self._run_action(rule)
                except Exception as exc:      # never kill the caller
                    result = f"error: {exc}"
            rule.run_count += 1
            rule.last_run_at = to_iso(utcnow())
            rule.last_run_result = result
            report.append({
                "rule_id": rule.rule_id, "name": rule.name,
                "fact_value": value, "fired": bool(fired), "result": result,
            })
        return report
