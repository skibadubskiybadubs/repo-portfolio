from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "repo_portfolio.py"
README = Path(__file__).parents[1] / "README.md"
PYTHON = os.environ.get("REPO_PORTFOLIO_PYTHON", shutil.which("python3.12") or shutil.which("python3") or "python3")
CORE_KEYS = [
    "project", "problem", "users", "workflows", "technology", "architecture",
    "automation", "testing", "delivery", "maintenance", "ownership", "impact",
    "decisions", "career_signals", "unknowns", "extensions",
]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass


class OversizedImageHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(25 * 1024 * 1024 + 1))
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        pass


class RepoPortfolioBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.payloads = self.base / "payloads"
        self.root.mkdir()
        self.payloads.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def out(self) -> Path:
        return self.root / ".repo-portfolio"

    def write(self, relative: str, content: str = "") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def payload(self, name: str, value: object) -> Path:
        path = self.payloads / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run_tool(
        self, *args: str, check: bool = True, env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [PYTHON, str(SCRIPT), *args], capture_output=True, text=True, check=False,
            env={**os.environ, **(env or {})},
        )
        if check and result.returncode:
            self.fail(f"Command failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        return result

    def command(self, name: str, payload: object) -> subprocess.CompletedProcess[str]:
        return self.run_tool(name, str(self.root), "--input", str(self.payload(f"{name}.json", payload)))

    def analyze(self, *extra: str, env: dict[str, str] | None = None) -> None:
        self.run_tool("analyze", str(self.root), *extra, env=env)

    def read(self, relative: str) -> object:
        return json.loads((self.out / relative).read_text(encoding="utf-8"))

    def set_plan(self, domains: list[dict[str, object]], dimensions: list[dict[str, object]] | None = None) -> None:
        self.command("set-plan", {
            "project_profile": {"summary": "Codex interpretation of observed repository signals."},
            "domains": domains, "dimensions": dimensions or [],
        })

    def finish_domain(
        self, domain_id: str, state: str = "COMPLETE", reason: str | None = None,
        percent: int | None = None, claims: list[str] | None = None,
    ) -> None:
        update: dict[str, object] = {
            "domain_id": domain_id, "state": state,
            "inspected_references": ["src/main.py"], "evidence_claim_ids": claims or [],
            "findings_summary": "Codex inspected the planned evidence boundary.",
        }
        if reason:
            update["reason"] = reason
        if percent is not None:
            update["completion_percent"] = percent
        self.command("update-coverage", {"domains": [update]})

    def ingest_claim(self, **overrides: object) -> dict[str, object]:
        claim: dict[str, object] = {
            "category": "architecture", "claim": "The main module is the repository entry point.",
            "status": "CONFIRMED", "sources": [{"type": "SOURCE_CODE", "reference": "src/main.py:1"}],
            "dimensions": ["architecture.structure"], "public_safe": False,
        }
        claim.update(overrides)
        result = self.run_tool(
            "ingest", str(self.root), "--kind", "observed", "--input",
            str(self.payload("ingest.json", [claim])),
        )
        claim_id = json.loads(result.stdout)["ids"][0]
        return next(item for item in self.read("observed_evidence.json")["claims"] if item["id"] == claim_id)

    def complete_static_workflow(self) -> None:
        self.write("src/main.py", "def main():\n    return 0\n")
        self.analyze("--static")
        self.set_plan([{
            "id": "D-ARCH", "priority": "high", "reason": "The inventory contains an application entry point.",
            "focus": ["entry point", "module boundary"],
        }])
        claim = self.ingest_claim()
        self.finish_domain("D-ARCH", claims=[claim["id"]])
        self.command("set-gaps", {
            "dimensions": [{
                "id": "architecture.structure", "topic": "architecture", "relevant": True,
                "relevance_reason": "The repository contains application code.", "weight": 2,
                "resolution_channel": "ARTIFACT", "evidence_claim_ids": [claim["id"]],
            }],
            "gaps": [],
        })
        self.command("set-reconciled", {"claims": [claim]})
        project = {"schema_version": "1.1", **{key: [] for key in CORE_KEYS}}
        project["project"] = {"name": "Example"}
        project["semantic_summary"] = {
            "architecture": [{
                "statement": claim["claim"], "status": claim["status"],
                "dimensions": claim["dimensions"], "evidence_claim_ids": [claim["id"]],
            }]
        }
        self.command("write-outputs", {
            "project": project,
            "dossier": f"# Project Evidence Dossier\n\n{claim['id']}: {claim['claim']}",
            "public_safe_summary": "# Public-safe Summary\n\nNo claims were marked for publication.",
        })

    def test_incomplete_artifact_analysis_cannot_validate_as_complete(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze("--static")
        self.set_plan([{
            "id": "D-CODE", "priority": "high", "reason": "Source code is present.", "focus": ["entry points"],
        }])
        result = self.run_tool("validate", str(self.root), check=False)
        report = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["artifact_analysis_finished"])
        self.assertFalse(report["workflow_complete"])
        self.assertTrue(any("PENDING" in error for error in report["errors"]))

    def test_observed_claim_without_status_is_rejected_without_persistence(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze("--static")
        result = self.run_tool(
            "ingest", str(self.root), "--kind", "observed", "--input",
            str(self.payload("missing-observed-status.json", [{
                "category": "architecture", "claim": "The main module is an entry point.",
                "sources": [{"type": "SOURCE_CODE", "reference": "src/main.py:1"}],
            }])), check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Observed claim requires an explicit non-empty status", result.stderr)
        self.assertEqual(self.read("observed_evidence.json")["claims"], [])

    def test_canonical_claim_without_status_is_rejected_without_persistence(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze("--static")
        self.set_plan([{
            "id": "D-ARCH", "priority": "high", "reason": "Source code exists.", "focus": ["entry point"],
        }])
        self.finish_domain("D-ARCH")
        result = self.command_result("set-reconciled", {"claims": [{
            "category": "architecture", "claim": "The main module is an entry point.",
            "sources": [{"type": "SOURCE_CODE", "reference": "src/main.py:1"}],
        }]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Canonical claim requires an explicit non-empty status", result.stderr)
        self.assertEqual(self.read("evidence.json")["claims"], [])
        self.assertFalse(self.read("session.json")["reconciliation_ready"])

    def test_explicit_confirmed_claim_still_completes_normally(self) -> None:
        self.complete_static_workflow()
        claim = self.read("evidence.json")["claims"][0]
        self.assertEqual(claim["status"], "CONFIRMED")
        self.assertTrue(json.loads(self.run_tool("validate", str(self.root)).stdout)["valid"])

    def test_interview_claim_default_retains_question_provenance(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze()
        result = self.run_tool(
            "ingest", str(self.root), "--kind", "interview", "--input",
            str(self.payload("interview-default.json", [{
                "category": "impact", "claim": "The developer reports that the tool reduced rework.",
                "interview_question_id": "Q-IMPACT-001",
            }])),
        )
        self.assertEqual(result.returncode, 0)
        claim = self.read("interview_evidence.json")["claims"][0]
        self.assertEqual(claim["status"], "USER_CONFIRMED")
        self.assertEqual(claim["sources"], [{
            "type": "USER_ATTESTATION", "reference": "Q-IMPACT-001",
            "interview_question_id": "Q-IMPACT-001",
        }])

    def test_artifact_source_without_reference_is_rejected(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze("--static")
        for index, source in enumerate(({"type": "SOURCE_CODE"}, {"type": "DOCUMENTATION", "reference": "   "})):
            result = self.run_tool(
                "ingest", str(self.root), "--kind", "observed", "--input",
                str(self.payload(f"missing-reference-{index}.json", [{
                    "category": "architecture", "claim": "An artifact-backed claim.",
                    "status": "CONFIRMED", "sources": [source],
                }])), check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires a non-empty reference", result.stderr)
        self.assertEqual(self.read("observed_evidence.json")["claims"], [])

    def test_valid_artifact_reference_is_accepted(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze("--static")
        claim = self.ingest_claim()
        self.assertEqual(claim["sources"][0]["reference"], "src/main.py:1")

    def test_validator_rejects_persisted_missing_status_and_reference(self) -> None:
        self.complete_static_workflow()
        observed = self.read("observed_evidence.json")
        observed["claims"][0].pop("status")
        observed["claims"][0]["sources"][0].pop("reference")
        (self.out / "observed_evidence.json").write_text(json.dumps(observed), encoding="utf-8")
        result = self.run_tool("validate", str(self.root), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("observed claim is missing an explicit status", result.stdout)
        self.assertIn("artifact source SOURCE_CODE requires a non-empty reference", result.stdout)

    def test_partial_and_blocked_are_honest_terminal_states(self) -> None:
        self.write("src/main.py", "print('historical')")
        self.analyze("--static")
        self.set_plan([
            {"id": "D-A", "priority": "high", "reason": "Code exists.", "focus": ["logic"]},
            {"id": "D-B", "priority": "medium", "reason": "History is incomplete.", "focus": ["evolution"]},
            {"id": "D-C", "priority": "low", "reason": "Deployment may be external.", "focus": ["delivery"]},
        ])
        updates = {"domains": [
            {"domain_id": "D-A", "state": "COMPLETE", "inspected_references": ["src/main.py"]},
            {"domain_id": "D-B", "state": "PARTIAL", "reason": "Only the final snapshot survives.",
             "completion_percent": 50, "inspected_references": ["src/main.py"]},
            {"domain_id": "D-C", "state": "BLOCKED", "reason": "The historical release system is unavailable.",
             "inspected_references": []},
        ]}
        self.command("update-coverage", updates)
        status = json.loads(self.run_tool("finalize", str(self.root)).stdout)
        self.assertTrue(status["artifact_analysis_finished"])
        self.assertAlmostEqual(status["evidence_completeness"], 66.7)
        self.assertFalse(status["workflow_complete"])

    def test_not_applicable_requires_evidence_and_is_terminal(self) -> None:
        self.write("src/main.py", "print('cli')")
        self.analyze("--static")
        self.set_plan([{
            "id": "D-UI", "priority": "medium", "reason": "Confirm whether the CLI has a graphical UI.", "focus": ["UI boundary"],
        }])
        bad = self.command_result("update-coverage", {
            "domains": [{"domain_id": "D-UI", "state": "NOT_APPLICABLE", "reason": "No UI."}],
        })
        self.assertNotEqual(bad.returncode, 0)
        self.command("update-coverage", {"domains": [{
            "domain_id": "D-UI", "state": "NOT_APPLICABLE", "reason": "The only entry point is a CLI.",
            "inspected_references": ["src/main.py"],
        }]})
        self.assertTrue(self.read("session.json")["artifact_analysis_finished"])

    def command_result(self, name: str, payload: object) -> subprocess.CompletedProcess[str]:
        return self.run_tool(
            name, str(self.root), "--input", str(self.payload(f"bad-{name}.json", payload)), check=False,
        )

    def test_different_project_types_accept_different_codex_plans(self) -> None:
        self.write("package.json", '{"dependencies":{"react":"1"}}')
        self.write("src/App.tsx", "export const App = () => null")
        self.analyze("--static")
        self.set_plan([
            {"id": "D-WEB", "priority": "high", "reason": "React appears in package metadata.", "focus": ["UI states"]},
            {"id": "D-DELIVERY", "priority": "medium", "reason": "Delivery context is not yet known.", "focus": ["deployment"]},
        ])
        web_ids = {item["id"] for item in self.read("analysis_plan.json")["domains"]}

        other = self.base / "cli"
        other.mkdir()
        (other / "main.go").write_text("package main", encoding="utf-8")
        self.run_tool("analyze", str(other), "--static")
        plan_path = self.payload("cli-plan.json", {"domains": [{
            "id": "D-CLI", "priority": "high", "reason": "A Go command entry point is present.", "focus": ["commands", "flags"],
        }]})
        self.run_tool("set-plan", str(other), "--input", str(plan_path))
        cli_ids = {item["id"] for item in json.loads((other / ".repo-portfolio/analysis_plan.json").read_text())["domains"]}
        self.assertEqual(web_ids, {"D-WEB", "D-DELIVERY"})
        self.assertEqual(cli_ids, {"D-CLI"})

    def test_discovery_does_not_generate_a_default_questionnaire(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze()
        interview = self.read("interview_evidence.json")
        self.assertEqual(interview["questions"], [])
        self.assertEqual(self.read("analysis_plan.json")["domains"], [])

    def test_question_is_grounded_in_actual_project_evidence(self) -> None:
        self.write("src/transform.py", "def transform(records): return records")
        self.analyze()
        self.set_plan([{
            "id": "D-FLOW", "priority": "high", "reason": "A record transform is implemented.", "focus": ["workflow boundary"],
        }])
        claim = self.ingest_claim(
            category="workflow", claim="The transform function accepts a collection of records.",
            sources=[{"type": "SOURCE_CODE", "reference": "src/transform.py:1"}],
            dimensions=["workflows.prior_manual_steps"], status="STRONG_INFERENCE",
        )
        self.finish_domain("D-FLOW", claims=[claim["id"]])
        self.command("set-gaps", {
            "dimensions": [{
                "id": "workflows.prior_manual_steps", "topic": "workflows", "relevant": True, "weight": 3,
                "relevance_reason": "The transform implies an input workflow but artifacts cannot establish prior practice.",
                "resolution_channel": "INTERVIEW", "evidence_claim_ids": [claim["id"]],
            }],
            "gaps": [{
                "id": "GAP-FLOW", "topic": "workflows", "dimension_id": "workflows.prior_manual_steps",
                "importance": 90, "confirm_inference": True, "basis_claim_ids": [claim["id"]],
                "rationale": "Confirm the pre-tool workflow rather than guessing from code.",
            }],
        })
        self.command("queue-question", {
            "gap_id": "GAP-FLOW",
            "question": "The repository suggests transform(records) replaced or supported a record-processing step. What did people do before it?",
            "tentative_interpretation": "The collection-oriented transform may have consolidated a manual record workflow.",
            "rationale": "Only the developer can establish the historical workflow.",
        })
        question = json.loads(self.run_tool("next-question", str(self.root)).stdout)["question"]
        self.assertIn("transform(records)", question["question"])
        self.assertEqual(question["basis_claim_ids"], [claim["id"]])
        self.assertIn("manual record workflow", question["tentative_interpretation"])

    def test_one_confirmed_claim_does_not_complete_a_broad_topic(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze("--static")
        self.set_plan([{"id": "D-USERS", "priority": "high", "reason": "Usage context is unknown.", "focus": ["users"]}])
        claim = self.ingest_claim(
            category="users", claim="Documentation names analysts as users.",
            sources=[{"type": "DOCUMENTATION", "reference": "README.md:Users"}], dimensions=["users.roles"],
        )
        self.finish_domain("D-USERS", claims=[claim["id"]])
        self.command("set-gaps", {"dimensions": [
            {"id": "users.roles", "topic": "users", "relevant": True, "weight": 1,
             "relevance_reason": "A role is documented.", "resolution_channel": "ARTIFACT", "evidence_claim_ids": [claim["id"]]},
            {"id": "users.actual_usage", "topic": "users", "relevant": True, "weight": 1,
             "relevance_reason": "Actual use matters for this tool.", "resolution_channel": "INTERVIEW", "evidence_claim_ids": []},
        ], "gaps": [{
            "id": "GAP-USAGE", "topic": "users", "dimension_id": "users.actual_usage", "importance": 80,
            "basis_claim_ids": [claim["id"]], "rationale": "A named role does not establish real adoption.",
        }]})
        topics = {item["topic"]: item for item in self.read("gap_analysis.json")["topics"]}
        self.assertEqual(topics["users"]["completeness_percent"], 50.0)

    def test_question_order_uses_gap_score_before_question_id(self) -> None:
        self.write("src/main.py", "print('hello')")
        self.analyze()
        self.set_plan([{"id": "D-CONTEXT", "priority": "high", "reason": "Context is absent.", "focus": ["impact", "ownership"]}])
        self.finish_domain("D-CONTEXT")
        dimensions = [
            {"id": "impact.outcome", "topic": "impact", "relevant": True, "weight": 1,
             "relevance_reason": "Outcome matters.", "resolution_channel": "INTERVIEW", "evidence_claim_ids": []},
            {"id": "ownership.scope", "topic": "ownership", "relevant": True, "weight": 1,
             "relevance_reason": "Scope matters.", "resolution_channel": "INTERVIEW", "evidence_claim_ids": []},
        ]
        self.command("set-gaps", {"dimensions": dimensions, "gaps": [
            {"id": "GAP-LOW", "topic": "ownership", "dimension_id": "ownership.scope", "importance": 20,
             "basis_references": ["project_profile.json"], "rationale": "Ownership scope is optional context."},
            {"id": "GAP-HIGH", "topic": "impact", "dimension_id": "impact.outcome", "importance": 95,
             "basis_references": ["project_profile.json"], "rationale": "The outcome is a high-value unknown."},
        ]})
        self.command("queue-question", {"id": "Q-001", "gap_id": "GAP-LOW", "question": "What was your scope?", "rationale": "Resolve scope."})
        self.command("queue-question", {"id": "Q-999", "gap_id": "GAP-HIGH", "question": "What outcome did it create?", "rationale": "Resolve outcome."})
        selected = json.loads(self.run_tool("next-question", str(self.root)).stdout)["question"]
        self.assertEqual(selected["id"], "Q-999")
        self.assertGreater(selected["gap_score"], 90)

    def test_repository_change_stales_technical_evidence_but_preserves_user_context(self) -> None:
        self.write("src/main.py", "print('one')")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "src/main.py"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "initial"],
            cwd=self.root, check=True,
        )
        self.analyze()
        self.set_plan([{"id": "D-CODE", "priority": "high", "reason": "Code exists.", "focus": ["behavior"]}])
        self.ingest_claim()
        interview_payload = [{
            "category": "impact", "claim": "The developer reports that the project reduced rework.",
            "status": "USER_CONFIRMED", "dimensions": ["impact.qualitative_outcome"],
        }]
        self.run_tool("ingest", str(self.root), "--kind", "interview", "--input", str(self.payload("user.json", interview_payload)))
        self.write("src/main.py", "print('two')")
        self.analyze()
        self.assertEqual(self.read("session.json")["compatibility"], "CHANGED")
        self.assertTrue(all(item["currency"] == "STALE" for item in self.read("observed_evidence.json")["claims"]))
        self.assertTrue(all(item["currency"] == "REVIEW_REQUIRED" for item in self.read("interview_evidence.json")["claims"]))
        self.assertEqual(self.read("analysis_plan.json")["domains"], [])

    def test_exact_resume_retains_pending_question_and_external_media(self) -> None:
        self.write("src/main.py", "print('hello')")
        external_image = self.base / "workflow.png"
        external_image.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.analyze("--media", str(external_image))
        self.set_plan([{"id": "D-CONTEXT", "priority": "high", "reason": "Workflow context is unknown.", "focus": ["usage"]}])
        self.finish_domain("D-CONTEXT")
        self.command("set-gaps", {"dimensions": [{
            "id": "users.actual_usage", "topic": "users", "relevant": True, "weight": 2,
            "relevance_reason": "The project has an interface but usage is not documented.",
            "resolution_channel": "INTERVIEW", "evidence_claim_ids": [],
        }], "gaps": [{
            "id": "GAP-USAGE", "topic": "users", "dimension_id": "users.actual_usage", "importance": 90,
            "basis_references": ["media/media_index.json#MEDIA-001"], "rationale": "A screenshot cannot establish actual adoption.",
        }]})
        self.command("queue-question", {
            "gap_id": "GAP-USAGE", "question": "Who actually used the workflow shown in the supplied image?",
            "rationale": "Only testimony can establish actual use.",
        })
        first = json.loads(self.run_tool("next-question", str(self.root)).stdout)["question"]
        original_media_source = self.read("media/media_index.json")["items"][0]["source"]
        self.analyze()
        resumed = json.loads(self.run_tool("next-question", str(self.root)).stdout)
        self.assertEqual(self.read("session.json")["compatibility"], "EXACT")
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["question"]["id"], first["id"])
        self.assertEqual(self.read("media/media_index.json")["items"][0]["source"], original_media_source)

    def test_same_size_filesystem_change_is_detected(self) -> None:
        self.write("main.txt", "aaaa")
        self.analyze("--static")
        self.write("main.txt", "bbbb")
        self.analyze("--static")
        self.assertEqual(self.read("session.json")["compatibility"], "CHANGED")

    def make_video(self, path: Path) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg is unavailable")
        result = subprocess.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=128x72:rate=2", "-t", "4", "-c:v", "mpeg4", str(path),
        ], capture_output=True, text=True)
        if result.returncode:
            self.skipTest(f"ffmpeg cannot create the test video: {result.stderr}")

    def test_video_frames_retain_source_and_timestamps(self) -> None:
        self.write("src/main.py", "print('media')")
        video = self.base / "demo.mp4"
        self.make_video(video)
        self.analyze("--static", "--media", str(video))
        item = next(value for value in self.read("media/media_index.json")["items"] if value["type"] == "video")
        self.assertTrue(item["frames"])
        self.assertTrue(all(frame["source"] == item["source"] for frame in item["frames"]))
        self.assertTrue(all(isinstance(frame["timestamp_seconds"], (int, float)) for frame in item["frames"]))

    def test_direct_remote_image_keeps_url_as_canonical_provenance(self) -> None:
        served = self.base / "served"
        served.mkdir()
        (served / "screen.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"safe-test-data")
        handler = functools.partial(QuietHandler, directory=str(served))
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        except PermissionError:
            self.skipTest("the test sandbox does not permit loopback sockets")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/screen.png"
            self.write("src/main.py", "print('media')")
            self.analyze("--static", "--media", url, env={"REPO_PORTFOLIO_ALLOW_PRIVATE_MEDIA": "1"})
            item = next(value for value in self.read("media/media_index.json")["items"] if value["type"] == "image")
            self.assertEqual(item["source"], url)
            self.assertEqual(item["original_url"], url)
            self.assertTrue(item["cached_path"].startswith("media/cache/"))
            self.assertNotEqual(item["source"], item["cached_path"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_remote_html_is_rejected_without_crawling(self) -> None:
        served = self.base / "served"
        served.mkdir()
        (served / "page.html").write_text("<a href='screen.png'>do not follow</a>", encoding="utf-8")
        (served / "screen.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(served)))
        except PermissionError:
            self.skipTest("the test sandbox does not permit loopback sockets")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/page.html"
            self.analyze("--static", "--media", url, env={"REPO_PORTFOLIO_ALLOW_PRIVATE_MEDIA": "1"})
            media = self.read("media/media_index.json")
            self.assertEqual(media["items"][0]["source"], url)
            self.assertEqual(media["items"][0]["type"], "unavailable")
            self.assertIn("does not crawl pages", " ".join(media["warnings"]))
            self.assertEqual(len(media["items"]), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_direct_remote_video_uses_the_same_timestamped_frame_pipeline(self) -> None:
        served = self.base / "served-video"
        served.mkdir()
        self.make_video(served / "demo.mp4")
        try:
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(served)),
            )
        except PermissionError:
            self.skipTest("the test sandbox does not permit loopback sockets")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/demo.mp4"
            self.analyze("--static", "--media", url, env={"REPO_PORTFOLIO_ALLOW_PRIVATE_MEDIA": "1"})
            item = self.read("media/media_index.json")["items"][0]
            self.assertEqual(item["source"], url)
            self.assertTrue(item["cached_path"].startswith("media/cache/"))
            self.assertTrue(item["frames"])
            self.assertTrue(all(frame["source"] == url and frame["timestamp_seconds"] is not None for frame in item["frames"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_remote_media_size_limit_is_enforced_before_download(self) -> None:
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OversizedImageHandler)
        except PermissionError:
            self.skipTest("the test sandbox does not permit loopback sockets")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/large.png"
            self.analyze("--static", "--media", url, env={"REPO_PORTFOLIO_ALLOW_PRIVATE_MEDIA": "1"})
            item = self.read("media/media_index.json")["items"][0]
            self.assertEqual(item["type"], "unavailable")
            self.assertIn("exceeds the 25 MiB limit", item["warnings"][0])
            cache_files = list((self.out / "media/cache").rglob("media.*"))
            self.assertEqual(cache_files, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_youtube_unavailability_is_graceful_and_keeps_original_url(self) -> None:
        self.write("src/main.py", "print('media')")
        empty_bin = self.base / "empty-bin"
        empty_bin.mkdir()
        url = "https://www.youtube.com/watch?v=unavailable-test"
        self.analyze("--static", "--media", url, env={"PATH": str(empty_bin)})
        item = self.read("media/media_index.json")["items"][0]
        self.assertEqual(item["source"], url)
        self.assertEqual(item["original_url"], url)
        self.assertEqual(item["type"], "unavailable")
        self.assertIn("yt-dlp is unavailable", item["warnings"][0])

    def test_youtube_metadata_captions_frames_and_provenance_are_retained(self) -> None:
        video = self.base / "youtube-source.mp4"
        self.make_video(video)
        fake_bin = self.base / "fake-bin"
        fake_bin.mkdir()
        fake = fake_bin / "yt-dlp"
        fake.write_text(
            "#!/usr/bin/python3\n"
            "import json, os, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['FAKE_YTDLP_LOG'], 'a') as log: log.write(json.dumps(args) + '\\n')\n"
            "if '--dump-single-json' in args:\n"
            " print(json.dumps({'title':'Tool demo','duration':4.0,'webpage_url':args[-1],"
            "'subtitles':{'en':[{'ext':'vtt'}]}})); raise SystemExit(0)\n"
            "cache = args[args.index('--paths') + 1]\n"
            "shutil.copyfile(os.environ['FAKE_VIDEO'], os.path.join(cache, 'media.mp4'))\n"
            "open(os.path.join(cache, 'media.en.vtt'), 'w').write("
            "'WEBVTT\\n\\n00:00:01.000 --> 00:00:02.000\\nVisible workflow\\n')\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        log = self.base / "yt-dlp.log"
        url = "https://www.youtube.com/watch?v=abc123"
        self.write("src/main.py", "print('media')")
        self.analyze("--static", "--media", url, env={
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_VIDEO": str(video), "FAKE_YTDLP_LOG": str(log),
        })
        item = self.read("media/media_index.json")["items"][0]
        self.assertEqual(item["source"], url)
        self.assertEqual(item["original_url"], url)
        self.assertEqual(item["title"], "Tool demo")
        self.assertEqual(item["duration"], 4.0)
        self.assertEqual(item["caption_kind"], "human")
        self.assertTrue(item["transcript_path"].startswith("media/cache/"))
        self.assertTrue(item["frames"])
        self.assertTrue(all(frame["source"] == url for frame in item["frames"]))
        invocations = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertTrue(all("--no-config" in args and "--no-playlist" in args for args in invocations))

    def test_normalized_project_json_is_traceable_to_evidence(self) -> None:
        self.complete_static_workflow()
        result = self.run_tool("validate", str(self.root))
        report = json.loads(result.stdout)
        self.assertTrue(report["artifact_analysis_finished"])
        self.assertTrue(report["workflow_complete"])
        self.assertTrue(report["valid"])

        project = self.read("project.json")
        project["semantic_summary"]["impact"] = [{
            "statement": "An invented impact claim.", "status": "CONFIRMED",
            "dimensions": ["impact.outcome"], "evidence_claim_ids": ["IMPACT-999"],
        }]
        (self.out / "project.json").write_text(json.dumps(project), encoding="utf-8")
        invalid = self.run_tool("validate", str(self.root), check=False)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("not traceable", invalid.stdout)

    def test_contradictory_testimony_retains_an_explicit_relationship(self) -> None:
        self.write("tests/test_feature.py", "def test_feature(): assert True")
        self.analyze()
        self.set_plan([{"id": "D-TEST", "priority": "high", "reason": "Tests exist.", "focus": ["test strategy"]}])
        observed = self.ingest_claim(
            category="testing", claim="The repository contains an automated feature test.",
            sources=[{"type": "TEST", "reference": "tests/test_feature.py:1"}], dimensions=["testing.automation"],
        )
        payload = [{
            "category": "testing", "claim": "The developer remembers that the project had no automated tests.",
            "status": "USER_CONFIRMED", "interview_question_id": "Q-TESTS",
            "contradicts": [observed["id"]], "dimensions": ["testing.automation"],
        }]
        self.run_tool(
            "ingest", str(self.root), "--kind", "interview", "--input",
            str(self.payload("contradiction.json", payload)),
        )
        testimony = self.read("interview_evidence.json")["claims"][0]
        self.assertEqual(testimony["contradicts"], [observed["id"]])
        self.assertEqual(testimony["sources"][0]["type"], "USER_ATTESTATION")

    def test_inventory_does_not_follow_external_symlinks_and_marks_sensitive_names(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("PASSWORD='hidden'", encoding="utf-8")
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        self.write(".env", "TOKEN=secret")
        self.analyze("--static")
        files = {item["path"]: item for item in self.read("inventory.json")["files"]}
        self.assertNotIn("linked/secret.py", files)
        self.assertTrue(files[".env"]["sensitive_name"])
        serialized = json.dumps(self.read("inventory.json"))
        self.assertNotIn("TOKEN=secret", serialized)

    def test_validator_rejects_runtime_success_claimed_from_static_artifacts(self) -> None:
        self.complete_static_workflow()
        for name in ("observed_evidence.json", "evidence.json"):
            store = self.read(name)
            store["claims"][0]["category"] = "testing"
            store["claims"][0]["claim"] = "The tests pass."
            store["claims"][0]["sources"] = [{"type": "TEST", "reference": "tests/test_main.py"}]
            (self.out / name).write_text(json.dumps(store), encoding="utf-8")
        result = self.run_tool("validate", str(self.root), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("asserts runtime behavior from static evidence", result.stdout)

    def test_doctor_accepts_supported_interpreter_range(self) -> None:
        report = json.loads(self.run_tool("doctor").stdout)
        self.assertEqual(report["minimum_python"], "3.9")
        self.assertTrue(report["python_supported"])

    def test_readme_is_concise_and_usage_first(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# repo-portfolio\n\n## HOW TO USE IT"))
        self.assertLess(text.index("## HOW TO USE IT"), text.index("## What it is"))
        self.assertLessEqual(len(text.splitlines()), 30)


if __name__ == "__main__":
    unittest.main()
