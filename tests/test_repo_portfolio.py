from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "repo_portfolio.py"
PYTHON = os.environ.get("REPO_PORTFOLIO_PYTHON", "python3.12")


class RepoPortfolioBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: str = "") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_tool(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [PYTHON, str(SCRIPT), *args], capture_output=True, text=True, check=False
        )
        if check and result.returncode:
            self.fail(f"Command failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        return result

    def analyze(self, *extra: str) -> Path:
        self.run_tool("analyze", str(self.root), *extra)
        return self.root / ".repo-portfolio"

    def read(self, out: Path, relative: str):
        return json.loads((out / relative).read_text(encoding="utf-8"))

    def init_git(self, authors: list[tuple[str, str]]) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        for index, (name, email) in enumerate(authors):
            self.write(f"history-{index}.txt", str(index))
            subprocess.run(["git", "add", f"history-{index}.txt"], cwd=self.root, check=True)
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": name,
                "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": name,
                "GIT_COMMITTER_EMAIL": email,
            }
            subprocess.run(["git", "commit", "-q", "-m", f"change {index}"], cwd=self.root, env=env, check=True)

    def test_scenario_a_small_python_cli(self) -> None:
        self.write("pyproject.toml", '[project]\nname = "sample-cli"\n')
        self.write("src/app.py", "import argparse\nparser = argparse.ArgumentParser()\n")
        self.write("tests/test_app.py", "def test_cli():\n    assert True\n")
        self.write("README.md", "# Sample CLI\n")
        self.init_git([("Developer", "dev@example.test")])
        out = self.analyze("--static")
        profile = self.read(out, "project_profile.json")
        plan = self.read(out, "analysis_plan.json")
        self.assertIn("Python", profile["ecosystems"])
        self.assertIn("command_line_tool", profile["project_types"])
        self.assertIn("web_specific", plan["explicitly_skipped"])
        self.assertEqual(self.run_tool("validate", str(self.root)).returncode, 0)

    def test_scenario_b_cad_bim_plugin_and_screenshot(self) -> None:
        self.write("Plugin.csproj", '<Reference Include="RhinoCommon" />')
        self.write("Components/GeometryComponent.cs", "class GeometryComponent {}")
        self.write("installer/setup.wxs", "Rhino plugin installer")
        image = self.root / "screenshots" / "workflow.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"\x89PNG\r\n\x1a\n")
        out = self.analyze("--static")
        profile = self.read(out, "project_profile.json")
        media = self.read(out, "media/media_index.json")
        self.assertIn("host_application_plugin", profile["project_types"])
        self.assertIn("Rhino/Grasshopper", profile["ecosystems"])
        self.assertEqual(media["items"][0]["source"], "screenshots/workflow.png")
        self.assertFalse(profile["capabilities"]["database"])

    def test_scenario_c_web_application(self) -> None:
        self.write("package.json", '{"dependencies":{"react":"1","express":"1","prisma":"1"}}')
        self.write("src/App.tsx", "export const App = () => <main />")
        self.write("server/routes.ts", "export const routes = []")
        self.write(".github/workflows/ci.yml", "jobs: {}")
        self.write("deploy/Dockerfile", "FROM scratch")
        out = self.analyze("--static")
        profile = self.read(out, "project_profile.json")
        domains = {d["domain"] for d in self.read(out, "analysis_plan.json")["domains"]}
        self.assertIn("web_application", profile["project_types"])
        self.assertTrue(profile["capabilities"]["database"])
        self.assertIn("web", domains)
        self.assertIn("delivery", domains)

    def test_scenario_d_poorly_documented_repository_keeps_unknowns(self) -> None:
        self.write("src/process.lua", "function transform(value) return value end")
        self.init_git([("Old Dev", "old@example.test")])
        out = self.analyze()
        self.assertFalse(self.read(out, "project_profile.json")["capabilities"]["documentation"])
        self.assertTrue(self.read(out, "project.json")["unknowns"])
        self.assertIn("## High Value", (out / "open_questions.md").read_text())

    def test_scenario_e_external_video_is_indexed_without_false_claims(self) -> None:
        self.write("main.py", "print('static source only')")
        external = self.root.parent / f"{self.root.name}-demo.mp4"
        external.write_bytes(b"not-a-real-video")
        try:
            out = self.analyze("--static", "--media", str(external))
            media = self.read(out, "media/media_index.json")
            self.assertEqual(len(media["items"]), 1)
            self.assertTrue(media["items"][0]["source"].startswith("external:"))
            self.assertTrue(media["warnings"])
            claims = self.read(out, "evidence.json")["claims"]
            self.assertFalse(any("reliable" in c["claim"].lower() for c in claims))
        finally:
            external.unlink(missing_ok=True)

    def test_scenario_f_contradictory_user_answer_is_preserved(self) -> None:
        self.write("tests/test_feature.py", "def test_feature(): assert True")
        out = self.analyze()
        observed = self.read(out, "observed_evidence.json")["claims"]
        target = next(c for c in observed if c["category"] == "testing")
        payload = {
            "question": {"id": "CTX-001", "answer": "There were no automated tests."},
            "claims": [{
                "category": "testing",
                "claim": "The user remembers that the project had no automated tests.",
                "status": "USER_CONFIRMED",
                "interview_question_id": "CTX-001",
                "contradicts": [target["id"]],
            }],
        }
        payload_path = self.write("answer.json", json.dumps(payload))
        self.run_tool("ingest", str(self.root), "--kind", "interview", "--input", str(payload_path))
        evidence = self.read(out, "evidence.json")["claims"]
        contradicted = next(c for c in evidence if c["id"] == target["id"])
        self.assertEqual(contradicted["status"], "CONTRADICTED")
        self.assertTrue(contradicted["contradicts"])
        self.assertEqual(self.run_tool("validate", str(self.root)).returncode, 0)

    def test_scenario_g_team_repository_does_not_infer_personal_ownership(self) -> None:
        self.write("main.go", "package main")
        self.init_git([("One", "one@example.test"), ("Two", "two@example.test")])
        out = self.analyze("--static")
        ownership = [c for c in self.read(out, "evidence.json")["claims"] if c["category"] == "ownership"]
        self.assertTrue(ownership)
        self.assertTrue(all("does not establish" in c["claim"] for c in ownership))

    def test_scenario_h_unknown_technology_gets_dynamic_brief(self) -> None:
        self.write("engine/main.zzz", "BEGIN UNKNOWN_ENGINE")
        out = self.analyze("--static")
        profile = self.read(out, "project_profile.json")
        domains = {d["domain"] for d in self.read(out, "analysis_plan.json")["domains"]}
        self.assertIn("unknown_software_project", profile["project_types"])
        self.assertIn("unknown_ecosystem_brief", domains)
        self.assertIn("unknown_ecosystem", self.read(out, "project.json")["extensions"])

    def test_scenario_i_static_mode_never_queues_question(self) -> None:
        self.write("main.rs", "fn main() {}")
        out = self.analyze("--static")
        response = json.loads(self.run_tool("next-question", str(self.root)).stdout)
        self.assertIsNone(response["question"])
        self.assertEqual(self.read(out, "session.json")["phase"], "static_complete")
        self.assertTrue(self.read(out, "project.json")["unknowns"])

    def test_scenario_j_resume_retains_answers_and_pending_question(self) -> None:
        self.write("main.py", "print('hello')")
        out = self.analyze()
        first = json.loads(self.run_tool("next-question", str(self.root)).stdout)["question"]
        payload = {
            "question": {"id": first["id"], "answer": "Solo project."},
            "claims": [{
                "category": "ownership", "claim": "The project was completed solo.",
                "status": "USER_CONFIRMED", "interview_question_id": first["id"]
            }],
        }
        payload_path = self.write("resume-answer.json", json.dumps(payload))
        self.run_tool("ingest", str(self.root), "--kind", "interview", "--input", str(payload_path))
        second = json.loads(self.run_tool("next-question", str(self.root)).stdout)["question"]
        self.run_tool("analyze", str(self.root))
        resumed = json.loads(self.run_tool("next-question", str(self.root)).stdout)
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["question"]["id"], second["id"])
        interview = self.read(out, "interview_evidence.json")
        self.assertEqual(interview["questions"][0]["status"], "answered")
        self.assertEqual(len(interview["claims"]), 1)

    def test_sensitive_files_are_not_used_as_baseline_sources(self) -> None:
        self.write(".env", "TOKEN=secret")
        self.write("README.md", "# Safe")
        out = self.analyze("--static")
        claims = self.read(out, "observed_evidence.json")["claims"]
        refs = [source.get("reference", "") for item in claims for source in item["sources"]]
        self.assertNotIn(".env", refs)

    def test_gap_is_resolved_by_confirmed_artifact_evidence(self) -> None:
        self.write("README.md", "# Tool")
        out = self.analyze()
        payload = [{
            "category": "problem",
            "claim": "Project documentation states that the tool was created to validate imported records.",
            "status": "CONFIRMED",
            "sources": [{"type": "DOCUMENTATION", "reference": "README.md:Purpose"}],
        }]
        payload_path = self.write("observed.json", json.dumps(payload))
        self.run_tool("ingest", str(self.root), "--kind", "observed", "--input", str(payload_path))
        questions = self.read(out, "interview_evidence.json")["questions"]
        problem = next(q for q in questions if q["topic"] == "problem")
        self.assertEqual(problem["status"], "resolved_by_evidence")
        gap = self.read(out, "gap_analysis.json")
        self.assertEqual(next(a for a in gap["assessment"] if a["topic"] == "problem")["completeness_percent"], 100)

    def test_agent_observations_survive_refresh(self) -> None:
        self.write("README.md", "# Tool")
        out = self.analyze()
        payload = [{
            "category": "architecture", "claim": "The documented entry point is the main module.",
            "status": "CONFIRMED", "sources": [{"type": "DOCUMENTATION", "reference": "README.md"}]
        }]
        payload_path = self.write("observed.json", json.dumps(payload))
        self.run_tool("ingest", str(self.root), "--kind", "observed", "--input", str(payload_path))
        claim_id = next(c["id"] for c in self.read(out, "observed_evidence.json")["claims"] if c["category"] == "architecture")
        self.run_tool("analyze", str(self.root))
        refreshed_ids = {c["id"] for c in self.read(out, "observed_evidence.json")["claims"]}
        self.assertIn(claim_id, refreshed_ids)

    def test_user_estimate_is_not_promoted_or_published(self) -> None:
        self.write("main.py", "print('hello')")
        out = self.analyze()
        payload = {"claims": [{
            "category": "impact", "claim": "The workflow saved approximately two hours per run.",
            "status": "USER_ESTIMATE", "interview_question_id": "CTX-005", "public_safe": True
        }]}
        payload_path = self.write("estimate.json", json.dumps(payload))
        self.run_tool("ingest", str(self.root), "--kind", "interview", "--input", str(payload_path))
        estimate = next(c for c in self.read(out, "evidence.json")["claims"] if c["category"] == "impact")
        self.assertEqual(estimate["status"], "USER_ESTIMATE")
        self.assertNotIn(estimate["id"], (out / "public_safe_summary.md").read_text())
        self.assertEqual(self.run_tool("validate", str(self.root)).returncode, 0)

    def test_validator_rejects_static_runtime_claim(self) -> None:
        self.write("tests/test_one.py", "def test_one(): assert True")
        out = self.analyze()
        payload = [{
            "category": "testing", "claim": "The tests pass.", "status": "CONFIRMED",
            "sources": [{"type": "TEST", "reference": "tests/test_one.py"}]
        }]
        payload_path = self.write("bad-runtime.json", json.dumps(payload))
        self.run_tool("ingest", str(self.root), "--kind", "observed", "--input", str(payload_path))
        result = self.run_tool("validate", str(self.root), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("asserts runtime behavior", result.stdout)

    def test_external_symlink_is_not_traversed(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        (outside / "secret.py").write_text("PASSWORD='hidden'")
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        try:
            out = self.analyze("--static")
            files = {entry["path"] for entry in self.read(out, "inventory.json")["files"]}
            self.assertNotIn("linked/secret.py", files)
        finally:
            (self.root / "linked").unlink(missing_ok=True)
            (outside / "secret.py").unlink(missing_ok=True)
            outside.rmdir()


if __name__ == "__main__":
    unittest.main()
