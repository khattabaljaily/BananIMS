"""
يضمن أن BANAN IMS لا يحمل أي مصطلح من القائمة المحظورة في
scripts/check_forbidden_terms.py (مصطلحات قطاع النسخة الشقيقة، تتبع
التشغيلات والصلاحية، أو تموضع بدولة بعينها).
"""
import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_forbidden_terms.py'


def _load_checker():
    spec = importlib.util.spec_from_file_location('check_forbidden_terms', _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ForbiddenTermsTests(SimpleTestCase):
    def test_codebase_has_no_forbidden_terms(self):
        hits = _load_checker().scan()
        report = '\n'.join(f'{rel}:{lineno}: [{desc}] {line}' for rel, lineno, desc, line in hits[:50])
        self.assertFalse(hits, f'مصطلحات محظورة ({len(hits)}):\n{report}')
