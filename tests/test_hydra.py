import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.adapters import hydra
from obliquity.core.database import (
    add_host,
    add_login_job,
    connect,
    create_project,
    delete_login_job,
    get_found_credentials,
    get_history,
    get_login_job,
    insert_found_credentials,
    list_login_jobs,
)
from obliquity.core.loginplan import LoginStage, load_loginplan


def _job(**overrides) -> dict:
    base = {
        "service": "ssh", "target": "10.0.0.5", "port": None,
        "form_spec": None, "module_args": None, "name": None,
    }
    base.update(overrides)
    return base


class BuildCommandTests(TestCase):
    def test_single_credentials_ssh(self) -> None:
        stage = LoginStage(name="s", username="admin", password="admin", tasks=1, stop_on_first_valid=True)
        cmd = hydra.build_command(_job(port=2222), stage, Path("/out.json"))
        self.assertEqual(cmd[0], "hydra")
        self.assertIn("-l", cmd)
        self.assertIn("admin", cmd)
        self.assertEqual(cmd[cmd.index("-s") + 1], "2222")
        self.assertIn("-f", cmd)
        self.assertEqual(cmd[cmd.index("-t") + 1], "1")
        # target then service are the last positionals
        self.assertEqual(cmd[-2:], ["10.0.0.5", "ssh"])

    def test_lists_use_capital_flags(self) -> None:
        stage = LoginStage(name="s", userlist="/u.txt", passlist="/p.txt")
        cmd = hydra.build_command(_job(), stage, Path("/out.json"))
        self.assertIn("-L", cmd)
        self.assertIn("-P", cmd)
        self.assertNotIn("-l", cmd)

    def test_form_service_appends_form_spec(self) -> None:
        stage = LoginStage(name="s", username="a", password="b")
        spec = "/login:user=^USER^&pass=^PASS^:F=bad"
        cmd = hydra.build_command(_job(service="http-post-form", target="h", form_spec=spec), stage, Path("/o.json"))
        self.assertEqual(cmd[-3:], ["h", "http-post-form", spec])

    def test_form_service_without_spec_raises(self) -> None:
        stage = LoginStage(name="s", username="a", password="b")
        with self.assertRaises(ValueError):
            hydra.build_command(_job(service="http-post-form", target="h"), stage, Path("/o.json"))

    def test_unknown_service_raises(self) -> None:
        stage = LoginStage(name="s", username="a", password="b")
        with self.assertRaises(ValueError):
            hydra.build_command(_job(service="carrier-pigeon"), stage, Path("/o.json"))


class ParseOutputTests(TestCase):
    def _parse(self, text: str):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "creds.json"
            out.write_text(text, encoding="utf-8")
            return hydra.parse_output(out, run_id=1, project_id=1, job_id=1, service="ssh", target="10.0.0.5", source="s")

    def test_parses_json_results(self) -> None:
        text = json.dumps({"results": [
            {"host": "10.0.0.5", "port": 22, "service": "ssh", "login": "root", "password": "toor"},
        ]})
        creds = self._parse(text)
        self.assertEqual(len(creds), 1)
        self.assertEqual(creds[0]["username"], "root")
        self.assertEqual(creds[0]["password"], "toor")

    def test_text_fallback(self) -> None:
        text = "[22][ssh] host: 10.0.0.5   login: root   password: toor\n"
        creds = self._parse(text)
        self.assertEqual(len(creds), 1)
        self.assertEqual(creds[0]["username"], "root")
        self.assertEqual(creds[0]["password"], "toor")

    def test_empty_when_no_creds(self) -> None:
        self.assertEqual(self._parse(json.dumps({"results": []})), [])

    def test_missing_file(self) -> None:
        creds = hydra.parse_output(Path("/no/such.json"), run_id=1, project_id=1, job_id=1, service="ssh", target="t", source="s")
        self.assertEqual(creds, [])


class LoginPlanTests(TestCase):
    def test_stage_requires_user_and_pass(self) -> None:
        with self.assertRaises(ValueError):
            LoginStage(name="s", username="a")  # no password/passlist
        with self.assertRaises(ValueError):
            LoginStage(name="s", password="b")  # no username/userlist

    def test_load_builtin_shape(self) -> None:
        from obliquity.core.loginplan import find_builtin_loginplan
        plan = load_loginplan(find_builtin_loginplan("smoke-test"))
        self.assertEqual(plan.name, "smoke-test")
        self.assertEqual(len(plan.stages), 1)


class LoginJobDbTests(TestCase):
    def test_add_list_get_delete(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            job = add_login_job(conn, p["id"], service="ssh", target="10.0.0.5", name="ssh-box", port=22)
            self.assertEqual(job["service"], "ssh")
            self.assertEqual(len(list_login_jobs(conn, p["id"])), 1)
            self.assertIsNotNone(get_login_job(conn, p["id"], "ssh-box"))
            self.assertIsNotNone(get_login_job(conn, p["id"], "10.0.0.5"))  # by target too
            self.assertTrue(delete_login_job(conn, p["id"], "ssh-box"))
            self.assertEqual(list_login_jobs(conn, p["id"]), [])

    def test_host_link_and_credentials_and_history(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            host = add_host(conn, p["id"], "https://app.acme.test")
            job = add_login_job(conn, p["id"], service="http-post-form", target="app.acme.test",
                                name="web", host_id=host["id"], form_spec="/l:u=^USER^&p=^PASS^:F=no")
            # simulate a run row + found credential
            from obliquity.core.database import create_or_update_login_run
            run = create_or_update_login_run(conn, p["id"], job["id"], "quick", "s1", "fp1", "hydra ...", "/raw", "/res")
            inserted = insert_found_credentials(conn, [{
                "run_id": run["id"], "project_id": p["id"], "job_id": job["id"],
                "service": "http-post-form", "target": "app.acme.test",
                "username": "admin", "password": "hunter2", "source": "s1",
            }])
            self.assertEqual(inserted, 1)
            creds = get_found_credentials(conn, p["id"])
            self.assertEqual(creds[0]["username"], "admin")
            self.assertEqual(creds[0]["password"], "hunter2")
            # dedup on re-insert
            self.assertEqual(insert_found_credentials(conn, [{
                "run_id": run["id"], "project_id": p["id"], "job_id": job["id"],
                "service": "http-post-form", "target": "app.acme.test",
                "username": "admin", "password": "hunter2", "source": "s1",
            }]), 0)
            # history includes the hydra run
            hist = get_history(conn, p["id"])
            tools = {row["tool"] for row in hist}
            self.assertIn("hydra", tools)
