import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import demo

class FakeAPI:
    calls = []
    def __init__(self, key): pass
    def stocks(self): return {'items': [{'symbol': '7203.T'}]}
    def reports(self): return {'items': [{'id': 7, 'symbol': '7203.T', 'doc_type': 'annual', 'report_period': '2025-03-31'}]}
    def sections(self, doc): return {'sections': ['Risk', 'Financial']}
    def section(self, doc, title):
        self.calls.append((doc, title))
        return {'content': 'SYNTHETIC TEST DATA ONLY ' * (2000 if title == 'Financial' else 1)}

class FakeEncoding:
    def encode(self, text): return list(text)

class PipelineTests(unittest.TestCase):
    def test_retrieve_budget_and_live_output_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'prompts').mkdir()
            (root/'prompts/financial_analysis.md').write_text('## Financial performance')
            FakeAPI.calls = []
            response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='## Financial performance\n**Fact:** SYNTHETIC TEST DATA ONLY [S1]'), finish_reason='stop')], usage=None)
            fake_openai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
            with patch.object(demo, 'ROOT', root), patch.object(demo, 'DataSinkingClient', FakeAPI), patch.object(demo.tiktoken, 'encoding_for_model', return_value=FakeEncoding()), patch.object(demo, 'OpenAI', return_value=fake_openai), patch.dict(os.environ, {'DATASINK_API_KEY':'TEST_PLACEHOLDER','OPENAI_API_KEY':'TEST_PLACEHOLDER'}), patch('sys.argv', ['demo.py', '--max-input-tokens','2000']):
                self.assertEqual(demo.main(), 0)
            manifest = json.loads((root/'output/retrieval_manifest.json').read_text())
            self.assertFalse(manifest['full_report_fetched'])
            self.assertLessEqual(manifest['estimated_input_tokens_with_margin'], 2000)
            self.assertEqual(len(manifest['selected_sections']), 1)
            self.assertEqual(manifest['skipped_sections'][0]['title'], 'Financial')
            self.assertEqual(manifest['status'], 'analysis_completed')
            self.assertTrue((root/'output/analysis.md').exists())
            self.assertEqual(FakeAPI.calls, [(7,'Risk'), (7,'Financial')])

    def test_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(demo, 'load_dotenv'), patch('sys.argv', ['demo.py']):
            self.assertEqual(demo.main(), 2)
