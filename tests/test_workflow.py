"""Research, import and experiment workflows through the real HTTP boundary."""
import copy
import csv
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ashare_monitor.runtime import Runtime
from ashare_monitor.server import DashboardServer
from test_research import stock


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(self.tmp.name)
        self.runtime.state['settings']['auto_refresh'] = False
        self.runtime.start()
        self.server = DashboardServer(('127.0.0.1', 0), self.runtime)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.runtime.close()
        self.tmp.cleanup()

    def call(self, path, payload=None, expected=200):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': self.server.token}
        connection.request('GET' if payload is None else 'POST', path,
                           None if payload is None else json.dumps(payload).encode(), headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        result = json.loads(raw)
        self.assertEqual(status, expected, result)
        return result

    def idle(self, research=False):
        attribute = 'research_busy' if research else 'refreshing'
        deadline = time.monotonic() + 15
        while getattr(self.runtime, attribute) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(getattr(self.runtime, attribute))

    def csv_fixture(self):
        # Deliberately artificial data serialized as a genuine CSV import;
        # it tests the data path, never serves as evidence of actual returns.
        item = stock(90)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'adjustment'])
        writer.writeheader()
        writer.writerows({**row, 'adjustment': 'none'} for row in item['candles'])
        return item, output.getvalue()

    def test_csv_research_report_archive_and_account_isolation(self):
        item, text = self.csv_fixture()
        before = copy.deepcopy(self.runtime.state)
        validation = self.call('/api/imports/validate', {'code': item['code'], 'text': text})
        self.assertTrue(validation['valid'])
        self.call('/api/imports/commit', {'code': item['code'], 'text': text})
        payload = {'name': 'CSV workflow fixture', 'mode': 'csv', 'codes': [item['code']],
                   'start_date': item['candles'][59]['date'], 'end_date': item['candles'][-1]['date'],
                   'strategies': {'teaching': {'min_score': 0, 'max_rsi': 100, 'max_distance_pct': 30}},
                   'max_holding_days': 1}
        response = self.call('/api/research', payload, expected=202)
        self.idle(research=True)
        detail = self.call('/api/research/' + response['id'])
        self.assertEqual(detail['status'], 'completed', detail['error'])
        self.assertNotIn('dataset', detail)
        report = detail['report']
        self.assertEqual(report['mode'], 'csv')
        self.assertGreater(report['metrics']['trade_count'], 0)
        self.assertGreater(report['trades'][0]['date'], report['trades'][0]['signal_date'])
        self.assertEqual(len(report['data_fingerprint']), 64)
        self.assertEqual(self.runtime.state, before)
        stored = self.runtime.store.experiment(response['id'])
        self.assertEqual(stored['dataset']['stocks'][0]['candles'], item['candles'])
        listing = self.call('/api/research')
        self.assertNotIn('report', listing['items'][0])
        self.assertNotIn('dataset', listing['items'][0])
        self.assertEqual(listing['items'][0]['metrics'], report['metrics'])
        self.assertEqual(listing['items'][0]['quality'], report['quality'])
        self.call('/api/research/' + response['id'] + '/archive', {})
        restored = Runtime(self.tmp.name)
        self.assertTrue(restored.store.experiment(response['id'])['archived'])
        self.assertEqual(restored.state['ledger'], before['ledger'])

    def test_import_errors_overwrite_and_no_partial_mutation(self):
        item, text = self.csv_fixture()
        code = item['code']
        bad = text.replace(item['candles'][0]['date'], '2025-01-01', 1)
        checked = self.call('/api/imports/validate', {'code': code, 'text': bad})
        self.assertFalse(checked['valid'])
        self.assertEqual(checked['errors'][0]['line'], 2)
        self.call('/api/imports/commit', {'code': code, 'text': bad}, expected=400)
        self.assertFalse((self.runtime.csv_dir / (code + '.csv')).exists())
        self.call('/api/imports/commit', {'code': code, 'text': text})
        target = self.runtime.csv_dir / (code + '.csv')
        original = target.read_bytes()
        changed = text.replace('1000000', '2000000')
        self.call('/api/imports/commit', {'code': code, 'text': changed}, expected=400)
        self.assertEqual(target.read_bytes(), original)
        self.call('/api/imports/commit', {'code': code, 'text': changed, 'overwrite': True})
        self.assertNotEqual(target.read_bytes(), original)
        self.call('/api/imports/commit', {'code': '../escape', 'text': text}, expected=400)

    def test_demo_archive_preserves_account_and_is_atomic(self):
        self.call('/api/paper/order', {'code': '600036', 'side': 'buy', 'quantity': 100, 'request_id': 'archive-workflow'})
        old = copy.deepcopy(self.runtime.state)
        payload = {'name': 'Independent demo', 'initial_cash': 200000, 'start_date': '2026-10-08'}
        with patch.object(self.runtime.store, 'save', side_effect=OSError('disk unavailable')):
            self.call('/api/demo/experiments', payload, expected=500)
        self.assertEqual(self.runtime.state, old)
        self.assertEqual(self.call('/api/demo/experiments')['total'], 0)
        created = self.call('/api/demo/experiments', payload, expected=202)
        self.idle()
        archived = self.call('/api/demo/experiments/' + created['archived_id'])
        self.assertEqual(archived['report']['ledger'], old['ledger'])
        self.assertEqual(self.runtime.state['ledger']['orders'], [])
        self.assertEqual(self.runtime.snapshot('x')['portfolio']['cash'], 200000)
        restored = Runtime(self.tmp.name)
        self.assertEqual(restored.state, self.runtime.state)
        self.call('/api/demo/experiments', {**payload, 'start_date': '2026-10-01'}, expected=400)

    def test_research_failures_and_busy_are_visible_without_lost_flag(self):
        payload = {'name': 'Missing CSV', 'mode': 'csv', 'codes': ['600036'], 'end_date': '2026-10-12'}
        created = self.call('/api/research', payload, expected=202)
        self.idle(research=True)
        detail = self.call('/api/research/' + created['id'])
        self.assertEqual(detail['status'], 'failed')
        self.assertTrue(detail['error'])
        self.assertFalse(self.runtime.research_busy)
        with patch.object(self.runtime.store, 'create_experiment', side_effect=OSError('disk failure')):
            self.call('/api/research', payload, expected=500)
        self.assertFalse(self.runtime.research_busy)
        with self.runtime.lock:
            self.runtime.research_busy = True
        try:
            self.call('/api/research', payload, expected=409)
            _, text = self.csv_fixture()
            self.call('/api/imports/commit', {'code': '600036', 'text': text}, expected=409)
        finally:
            self.runtime.research_busy = False
        self.call('/api/research', {**payload, 'strategy_id': 'missing'}, expected=400)
        self.call('/api/research', {**payload, 'end_date': '2026-12-31'}, expected=400)
        self.call('/api/research', {**payload, 'codes': ['600036', '600036']}, expected=400)

    def test_lost_worker_recovery_does_not_overwrite_completed_report(self):
        item = self.runtime.store.create_experiment('research', 'Interrupted', {}, '2026-10-13T00:00:00Z')
        done = self.runtime.store.create_experiment('research', 'Finished', {}, '2026-10-13T00:00:01Z')
        self.runtime.store.update_experiment(done['id'], {'status': 'completed', 'report': {'metrics': {'trade_count': 1}}})
        self.runtime.store.recover_research()
        self.assertEqual(self.call('/api/research/' + item['id'])['status'], 'failed')
        self.assertEqual(self.call('/api/research/' + done['id'])['report']['metrics']['trade_count'], 1)

    def test_history_details_are_persisted_not_recomputed(self):
        listing = self.call('/api/history')
        scan_id = listing['items'][0]['id']
        detail = self.call('/api/history/' + str(scan_id))
        self.assertEqual(len(detail['details']['analyses']), 8)
        self.assertNotIn('chart_series', detail['details']['analyses'][0])
        self.call('/api/settings', {'strategy_config': {'teaching': {'enabled': False}}}, expected=202)
        self.idle()
        self.assertEqual(self.call('/api/history/' + str(scan_id)), detail)
        self.runtime.store.save(self.runtime.state, {'created_at': '2026-10-13T00:00:00Z', 'summary': 'legacy'})
        legacy_id = self.call('/api/history')['items'][0]['id']
        self.assertIsNone(self.call('/api/history/' + str(legacy_id))['details'])
        self.call('/api/history/999999', expected=404)
        self.call('/api/research/missing', expected=404)

    def test_compact_state_and_server_paging_preserve_exact_totals(self):
        for index in range(35):
            self.runtime.paper_order({'code': '600036', 'side': 'buy', 'quantity': 100, 'request_id': f'paging-{index:08}'})
            self.runtime.cancel({'order_id': f'paper-{index + 1}'})
        state = self.call('/api/state')
        self.assertEqual(state['portfolio']['order_count'], 35)
        self.assertNotIn('orders', state['portfolio'])
        self.assertNotIn('raw_candles', state['stocks'][0])
        page1 = self.call('/api/paper/records?kind=orders&page=1')
        page2 = self.call('/api/paper/records?kind=orders&page=2')
        self.assertEqual((len(page1['items']), len(page2['items'])), (30, 5))
        self.assertEqual(page1['items'][0]['id'], 'paper-35')
        self.assertEqual(page2['items'][-1]['id'], 'paper-1')
        self.assertEqual(page1['total'], 35)
        self.call('/api/paper/records?kind=invalid', expected=400)

    def test_strategy_and_group_configuration_validation(self):
        self.assertEqual(len(self.call('/api/strategies')['strategies']), 3)
        self.assertTrue(self.call('/api/stocks/templates')['items'])
        self.assertTrue(self.call('/api/stocks/search?q=600036')['items'])
        before = self.runtime.store.load()
        for payload in ({'strategy_config': {'bad': {}}}, {'watchlist_groups': {'group': ['600036', '600036']}},
                        {'watchlist_groups': {'group': ['../../']}}):
            self.call('/api/settings', payload, expected=400)
            self.assertEqual(self.runtime.store.load(), before)
        self.call('/api/settings', {'watchlist_groups': {'银行': ['600036', '601398']}}, expected=202)
        self.idle()
        self.assertEqual(Runtime(self.tmp.name).state['settings']['watchlist_groups']['银行'], ['600036', '601398'])


if __name__ == '__main__':
    unittest.main()
