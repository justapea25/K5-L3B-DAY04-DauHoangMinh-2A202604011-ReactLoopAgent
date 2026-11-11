"""Tests offline cho phần bonus: retry 429 có giới hạn, Retry-After, context gọn, phân trang, prompt."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from agent import run_agent, SYSTEM_PROMPT, EXTRA_RULES
from bonus.tools import BonusTools
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final


def vercel(call_id):
    return tool_call(call_id, 'get_vercel_status', '{}')


def tool_events(result, name):
    return [t for t in result['trace'] if t['event'] == 'tool' and t['name'] == name]


class RetryTests(unittest.TestCase):
    def test_429_once_model_retries_and_is_told_it_may(self):
        fake = FakeProvider([vercel('a'), vercel('b'), final('Vercel ổn https://www.vercel-status.com')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_once'), max_steps=5)
        first = json.loads(fake.histories[1][-1]['content'])
        self.assertEqual(first['error'], 'RATE_LIMITED')
        self.assertIn('GỌI LẠI', first['note'])
        self.assertIn('KHÔNG phải outage', first['note'])
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), 2)

    def test_429_always_stops_after_three_real_calls(self):
        fake = FakeProvider([vercel(str(i)) for i in range(5)] + [final('Vercel chưa biết')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_always'), max_steps=8)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), 3)  # max_calls của B4
        self.assertEqual(sum(t['event'] == 'retry_blocked' for t in result['trace']), 2)
        third = json.loads(fake.histories[3][-1]['content'])
        self.assertIn('hết lượt retry', third['note'])
        blocked = json.loads(fake.histories[4][-1]['content'])
        self.assertEqual(blocked['error'], 'RETRY_BUDGET_EXHAUSTED')

    def test_pending_retry_gate_when_model_gives_up_early(self):
        fake = FakeProvider([vercel('a'), final('Vercel lỗi, đã thử lại'), vercel('b'), final('Vercel ổn')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_once'), max_steps=6)
        gate = [t for t in result['trace'] if t['event'] == 'validation_pending_retry']
        self.assertEqual(gate[0]['tools'], ['get_vercel_status'])
        self.assertIn('Không được nói đã thử lại', fake.histories[2][-1]['content'])
        self.assertEqual([t['ok'] for t in tool_events(result, 'get_vercel_status')], [False, True])

    def test_pending_retry_gate_nudges_only_once(self):
        fake = FakeProvider([vercel('a'), final('A'), final('B chưa biết Vercel')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_always'), max_steps=6)
        self.assertEqual(result['answer'], 'B chưa biết Vercel')

    def test_budget_is_per_tool_and_provider(self):
        fake = FakeProvider([vercel('a'), vercel('b'), vercel('c'),
                             tool_call('d', 'get_github_status', '{}'), final('GitHub ổn')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_always'), max_steps=8)
        self.assertTrue(tool_events(result, 'get_github_status')[0]['ok'])


class _Limited:
    """Tool giả: luôn 429 kèm Retry-After cho trước."""
    def __init__(self, retry_after):
        self.retry_after = retry_after
    def execute(self, name, args):
        return {'ok': False, 'error': 'RATE_LIMITED', 'http_status': 429, 'retry_after': self.retry_after}


class RetryAfterTests(unittest.TestCase):
    def test_short_retry_after_is_honored(self):
        fake = FakeProvider([vercel('a'), final('chưa biết'), final('vẫn chưa biết')])
        with patch.object(agent.time, 'sleep') as sleep:
            result = run_agent('x', fake, _Limited('2'))
        sleep.assert_called_once_with(2.0)
        self.assertEqual(tool_events(result, 'get_vercel_status')[0]['waited_s'], 2.0)
        self.assertIn('Đã chờ 2s', json.loads(fake.histories[1][-1]['content'])['note'])

    def test_long_retry_after_stops_retrying_without_waiting(self):
        fake = FakeProvider([vercel('a'), vercel('b'), final('chưa biết')])
        with patch.object(agent.time, 'sleep') as sleep:
            result = run_agent('x', fake, _Limited('120'))
        sleep.assert_not_called()
        self.assertIn('vượt giới hạn chờ', json.loads(fake.histories[1][-1]['content'])['note'])
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), 1)  # lần 2 bị chặn
        self.assertTrue(any(t['event'] == 'retry_blocked' for t in result['trace']))


class ContextTests(unittest.TestCase):
    def test_long_noise_list_is_trimmed_for_model_only(self):
        fake = FakeProvider([vercel('a'), final('ok https://www.vercel-status.com')])
        result = run_agent('x', fake, BonusTools(scenario='noisy'))
        sent = json.loads(fake.histories[1][-1]['content'])
        self.assertEqual(len(sent['distractors']), 20)
        self.assertIn('140/160', sent['distractors_omitted'])
        self.assertEqual(len(tool_events(result, 'get_vercel_status')[0]['result']['distractors']), 160)

    def test_main_eval_noise_of_40_items_is_untouched(self):
        self.assertEqual(len(agent._compact({'distractors': list(range(40))})['distractors']), 40)

    def test_pagination_note_when_pages_remain(self):
        args = '{"provider":"vercel","incident_id":"sps6n39gm4sg"}'
        url = BonusTools().get_incident_details('vercel', 'sps6n39gm4sg')['url']
        fake = FakeProvider([tool_call('a', 'get_incident_details', args), final('Một phần ' + url)])
        run_agent('x', fake, BonusTools())
        sent = json.loads(fake.histories[1][-1]['content'])
        self.assertIn('chưa xem hết timeline', sent['pagination_note'])


class LinkProviderTests(unittest.TestCase):
    def test_link_provider_is_taken_from_domain(self):
        result = {'ok': True, 'provider': 'vercel', 'id': 'v1', 'updates': [
            {'body': 'See https://www.githubstatus.com/incidents/abcdefgh1234 for GitHub.'},
            {'body': 'Also /incidents/zzzzzzzz9999'}]}
        found = agent._linked_incidents('get_incident_details', {}, result, ['github', 'vercel', 'npm'])
        self.assertEqual(found, [('github', 'abcdefgh1234'), ('vercel', 'zzzzzzzz9999')])

    def test_main_github_links_still_resolve_to_github(self):
        r = StatusTools().get_incident_details('github', 'h02n9572mx9y')
        self.assertEqual(agent._linked_incidents('get_incident_details', {}, r, ['github', 'cloudflare']),
                         [('github', 'xr3myzj7ms51')])


class PromptTests(unittest.TestCase):
    def test_bonus_prompt_keeps_tools_prompt_and_adds_rules(self):
        fake = FakeProvider([final('x')])
        run_agent('x', fake, BonusTools())
        system = fake.histories[0][0]['content']
        self.assertTrue(system.startswith(BonusTools.system_prompt))
        self.assertIn(EXTRA_RULES, system)

    def test_main_prompt_is_unchanged(self):
        fake = FakeProvider([final('x')])
        run_agent('x', fake, StatusTools())
        self.assertEqual(fake.histories[0][0]['content'], SYSTEM_PROMPT)


if __name__ == '__main__':
    unittest.main()
