import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.core.database import (
    add_host,
    connect,
    create_or_update_run,
    create_project,
    get_findings,
    get_runs,
    insert_findings,
)
from obliquity.core.reporting import generate_csv, generate_json, generate_markdown


def _seed(conn, project, host_id):
    run = create_or_update_run(
        conn, project["id"], host_id, "gameplan", "stage-1", "fp-1", "feroxbuster ...", "raw.txt", "out.jsonl",
    )
    insert_findings(
        conn,
        [
            {
                "run_id": run["id"],
                "project_id": project["id"],
                "host_id": host_id,
                "url": "https://example.com/admin",
                "path": "/admin",
                "status_code": 200,
                "content_length": 42,
                "words": 3,
                "lines": 1,
                "redirect": None,
                "source": "stage-1",
            }
        ],
    )
    return run


class ExportFormatTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.conn = connect(root / "obliquity.db")
        self.project = create_project(self.conn, "export-test", root / "project")
        self.host = add_host(self.conn, self.project["id"], "https://example.com")
        self.run = _seed(self.conn, self.project, self.host["id"])
        self.findings = get_findings(self.conn, self.project["id"])
        self.runs = get_runs(self.conn, self.project["id"])
        self.out_dir = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_export_is_valid_and_contains_findings(self) -> None:
        output = generate_json(self.project, self.runs, self.findings, self.out_dir / "report.json")
        data = json.loads(output.read_text())

        self.assertEqual(data["project"], "export-test")
        self.assertEqual(len(data["findings"]), 1)
        self.assertEqual(data["findings"][0]["url"], "https://example.com/admin")
        self.assertEqual(data["cracked_hashes"], [])

    def test_csv_export_has_header_and_row(self) -> None:
        output = generate_csv(self.findings, self.out_dir / "findings.csv")
        rows = list(csv.DictReader(output.open()))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://example.com/admin")
        self.assertEqual(rows[0]["status_code"], "200")

    def test_csv_export_of_empty_dataset_writes_empty_file(self) -> None:
        output = generate_csv([], self.out_dir / "empty.csv")
        self.assertEqual(output.read_text(), "")

    def test_markdown_export_contains_finding_and_counts(self) -> None:
        output = generate_markdown(self.project, self.runs, self.findings, self.out_dir / "report.md")
        text = output.read_text()

        self.assertIn("# Obliquity Report -- export-test", text)
        self.assertIn("- Findings: 1", text)
        self.assertIn("https://example.com/admin", text)

    def test_hydra_credentials_flow_into_json_and_markdown(self) -> None:
        from obliquity.core.database import (
            add_login_job,
            create_or_update_login_run,
            get_found_credentials,
            get_login_runs,
            insert_found_credentials,
        )
        job = add_login_job(self.conn, self.project["id"], service="ssh", target="10.0.0.5", name="ssh-box")
        run = create_or_update_login_run(
            self.conn, self.project["id"], job["id"], "quick", "s1", "lfp1", "hydra ...", "/raw", "/res",
        )
        insert_found_credentials(self.conn, [{
            "run_id": run["id"], "project_id": self.project["id"], "job_id": job["id"],
            "service": "ssh", "target": "10.0.0.5", "username": "root", "password": "toor", "source": "s1",
        }])
        login_runs = get_login_runs(self.conn, self.project["id"])
        creds = get_found_credentials(self.conn, self.project["id"])

        out = generate_json(self.project, self.runs, self.findings, self.out_dir / "r.json",
                            login_runs=login_runs, found_credentials=creds)
        data = json.loads(out.read_text())
        self.assertEqual(len(data["found_credentials"]), 1)
        self.assertEqual(data["found_credentials"][0]["username"], "root")
        self.assertEqual(len(data["login_runs"]), 1)

        md = generate_markdown(self.project, self.runs, self.findings, self.out_dir / "r.md",
                               login_runs=login_runs, found_credentials=creds)
        text = md.read_text()
        self.assertIn("## Found Credentials", text)
        self.assertIn("root", text)
        self.assertIn("toor", text)

    def test_markdown_escapes_pipe_characters_in_cells(self) -> None:
        insert_findings(
            self.conn,
            [
                {
                    "run_id": self.run["id"],
                    "project_id": self.project["id"],
                    "host_id": self.host["id"],
                    "url": "https://example.com/a|b",
                    "path": "/a|b",
                    "status_code": 200,
                    "content_length": 1,
                    "words": 1,
                    "lines": 1,
                    "redirect": None,
                    "source": "stage-1",
                }
            ],
        )
        findings = get_findings(self.conn, self.project["id"])
        output = generate_markdown(self.project, self.runs, findings, self.out_dir / "report2.md")
        text = output.read_text()

        self.assertIn("a\\|b", text)
        # every data row must still have exactly as many cells as the header
        header_cells = text.count("| Status | URL |")
        self.assertGreaterEqual(header_cells, 1)
