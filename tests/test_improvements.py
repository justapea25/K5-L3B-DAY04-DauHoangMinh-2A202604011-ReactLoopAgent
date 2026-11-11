"""Tests offline cho cải tiến Bài 4: link gate và ghi chú khi tool lỗi."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final

LINKING = '{"provider":"github","incident_id":"h02n9572mx9y"}'   # update trỏ tới xr3myzj7ms51
LINKED = '{"provider":"github","incident_id":"xr3myzj7ms51"}'
URL_A, URL_B = 'https://stspg.io/7pwv28hvkmz8', 'https://stspg.io/pjgptg3cfc6n'


class LinkGateTests(unittest.TestCase):
    def test_unread_linked_incident_is_requested(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', LINKING), final('Xong ' + URL_A),
                             tool_call('2', 'get_incident_details', LINKED), final(f'Xong {URL_A} {URL_B}')])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        gate = [t for t in result['trace'] if t['event'] == 'validation_unread_link']
        self.assertEqual(gate[0]['linked'], ['github/xr3myzj7ms51'])
        self.assertIn('xr3myzj7ms51', fake.histories[2][-1]['content'])

    def test_link_gate_nudges_only_once(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', LINKING), final('A ' + URL_A), final('B ' + URL_A)])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['answer'], 'B ' + URL_A)

    def test_already_read_link_does_not_trigger(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', LINKED),
                             tool_call('2', 'get_incident_details', LINKING), final(f'{URL_A} {URL_B}')])
        result = run_agent('x', fake, StatusTools())
        self.assertFalse(any(t['event'] == 'validation_unread_link' for t in result['trace']))


class FailedToolNoteTests(unittest.TestCase):
    def test_failed_tool_observation_has_note_but_trace_keeps_raw(self):
        fake = FakeProvider([tool_call('1', 'get_status', '{"provider":"invalid"}'), final('Không kiểm tra được')])
        result = run_agent('x', fake, StatusTools())
        sent = json.loads(fake.histories[1][-1]['content'])
        self.assertFalse(sent['ok'])
        self.assertIn('KHÔNG có dữ liệu', sent['note'])
        raw = [t for t in result['trace'] if t['event'] == 'tool'][0]['result']
        self.assertNotIn('note', raw)


if __name__ == '__main__':
    unittest.main()
