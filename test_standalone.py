import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server

class StandaloneTests(unittest.TestCase):
    def test_default_uses_existing_specs_sibling_not_the_tool_repository(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'__file__',str(Path(folder).resolve()/'spec-review/server.py')),patch.dict(os.environ,{'XML_REVIEW_REPO':''}),patch.object(server.subprocess,'check_output',return_value=b'git@github.com:onvif/specs.git\n'):
            sibling=Path(folder).resolve()/'specs';sibling.mkdir()
            self.assertEqual(server.default_repo(),sibling)
    def test_unrelated_sibling_uses_cache_and_environment_override_is_respected(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'__file__',str(Path(folder).resolve()/'spec-review/server.py')),patch.dict(os.environ,{'XML_REVIEW_REPO':''}),patch.object(server.subprocess,'check_output',return_value=b'https://github.com/other/specs.git\n'):
            (Path(folder).resolve()/'specs').mkdir()
            self.assertEqual(server.default_repo(),Path(folder).resolve()/'spec-review/.cache/specs')
            with patch.dict(os.environ,{'XML_REVIEW_REPO':str(Path(folder).resolve()/'chosen')}):self.assertEqual(server.default_repo(),Path(folder).resolve()/'chosen')
    def test_missing_explicit_checkout_is_not_silently_cloned(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server.subprocess,'check_call') as clone:
            with self.assertRaisesRegex(ValueError,'does not exist'):server.ensure_specs_checkout(Path(folder).resolve()/'missing')
            clone.assert_not_called()
    def test_first_launch_clones_only_the_known_public_target_into_cache(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'__file__',str(Path(folder).resolve()/'spec-review/server.py')),patch.object(server.subprocess,'check_call') as clone,patch.object(server,'git',return_value=b'.git'),patch.object(server,'github_repo',return_value='onvif/specs'):
            cached=Path(folder).resolve()/'spec-review/.cache/specs';server.ensure_specs_checkout(cached)
            self.assertEqual(clone.call_args.args[0],['git','clone','--filter=blob:none','https://github.com/onvif/specs.git',str(cached)])
    def test_tool_repository_cannot_be_mistaken_for_specs(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'git',return_value=b'.git'),patch.object(server,'github_repo',return_value='videoai/spec-review'):
            with self.assertRaisesRegex(ValueError,'Unsupported review repository'):server.ensure_specs_checkout(Path(folder).resolve())

if __name__=='__main__':unittest.main()
