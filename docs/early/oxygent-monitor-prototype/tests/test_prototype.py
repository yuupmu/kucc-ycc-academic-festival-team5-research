import asyncio
import contextlib
import io
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import ask_human, build_mas, impact, run, validate_policy


async def never_ask():
    raise AssertionError("문서에 있는 정책이나 구현 오류를 인간에게 다시 물었습니다.")


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 실제 OxyGent 실행 중 네트워크 연결이 발생하면 테스트를 실패시킨다.
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(socket.socket, "connect",
                                             side_effect=AssertionError("네트워크 호출 금지")))
        self.stack.enter_context(patch.object(socket, "getaddrinfo",
                                             side_effect=AssertionError("DNS 호출 금지")))
        self.mas = build_mas()
        await self.mas.__aenter__()

    async def asyncTearDown(self):
        try:
            await self.mas.__aexit__(None, None, None)
        finally:
            self.stack.close()

    async def test_missing_policy_pauses_and_uses_human_answer(self):
        async def answer():
            return {"hours": 48, "inclusive": False}

        result = await run(self.mas, "missing", answer)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["human_questions"], 1)
        self.assertIsNone(result["steps"][0]["snapshot"]["implementation"])
        self.assertEqual(result["steps"][0]["reviews"][0]["decision"], "ask_human")
        self.assertEqual(result["implementation"]["hours"], 48)
        self.assertFalse(result["implementation"]["inclusive"])
        self.assertEqual(result["metrics"]["checks_passed"], 11)
        self.assertEqual(result["steps"][-1]["snapshot"]["source"], "human")

    async def test_documented_policy_never_asks(self):
        result = await run(self.mas, "documented", never_ask)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["metrics"], {
            "checks_passed": 11, "checks_total": 11, "worker_rounds": 1,
            "human_questions": 0, "auto_repairs": 0,
        })

    async def test_boundary_bug_repaired_without_human(self):
        result = await run(self.mas, "bug", never_ask)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["repairs"], 1)
        first_tests = result["steps"][0]["reviews"][1]["tests"]
        failures = [t["name"] for t in first_tests if not t["passed"]]
        self.assertEqual(failures, ["정확한 마감 시각"])
        self.assertTrue(result["implementation"]["inclusive"])
        self.assertEqual(result["metrics"]["checks_passed"], 11)

    async def test_concurrent_runs_do_not_share_human_answers(self):
        async def first():
            await asyncio.sleep(0)
            return {"hours": 12, "inclusive": True}

        async def second():
            return {"hours": 72, "inclusive": False}

        results = await asyncio.gather(run(self.mas, "missing", first),
                                       run(self.mas, "missing", second))
        self.assertEqual([r["implementation"]["hours"] for r in results], [12, 72])
        self.assertTrue(all(r["status"] == "completed" for r in results))
        self.assertNotEqual(results[0]["steps"][0]["trace_id"],
                            results[1]["steps"][0]["trace_id"])

    async def test_invalid_feedback_is_not_accepted(self):
        async def answer():
            return {"hours": -1, "inclusive": True}

        with self.assertRaises(ValueError):
            await run(self.mas, "missing", answer)

    async def test_failed_monitor_does_not_produce_success(self):
        async def fail(request):
            raise RuntimeError("감시 실패 주입")

        self.mas.oxy_name_to_oxy["impact"].func_workflow = fail
        with self.assertRaisesRegex(RuntimeError, "작업 실행 실패"):
            await run(self.mas, "documented", never_ask)


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_feedback_and_notification_regression_are_detected(self):
        request = SimpleNamespace(arguments={"snapshot": {
            "policy": {"hours": 48, "inclusive": False}, "version": 2,
            "implementation": {"hours": 24, "inclusive": True,
                               "version": 1, "suppress_cancelled": False},
        }})
        review = await impact(request)
        self.assertEqual(review["decision"], "revise")
        self.assertEqual([t["name"] for t in review["tests"] if not t["passed"]],
                         ["정책 버전 반영", "정책 내용 반영", "취소된 예약의 알림 차단"])

    async def test_cli_retries_invalid_input(self):
        with patch("builtins.input", side_effect=["abc", "24", "maybe", "48", "n"]):
            with contextlib.redirect_stdout(io.StringIO()):
                policy = await ask_human()
        self.assertEqual(policy, {"hours": 48, "inclusive": False})

    def test_policy_rejects_wrong_types_and_ranges(self):
        for policy in [None, {}, {"hours": True, "inclusive": True},
                       {"hours": 1.5, "inclusive": True},
                       {"hours": 8761, "inclusive": True},
                       {"hours": 24, "inclusive": "yes"}]:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                validate_policy(policy)


if __name__ == "__main__":
    unittest.main()
