"""Cross-surface parity: desktop pairing, backups, automation, recycle bin.

Everything here is exercised through the same API/service layer the desktop
UI binds to, so a passing suite means both faces can do the same things.
"""

from __future__ import annotations

from app.server.pairing import PairingError, PairingRegistry


# ------------------------------------------------------------------ pairing


class TestPairingRegistry:
    def test_issue_then_redeem_round_trips_the_identity(self):
        registry = PairingRegistry()
        identity = {"sub": 1, "username": "admin", "email": "a@b.c",
                    "role": "administrator", "auth_provider": "password"}
        entry = registry.issue_code(identity, label="Desk")
        assert "-" in entry["code"] and entry["expires_in"] > 0
        assert registry.redeem_code(entry["code"])["username"] == "admin"

    def test_codes_are_single_use(self):
        registry = PairingRegistry()
        entry = registry.issue_code({"sub": 1})
        registry.redeem_code(entry["code"])
        try:
            registry.redeem_code(entry["code"])
        except PairingError as exc:
            assert "Unknown" in str(exc)
        else:
            raise AssertionError("a spent code was accepted twice")

    def test_unknown_code_is_rejected(self):
        registry = PairingRegistry()
        try:
            registry.redeem_code("NOPE-NOPE")
        except PairingError:
            pass
        else:
            raise AssertionError("an unknown code was accepted")

    def test_lowercase_input_is_normalised(self):
        registry = PairingRegistry()
        entry = registry.issue_code({"sub": 7})
        assert registry.redeem_code(entry["code"].lower())["sub"] == 7

    def test_quota_limits_live_codes_per_identity(self):
        registry = PairingRegistry()
        for _ in range(3):
            registry.issue_code({"sub": 1})
        try:
            registry.issue_code({"sub": 1})
        except PairingError as exc:
            assert "Too many" in str(exc)
        else:
            raise AssertionError("quota not enforced")

    def test_expired_codes_are_purged_and_rejected(self):
        import time as _time
        registry = PairingRegistry()
        entry = registry.issue_code({"sub": 1})
        # age the entry beyond its ttl without sleeping
        code = entry["code"]
        registry._codes[code]["expires_at"] = _time.time() - 1
        try:
            registry.redeem_code(code)
        except PairingError as exc:
            assert "expired" in str(exc).lower()
        else:
            raise AssertionError("an expired code was accepted")
        assert registry.purge() == 0  # already consumed on the failed attempt


class TestPairingEndpoints:
    def test_web_session_can_issue_and_desktop_can_redeem(self, client, auth):
        created = client.post("/api/pairing/code", json={"label": "Desk"},
                              headers=auth)
        assert created.status_code == 201, created.text
        code = created.json()["code"]

        redeemed = client.post("/api/pairing/redeem",
                               json={"code": code, "device_id": "ws-9"})
        assert redeemed.status_code == 200, redeemed.text
        body = redeemed.json()
        assert body["user"]["username"] == "admin"
        assert body["identity"]["username"] == "admin"
        assert body["token"]

    def test_redeemed_code_cannot_be_reused(self, client, auth):
        code = client.post("/api/pairing/code", json={}, headers=auth).json()["code"]
        client.post("/api/pairing/redeem", json={"code": code})
        again = client.post("/api/pairing/redeem", json={"code": code})
        assert again.status_code == 401


# ------------------------------------------------------------------ backups


class TestBackupEndpoints:
    def test_create_and_list_backups(self, client, auth):
        made = client.post("/api/backups", headers=auth)
        assert made.status_code == 201, made.text
        assert made.json()["created"].endswith(".db")

        listed = client.get("/api/backups", headers=auth)
        assert listed.status_code == 200
        assert any(b["name"] == made.json()["created"]
                   for b in listed.json())

    def test_prune_reports_removed_count(self, client, auth):
        pruned = client.post("/api/backups/prune", headers=auth)
        assert pruned.status_code == 200
        assert pruned.json()["removed"] == 0

    def test_backups_require_settings_permission(self, client):
        signup = client.post("/api/auth/signup", json={
            "username": "visitor", "display_name": "Visitor",
            "password": "longpassword1"})
        assert signup.status_code == 201
        headers = {"Authorization": f"Bearer {signup.json()['token']}"}
        assert client.get("/api/backups", headers=headers).status_code == 403


# --------------------------------------------------------------- automation


class TestAutomationEndpoints:
    def test_rule_lifecycle(self, client, auth):
        made = client.post("/api/automation/rules", headers=auth, json={
            "name": "watch", "fact": "patients_total", "operator": ">",
            "threshold": 0, "action": "log"})
        assert made.status_code == 201, made.text
        rule_id = made.json()["rule_id"]

        listed = client.get("/api/automation/rules", headers=auth)
        assert [r["rule_id"] for r in listed.json()] == [rule_id]

        deleted = client.delete(f"/api/automation/rules/{rule_id}",
                                headers=auth)
        assert deleted.status_code == 200
        assert client.get("/api/automation/rules", headers=auth).json() == []

    def test_invalid_rule_is_rejected(self, client, auth):
        bad = client.post("/api/automation/rules", headers=auth, json={
            "name": "x", "fact": "not_a_fact", "operator": ">",
            "threshold": 1, "action": "log"})
        assert bad.status_code == 400

    def test_run_once_reports_each_rule(self, client, auth):
        client.post("/api/automation/rules", headers=auth, json={
            "name": "never fires", "fact": "patients_total", "operator": "<",
            "threshold": -1, "action": "log"})
        report = client.post("/api/automation/run", headers=auth)
        assert report.status_code == 200
        assert report.json() and report.json()[0]["fired"] is False


# -------------------------------------------------------------- recycle bin


class TestRecycleBinEndpoint:
    def test_delete_then_list_then_restore(self, client, auth, repos):
        made = client.post("/api/patients", headers=auth, json={
            "name": "Bin Test", "age": 30, "phone": "+234 803 555 0199"})
        assert made.status_code == 201, made.text
        pid = made.json()["patient_id"]

        assert client.delete(f"/api/patients/{pid}", headers=auth).status_code in (200, 204)

        listed = client.get("/api/patients/deleted", headers=auth)
        assert listed.status_code == 200, listed.text
        assert [p["patient_id"] for p in listed.json()] == [pid]

        restored = client.post(f"/api/patients/{pid}/restore", headers=auth)
        assert restored.status_code == 200
        assert client.get("/api/patients/deleted", headers=auth).json() == []
