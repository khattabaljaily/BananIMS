#!/usr/bin/env python3
"""
يفحص المشروع بحثاً عن أي مصطلح طبي/دوائي أو إشارة لدولة بعينها لا يجوز أن
تظهر في BANAN IMS. يُشغَّل:

    python scripts/check_forbidden_terms.py            # كامل المشروع
    python scripts/check_forbidden_terms.py --staged   # الملفات المُجهَّزة للـ commit فقط

ويعمل تلقائياً قبل كل commit (scripts/install_git_hooks.sh) وضمن الاختبارات
(apps/core/tests_forbidden_terms.py). أي ورود يُوقف العملية برمز خروج 1.

ملاحظة عن الكلمات ذات المعنيين: «دفعة» (سداد مالي) و«صلاحية» (إذن وصول)
مستخدمتان بمعناهما العام في النظام، لذلك لا تُحظران منفردتين — المحظور هو
تراكيبهما الدوائية فقط (رقم الدفعة، تاريخ الصلاحية، ...).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = ['apps', 'PROJECT', 'templates', 'static/js', 'static/css', 'scripts', 'docs', 'deploy', '.github', 'branding']
SCAN_FILES = ['README.md', 'static/manifest.json', 'requirements.txt']
SCAN_SUFFIXES = {'.py', '.html', '.js', '.css', '.json', '.md', '.txt', '.sh', '.cnf', '.yml', '.yaml'}
SKIP_PARTS = {'__pycache__', 'node_modules', '.env', 'staticfiles', 'vendor'}
SKIP_FILES = {'scripts/check_forbidden_terms.py', 'apps/core/tests_forbidden_terms.py'}

# (regex, وصف) — بحث غير حساس لحالة الأحرف.
FORBIDDEN = [
    # ── صيدلة وأدوية ──
    (r'صيدل', 'صيدلية/صيدلي/صيدلاني'),
    (r'دواء|أدوية|ادوية|الدوائي|دوائية', 'دواء/أدوية'),
    (r'المادة الفعالة|مادة فعالة|الاسم العلمي', 'المادة الفعالة/الاسم العلمي'),
    (r'الشكل الصيدلاني|جرعة|جرعات', 'شكل صيدلاني/جرعة'),
    (r'وصفة طبية|روشت|بوصفة', 'وصفة طبية'),
    (r'مخدرات|خاضع للرقابة|الخاضعة للرقابة', 'مخدرات/رقابة دوائية'),
    (r'مستحضر', 'مستحضرات'),
    (r'\bمريض|المريض|المرضى|مستشفى|عيادة', 'مريض/مستشفى/عيادة'),
    (r'تأمين طبي|التأمين الطبي|شركة تأمين|شركات التأمين|بطاقة تأمين|بطاقة التأمين|مطالبة تأمين|مطالبات التأمين|المؤمَّن|المؤمن عليه', 'تأمين طبي'),
    (r'مستلزمات طبية|المستلزمات الطبية', 'مستلزمات طبية'),
    (r'عبوة|العبوة|عبوات|العبوات', 'عبوة (مصطلح النسخة الدوائية)'),
    (r'\bحبة\b|حبوب|أقراص|كبسول|مرهم|فيتامين|مكملات غذائية|مضاد حيوي|مسكنات', 'أشكال دوائية'),
    (r'💊|🩹|🌡️|💉|🩺|⚕', 'رمز تعبيري طبي'),
    (r'fa-pills|fa-capsules|fa-mortar-pestle|fa-prescription|fa-syringe|fa-briefcase-medical|fa-file-medical|fa-kit-medical|fa-shield-heart', 'أيقونة طبية'),
    # ── تشغيلات وصلاحية ──
    (r'تشغيلة|تشغيلات|باتش|رقم الدفعة|رقم الدُفعة|أرقام الدفعات|الدُفعات|دفعات المنتج', 'تشغيلة/دفعة مخزنية'),
    (r'تاريخ الصلاحية|تواريخ الصلاحية|انتهاء الصلاحية|منتهي الصلاحية|منتهية الصلاحية|قرب انتهاء صلاحية', 'تاريخ صلاحية'),
    # ── إنجليزي ──
    (r'pharma', 'pharma*'),
    (r'\bdrugs?\b|master_?drug', 'drug'),
    (r'\bmedicines?\b|\bmedication', 'medicine'),
    (r'prescription', 'prescription'),
    (r'dosage|generic_name', 'dosage/generic name'),
    (r'controlled.?substance', 'controlled substance'),
    (r'insurance', 'insurance'),
    (r'\bpatients?\b|hospital|clinic', 'patient/hospital/clinic'),
    (r'ItemBatch|batch_number|track_batch|track_expiry|has_expiry|has_batch|\bfefo\b|expiry_soon', 'batch/expiry tracking'),
    (r'\bPMS\b', 'PMS'),
    # ── دولة بعينها / منطقة بعينها ──
    (r'السودان|سوداني|الخرطوم|أمدرمان|ام درمان|بورتسودان', 'السودان'),
    (r'\bsudan|khartoum|\bSDG\b', 'Sudan/Khartoum/SDG'),
    (r'\bقطر\b|\bqatar\b|الخليج|\bgulf\b', 'قطر/الخليج'),
    (r'العالم العربي|الوطن العربي|\barab world', 'العالم العربي'),
    # ── العلامة التجارية القديمة (كلمة «إنجاز» العربية العامة مثل «أبرز إنجاز» مسموحة) ──
    (r'enjaz', 'Enjaz'),
    (r'(?<!أبرز )(?:انجاز|إنجاز)', 'انجاز/إنجاز كعلامة تجارية'),
    # ── العملة الصعبة وأسعار الصرف (عملة واحدة لكل مشترك: عملة بلده) ──
    (r'العملة الصعبة|عملة صعبة|hard.?currency|exchange.?rate|سعر الصرف|دولار|تقلب الأسعار|\busd', 'عملة صعبة/سعر صرف'),
    # ── أنماط الشراء الهجين/اللامركزي (المؤسسات مركزية دائماً) ──
    (r'هجين|لامركزي|\bhybrid|decentralized|purchasing_mode', 'شراء هجين/لامركزي'),
]

# استثناء وحيد مدروس: (مسار الملف، regex النص المسموح) — قائمة الدول والعملات
# وظيفية (يختار المشترك دولته ومنها تُشتقّ عملته)، وليست تموضعاً تسويقياً.
ALLOWED = [
    ('apps/core/constants.py', r'السودان|\bقطر\b|\bSDG\b|\bqatar\b|sudan|khartoum|الخليج|\bUSD\b'),
]

COMPILED = [(re.compile(p, re.IGNORECASE), d) for p, d in FORBIDDEN]
ALLOWED_COMPILED = [(path, re.compile(p, re.IGNORECASE)) for path, p in ALLOWED]


def iter_files(staged=False):
    if staged:
        out = subprocess.run(
            ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR'],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split()
        candidates = [ROOT / p for p in out]
    else:
        candidates = [ROOT / f for f in SCAN_FILES]
        for d in SCAN_DIRS:
            base = ROOT / d
            if base.exists():
                candidates.extend(p for p in base.rglob('*') if p.is_file())
    for path in candidates:
        rel = path.relative_to(ROOT).as_posix()
        if rel in SKIP_FILES or not path.exists():
            continue
        if set(path.relative_to(ROOT).parts) & SKIP_PARTS:
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        yield rel, path


def _is_allowed(rel, line):
    return any(
        (rel == path or (path.endswith('/') and rel.startswith(path))) and rx.search(line)
        for path, rx in ALLOWED_COMPILED
    )


def scan(staged=False):
    hits = []
    for rel, path in iter_files(staged):
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for rx, desc in COMPILED:
                if rx.search(line) and not _is_allowed(rel, line):
                    hits.append((rel, lineno, desc, line.strip()[:160]))
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--staged', action='store_true', help='افحص الملفات المُجهَّزة للـ commit فقط')
    parser.add_argument('--summary', action='store_true', help='اعرض عدد الورود لكل ملف فقط')
    args = parser.parse_args()

    hits = scan(staged=args.staged)
    if not hits:
        print('✓ لا توجد مصطلحات محظورة.')
        return 0

    if args.summary:
        counts = {}
        for rel, *_ in hits:
            counts[rel] = counts.get(rel, 0) + 1
        for rel, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f'{n:5d}  {rel}')
    else:
        for rel, lineno, desc, line in hits:
            print(f'{rel}:{lineno}: [{desc}] {line}')
    print(f'\n✗ {len(hits)} ورود لمصطلحات محظورة في BANAN IMS.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
