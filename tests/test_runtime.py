"""Regression checks for the configurable skill, with all network calls mocked."""
import atexit
import contextlib
import copy
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

skill = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('create_project', skill / 'scripts/create_project.py')
creator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creator)
validation_dir = Path(tempfile.gettempdir())
container = tempfile.TemporaryDirectory(prefix='runtime-test-', dir=validation_dir)
atexit.register(container.cleanup)
project = Path(container.name) / 'synthetic-team'
creator.create_project(project)
os.environ['LOCALAPPDATA'] = str(Path(container.name) / 'local-state')
config = json.loads((project / 'config.local.json').read_text(encoding='utf-8'))
config.update(profile_id='synthetic-regression', cohort='가상99기', group='새예시조', window_start='09:00:00', final_time='09:10:00', whole_minute_checkpoints=['09:05'], source_verified=True, mapping_verified=True)
(project / 'config.local.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
sys.path.insert(0, str(project / 'scripts'))
import runtime_config as settings
import check_common as common
import slack_api_delivery as sender
import site_checklist_api as site
import slack_command_listener as listener
import quick_check


class RuntimeTests(unittest.TestCase):
    def test_mapping_guards(self):
        path = project / 'invalid.json'
        candidate = copy.deepcopy(config)
        candidate['members'][1]['absent_confirmed'] = False
        path.write_text(json.dumps(candidate), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '부재'):
            settings.load_config(path)
        candidate = copy.deepcopy(config)
        candidate['members'][1]['author_id'] = candidate['members'][0]['author_id']
        candidate['members'][1]['communication_room'] = '가상별명B'
        path.write_text(json.dumps(candidate), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '중복'):
            settings.load_config(path)

    def test_dynamic_team_format_and_voice(self):
        at = dt.datetime.combine(dt.date.today(), settings.FINAL_TIME, settings.KST)
        message = common.slack_message(['가상B', '가상A'], ['가상C'], at, final=True)
        self.assertIn('가상99기 새예시조 하멈말', message)
        self.assertLess(message.index('1.가상B'), message.index('2.가상A'))
        self.assertNotIn('미완료', message)
        self.assertTrue(common.is_audio('', json.dumps({'url': 'https://example.invalid/voice.m4a'}), 18))
        self.assertTrue(common.is_audio('음성 메시지', '{}', 5))

    def test_receipts_snapshot_and_uncertain_post(self):
        day = dt.datetime.now(settings.KST).date()
        names = [m['site_name'] for m in config['members']]
        report = {'completed': names[:1], 'missing': names[1:], 'slack_message': '가상 검증 결과'}
        calls = []
        def api(method, payload, token):
            calls.append(method)
            if method == 'auth.test':
                return {'team_id': config['slack']['workspace_id'], 'url': 'https://example.slack.com'}
            if method == 'chat.getPermalink':
                return {'permalink': 'https://example.slack.com/archives/CEXAMPLE/p123400'}
            return {'channel': config['slack']['channel_id'], 'ts': '1234.00'}
        args = ['sender', '--send', '--date', day.isoformat(), '--as-of', '09:05:20']
        receipt = project / 'receipts.json'
        with patch.object(sender, 'RECEIPTS', receipt), patch.object(sender, 'api', side_effect=api), patch.object(sender, 'validated_report', return_value=report), patch.dict(os.environ, SLACK_BOT_TOKEN='xoxb-synthetic'), patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()):
            sender.main()
            with patch.object(sender, 'validated_report', side_effect=AssertionError('snapshot must be reused')):
                sender.main()
        self.assertEqual(calls.count('chat.postMessage'), 1)
        records = json.loads(receipt.read_text(encoding='utf-8'))
        next(iter(records.values()))['state'] = 'attempting'
        receipt.write_text(json.dumps(records), encoding='utf-8')
        with patch.object(sender, 'RECEIPTS', receipt), patch.object(sender, 'api', side_effect=api), patch.dict(os.environ, SLACK_BOT_TOKEN='xoxb-synthetic'), patch.object(sys, 'argv', args):
            with self.assertRaisesRegex(RuntimeError, '중복 전송 방지'):
                sender.main()
        self.assertEqual(calls.count('chat.postMessage'), 1)

    def test_site_two_members_saves_only_completed(self):
        a, b = config['members']
        rows = [{'real_name': a['real_name'], 'group_id': 7, 'id': 11}, {'real_name': b['real_name'], 'group_id': 7, 'id': 12}]
        checks = {'11': {'3': {'status': False}}, '12': {'3': {'status': True}}}
        saved = []
        class Client:
            def request(self, path, *, params=None, body=None):
                action = path.split('action=')[1]
                if action == 'login_phone':
                    return {'admin': {'admin_roles': ['leader'], 'bootcamp_group_id': 7}}
                if action == 'cohorts':
                    return {'cohorts': [{'cohort': config['cohort'], 'id': 2}]}
                if action == 'groups':
                    return {'groups': [{'id': 7, 'name': config['group']}]}
                if action == 'mission_types':
                    return {'mission_types': [{'id': 3, 'name': config['mission'], 'code': 'VOICE'}]}
                if action == 'checklist':
                    return {'members': rows, 'checks': copy.deepcopy(checks)}
                if action == 'check_bulk_save':
                    saved.extend(body['items'])
                    for item in body['items']:
                        checks[str(item['member_id'])]['3']['status'] = True
                    return {'success': True}
                raise AssertionError(action)
        payload = {'date': dt.datetime.now(settings.KST).date().isoformat(), 'completed': [a['site_name']], 'missing': [b['site_name']]}
        with patch.object(site, 'SiteClient', Client), patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), patch.dict(os.environ, SORITUNE_LEADER_PHONE='synthetic'), contextlib.redirect_stdout(io.StringIO()):
            site.main()
        self.assertEqual([item['member_id'] for item in saved], [11])
        self.assertTrue(checks['12']['3']['status'])

    def test_listener_configured_boundary(self):
        at = dt.datetime.combine(dt.datetime.now(settings.KST).date(), dt.time(9, 11), settings.KST)
        class Client:
            def request(self, method, payload):
                return {'channel': config['slack']['channel_id'], 'ts': '123.45'}
        calls = []
        def runner(mode, day, as_of, thread_ts, powershell):
            calls.append((mode, as_of))
            return {'slack': {'sent': True, 'permalink': 'https://example.invalid', 'completed_count': 1, 'missing_count': 1}, 'site': {'verified_after_save': True, 'completed_count': 1}}
        instance = listener.Listener(Client(), project / 'listener-state', 'pwsh.exe', runner=runner, now=lambda: at)
        instance.state['cursor'] = str(at.timestamp() - 2)
        instance.bot_user_id = 'UBOT'
        instance.process({'ts': str(at.timestamp() - 1), 'user': 'UHUMAN', 'text': '지금 체크해줘'})
        self.assertEqual(calls, [('final', '09:10')])

    def test_short_command_uses_quick_route(self):
        at = dt.datetime.combine(dt.datetime.now(settings.KST).date(), dt.time(9, 11), settings.KST)
        for text in ('체크', 'check', 'CHECK!'):
            self.assertTrue(listener.is_command({'user': 'UHUMAN', 'text': text, 'ts': '10.0'}, 'UBOT'))
        client = unittest.mock.Mock()
        client.request.return_value = {'channel': config['slack']['channel_id'], 'ts': '100.00'}
        runner = unittest.mock.Mock(return_value={'sent': True, 'permalink': 'https://example.invalid', 'completed_count': 1, 'missing_count': 1})
        instance = listener.Listener(client, project / 'quick-command-state', 'pwsh.exe', runner=runner, now=lambda: at)
        instance.state['cursor'] = str(at.timestamp() - 2)
        instance.bot_user_id = 'UBOT'
        instance.process({'ts': str(at.timestamp() - 1), 'user': 'UHUMAN', 'text': 'check'})
        self.assertEqual(runner.call_args.args[0], 'quick')

    def test_powershell_quick_preview_reaches_profile_queue(self):
        powershell = shutil.which('pwsh')
        if powershell is None:
            self.skipTest('PowerShell 7 is required for this Windows entrypoint')
        state = settings.STATE_DIR / 'slack_listener'
        state.mkdir(parents=True, exist_ok=True)
        (state / 'status.json').write_text(json.dumps({'checked_at': dt.datetime.now(settings.KST).isoformat()}), encoding='utf-8')
        checker = unittest.mock.Mock()
        checker.run.return_value = {'preview': True, 'completed': ['synthetic'], 'as_of': '09:05:00'}
        queue = quick_check.LocalQuickRequests(state / 'quick_requests', checker, lambda: 'unused')
        stop = threading.Event()
        def work():
            while not stop.wait(0.02):
                queue.poll()
        thread = threading.Thread(target=work)
        thread.start()
        try:
            result = subprocess.run([powershell, '-NoProfile', '-File', str(project / 'scripts/run_check_now.ps1'), '-Preview'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
        finally:
            stop.set()
            thread.join()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['preview'])
        checker.run.assert_called_once()


class QuickCheckTests(unittest.TestCase):
    def test_reuses_verified_key_and_recovers_after_process_change(self):
        checker = quick_check.QuickChecker()
        with patch.object(quick_check.reader.memkey, "find_pids", side_effect=[[100], [100], [200]]), \
             patch.object(quick_check.reader.decryptor, "first_page", return_value=b"page"), \
             patch.object(quick_check.reader.sqlcipher_v4, "try_raw_key", return_value=True), \
             patch.object(quick_check.reader, "recover_key", side_effect=[b"first", b"second"]) as recover:
            self.assertEqual(checker.key(), b"first")
            self.assertEqual(checker.key(), b"first")
            self.assertEqual(checker.key(), b"second")
        self.assertEqual(recover.call_count, 2)
        self.assertEqual(checker.key_hits, 1)

    def test_rejects_cached_key_that_no_longer_validates(self):
        checker = quick_check.QuickChecker()
        with patch.object(quick_check.reader.memkey, "find_pids", return_value=[100]), \
             patch.object(quick_check.reader.decryptor, "first_page", return_value=b"page"), \
             patch.object(quick_check.reader.sqlcipher_v4, "try_raw_key", return_value=False), \
             patch.object(quick_check.reader, "recover_key", side_effect=[b"old", b"new"]) as recover:
            checker.key()
            self.assertEqual(checker.key(), b"new")
        self.assertEqual(recover.call_count, 2)

    def test_completed_request_is_not_replayed(self):
        with tempfile.TemporaryDirectory(dir=validation_dir) as folder:
            checker = unittest.mock.Mock()
            checker.run.return_value = {"preview": True}
            requests = quick_check.LocalQuickRequests(Path(folder), checker, lambda: "synthetic")
            path = Path(folder) / "request.json"
            path.write_text(json.dumps({"state": "pending", "action": "preview",
                "requested_at": dt.datetime.now(quick_check.reader.KST).isoformat()}), encoding="utf-8")
            requests.poll()
            requests.poll()
            self.assertEqual(checker.run.call_count, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "completed")

    def test_interrupted_request_does_not_run_again(self):
        with tempfile.TemporaryDirectory(dir=validation_dir) as folder:
            checker = unittest.mock.Mock()
            requests = quick_check.LocalQuickRequests(Path(folder), checker, lambda: "synthetic")
            path = Path(folder) / "request.json"
            path.write_text(json.dumps({"state": "processing"}), encoding="utf-8")
            requests.poll()
            checker.run.assert_not_called()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "failed")

if __name__ == '__main__':
    unittest.main()
