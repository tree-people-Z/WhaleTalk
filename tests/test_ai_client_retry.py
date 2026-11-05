import unittest

from core.ai_client import AIClient, AIProvider


class _FlakyCompletions:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError('connection reset by peer')
        from types import SimpleNamespace
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='重试成功'))]
        )


class _AuthCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        raise PermissionError('invalid api key')


def _client(completions, retries=2):
    client = AIClient.__new__(AIClient)
    client.provider = AIProvider.DEEPSEEK
    client.model = 'test-model'
    client.max_retries = retries
    client.retry_backoff = 0.01
    from types import SimpleNamespace
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return client


class _ReasoningCompletions:
    def __init__(self):
        self.budgets = []

    async def create(self, **kwargs):
        from types import SimpleNamespace
        self.budgets.append(kwargs['max_tokens'])
        if len(self.budgets) == 1:
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    finish_reason='length',
                    message=SimpleNamespace(content=''),
                )],
                usage=SimpleNamespace(
                    completion_tokens_details=SimpleNamespace(
                        reasoning_tokens=kwargs['max_tokens']
                    )
                ),
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason='stop',
                message=SimpleNamespace(content='想清楚了'),
            )],
            usage=SimpleNamespace(
                completion_tokens_details=SimpleNamespace(reasoning_tokens=10)
            ),
        )


class AIClientRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_error_is_retried(self):
        completions = _FlakyCompletions(failures=2)
        result = await _client(completions).chat([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result, '重试成功')
        self.assertEqual(completions.calls, 3)

    async def test_retries_are_bounded(self):
        completions = _FlakyCompletions(failures=10)
        result = await _client(completions, retries=2).chat(
            [{'role': 'user', 'content': 'hi'}]
        )
        self.assertIsNone(result)
        self.assertEqual(completions.calls, 3)

    async def test_auth_error_is_not_retried(self):
        completions = _AuthCompletions()
        result = await _client(completions, retries=3).chat(
            [{'role': 'user', 'content': 'hi'}]
        )
        self.assertIsNone(result)
        self.assertEqual(completions.calls, 1)

    async def test_empty_reasoning_output_escalates_budget(self):
        completions = _ReasoningCompletions()
        client = _client(completions)
        client.max_output_tokens = 8000
        client.output_retries = 3
        result = await client.chat([{'role': 'user', 'content': 'hi'}], max_tokens=1000)
        self.assertEqual(result, '想清楚了')
        self.assertEqual(completions.budgets, [1000, 2024])

    async def test_escalated_budget_is_reused_by_next_call(self):
        completions = _ReasoningCompletions()
        client = _client(completions)
        client.max_output_tokens = 8000
        client.output_retries = 3
        await client.chat([{'role': 'user', 'content': 'hi'}], max_tokens=1000)
        await client.chat([{'role': 'user', 'content': 'hi'}], max_tokens=600)
        self.assertEqual(completions.budgets, [1000, 2024, 2024])

    def test_chat_sync_rejects_running_loop(self):
        client = _client(_FlakyCompletions(failures=0))

        async def call_sync_inside_loop():
            return client.chat_sync([{'role': 'user', 'content': 'hi'}])

        import asyncio
        with self.assertRaises(RuntimeError):
            asyncio.run(call_sync_inside_loop())


if __name__ == '__main__':
    unittest.main()
