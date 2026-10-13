"""Exercise commit-email privacy rules against disposable Git repositories."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import privacy_check


class CommitEmailPrivacyTests(unittest.TestCase):
    def scan_commit(self, author_email, committer_email):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.dockerignore').write_text(
                '**\n!Dockerfile\n!server.py\n!public/\n!public/**\n', encoding='utf-8')
            (root / 'README.md').write_text('Disposable privacy-test source.\n', encoding='utf-8')
            environment = os.environ.copy()
            environment.update({
                'GIT_CONFIG_NOSYSTEM': '1',
                'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_AUTHOR_NAME': 'Fixture author',
                'GIT_AUTHOR_EMAIL': author_email,
                'GIT_COMMITTER_NAME': 'Fixture committer',
                'GIT_COMMITTER_EMAIL': committer_email,
            })
            for arguments in [('init', '--quiet'), ('add', '.'), ('commit', '--quiet', '-m', 'Fixture')]:
                subprocess.run(['git', '-C', str(root), *arguments], env=environment,
                               check=True, capture_output=True)
            output = io.StringIO()
            with patch.object(privacy_check, 'ROOT', root), \
                    patch.object(sys, 'argv', ['privacy_check.py', '--history']), \
                    contextlib.redirect_stdout(output):
                result = privacy_check.main()
            return result, output.getvalue()

    def test_github_web_commit_accepts_platform_noreply_committer(self):
        result, output = self.scan_commit(
            'fixture-user@users.noreply.github.com', 'noreply@github.com')
        self.assertEqual(result, 0, output)

    def test_user_noreply_author_and_committer_remain_allowed(self):
        result, output = self.scan_commit(
            'fixture-user@users.noreply.github.com', 'fixture-user@users.noreply.github.com')
        self.assertEqual(result, 0, output)

    def test_github_committer_does_not_exempt_personal_author_email(self):
        result, output = self.scan_commit('fixture-private@example.com', 'noreply@github.com')
        self.assertEqual(result, 1)
        self.assertIn('non-noreply commit email', output)
        self.assertNotIn('fixture-private@example.com', output)

    def test_personal_committer_email_is_rejected(self):
        result, output = self.scan_commit(
            'fixture-user@users.noreply.github.com', 'fixture-private@example.com')
        self.assertEqual(result, 1)
        self.assertIn('non-noreply commit email', output)
        self.assertNotIn('fixture-private@example.com', output)

    def test_lookalike_noreply_domain_is_rejected(self):
        result, output = self.scan_commit(
            'fixture-user@users.noreply.github.com.example', 'noreply@github.com')
        self.assertEqual(result, 1)
        self.assertIn('non-noreply commit email', output)


if __name__ == '__main__':
    unittest.main()
