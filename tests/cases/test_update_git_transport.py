"""Real task-owned parent/child fixtures for git update timeout cleanup."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import check_update as update


class GitUpdateTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='update-git-transport-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_real_git_parent_and_child_are_stopped_for_clone_and_show(self):
        child_code = '''
import os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / 'child.pid').write_text(str(os.getpid()))
print('remote child retains stdout and stderr', flush=True)
print('remote child error stream', file=sys.stderr, flush=True)
time.sleep(2)
(root / 'child-survived').write_text('alive')
time.sleep(20)
'''
        parent_code = '''
import os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / 'parent.pid').write_text(str(os.getpid()))
subprocess.Popen([sys.executable, '-B', str(root / 'child.py'), str(root)])
time.sleep(30)
'''
        runner_code = '''
import json, subprocess, sys, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import check_update as update
root, mode = Path(sys.argv[2]), sys.argv[3]
import local_update_guard as guard
original_popen, original_run = subprocess.Popen, update._run_git
owned = []
clone_directory = None
def launch(command, **kwargs):
    global clone_directory
    if command[0] == 'git':
        role = command[1]
        if role == 'clone':
            clone_directory = Path(command[-1])
            clone_directory.mkdir(parents=True,exist_ok=True)
            kwargs['cwd'] = clone_directory
        command = ([sys.executable, '-B', str(root / 'parent.py'), str(root)]
                   if role == mode or mode == 'stage' else [sys.executable, '-B', '-c', 'print("{}")'])
        child = original_popen(command, **kwargs)
        owned.append(child)
        return child
    return original_popen(command, **kwargs)
def bounded(command, **kwargs):
    kwargs['timeout'] = .8
    return original_run(command, **kwargs)
started = time.monotonic()
with patch.object(update.subprocess, 'Popen', side_effect=launch), \
     patch.object(update, '_run_git', side_effect=bounded), \
     patch.object(guard, '_run_git', side_effect=bounded):
    try:
        if mode == 'stage':
            live=root/'live';live.mkdir();(live/'SKILL.md').write_text('local rules')
            (live/'VERSION').write_text('1.0')
            (live/'updates.json').write_text(json.dumps({'update_source':'git+https://unused.invalid/repository#main'}))
            guard.prepare(live,root/'staged')
        else:
            update.fetch_remote_updates('git+https://unused.invalid/repository#main')
        result = {'unexpected_success': True}
    except subprocess.TimeoutExpired:
        result = {'exception': 'TimeoutExpired'}
result.update(elapsed=time.monotonic()-started,
              parent_codes=[child.poll() for child in owned],
              clone_directory_removed=not clone_directory.exists())
if mode == 'stage':
    result['local_rules_preserved']=(root/'live/SKILL.md').read_text()=='local rules'
    result['no_apply_plan']=not (root/'staged/plan.json').exists()
print(json.dumps(result))
'''
        unrelated = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(30)'],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for mode in ('clone', 'show', 'stage'):
                with self.subTest(mode=mode):
                    root = self.root / mode
                    root.mkdir()
                    for name, text in [('parent.py', parent_code), ('child.py', child_code),
                                       ('runner.py', runner_code)]:
                        (root / name).write_text(text, encoding='utf8')
                    runner = subprocess.run([sys.executable, '-B', '-X', 'utf8',
                                             str(root / 'runner.py'), str(Path(update.__file__).parent),
                                             str(root), mode], capture_output=True,
                                            encoding='utf8', timeout=10,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.assertEqual(runner.returncode, 0, runner.stderr)
                    result = json.loads(runner.stdout)
                    self.assertEqual(result['exception'], 'TimeoutExpired')
                    self.assertLess(result['elapsed'], 5)
                    if mode == 'stage':
                        self.assertTrue(result['local_rules_preserved'])
                        self.assertTrue(result['no_apply_plan'])
                    else:
                        self.assertTrue(result['clone_directory_removed'])
                    self.assertTrue(all(code is not None for code in result['parent_codes']))
                    self.assertTrue((root / 'child.pid').is_file(), 'Real descendant must start.')
                    time.sleep(2.1)
                    self.assertFalse((root / 'child-survived').exists())
                    self.assertIsNone(unrelated.poll(), 'Unrelated process must be preserved.')
        finally:
            unrelated.kill()
            unrelated.wait(timeout=5)

    def test_git_output_and_process_failure_keep_bytes_and_status(self):
        result = update._run_git([sys.executable, '-B', '-c', 'print("{}")'],
                                 env=os.environ.copy(), timeout=5)
        self.assertEqual(json.loads(result.stdout), {})
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            update._run_git([sys.executable, '-B', '-c',
                             'import sys; print("failure", file=sys.stderr); sys.exit(17)'],
                            env=os.environ.copy(), timeout=5)
        self.assertEqual(caught.exception.returncode, 17)
        self.assertIn(b'failure', caught.exception.stderr)

    def test_git_metadata_output_limit_is_enforced(self):
        with patch.object(update, 'HTTP_METADATA_LIMIT', 16), self.assertRaisesRegex(OSError, 'byte limit'):
            update._run_git([sys.executable, '-B', '-c', 'print("x" * 17)'],
                            env=os.environ.copy(), timeout=5)

    def test_cancelled_update_check_has_status_130(self):
        (self.root / 'VERSION').write_text('1.0', encoding='utf8')
        (self.root / 'updates.json').write_text(
            json.dumps({'update_source': 'git+https://unused.invalid/repo#main'}), encoding='utf8')
        error = io.StringIO()
        with patch.object(sys, 'argv', ['check_update', '--skill-root', str(self.root)]), \
                patch.object(update, 'fetch_remote_updates', side_effect=KeyboardInterrupt), \
                contextlib.redirect_stderr(error):
            code = update.main()
        self.assertEqual(code, 130)
        self.assertIn('remote version is unverified', error.getvalue())
        self.assertNotIn('Traceback', error.getvalue())


if __name__ == '__main__':
    unittest.main()
