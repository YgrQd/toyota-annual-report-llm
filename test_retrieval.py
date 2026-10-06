import unittest
from src.retrieval import items, select, section_titles, extract_content, validate_analysis

class RetrievalTests(unittest.TestCase):
    def test_japanese_coverage(self):
        result = select(['会社概要', '事業の内容', '事業等のリスク', '研究開発活動', '経理の状況', '経営方針'], 5)
        self.assertEqual(len(result), 5)
        self.assertEqual({t for _, groups in result for t in groups}, {'business','risk','technology','financial','strategy'})
    def test_catalog_shapes(self):
        self.assertEqual(section_titles({'sections': [{'title': 'Risk'}, 'Financial']}), ['Risk','Financial'])
        with self.assertRaises(ValueError): items({'unexpected': []})
    def test_invalid_content(self):
        with self.assertRaises(ValueError): extract_content({'text': 'wrong field'})
    def test_citations(self):
        validate_analysis('Evidence [S1]', ['S1'])
        with self.assertRaises(ValueError): validate_analysis('Invented [S9]', ['S1'])
        with self.assertRaises(ValueError): validate_analysis('No evidence', ['S1'])
