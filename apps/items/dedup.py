"""
Duplicate detection for tenant-level Item creation (used by the product
importer): barcode, then SKU, then exact name, then a bucketed difflib
fallback on the normalized name so it never scans the whole tenant.
"""
import difflib
import re
import unicodedata

from .models import Item

_ARABIC_DIACRITICS = re.compile(r'[ً-ٰٟۖ-ۭ]')
_WHITESPACE = re.compile(r'\s+')
_PUNCTUATION = re.compile(r'[^\w\s]', re.UNICODE)

FUZZY_DUPLICATE_RATIO = 0.65


def normalize_text(value: str) -> str:
    """Lowercase, strip Arabic diacritics/punctuation, collapse whitespace."""
    if not value:
        return ''
    value = unicodedata.normalize('NFKC', str(value))
    value = _ARABIC_DIACRITICS.sub('', value)
    value = _PUNCTUATION.sub(' ', value)
    value = _WHITESPACE.sub(' ', value)
    return value.strip().lower()


def find_existing_item_match(tenant, name='', barcode='', sku=''):
    """
    Returns {'item': Item, 'match_type': 'barcode'|'sku'|'exact'|'fuzzy', 'confidence': float}
    or None if nothing looks like a duplicate.
    """
    qs = Item.objects.for_tenant(tenant)

    barcode = (barcode or '').strip()
    if barcode:
        item = qs.filter(barcode=barcode).first()
        if item:
            return {'item': item, 'match_type': 'barcode', 'confidence': 1.0}

    sku = (sku or '').strip()
    if sku:
        item = qs.filter(sku__iexact=sku).first()
        if item:
            return {'item': item, 'match_type': 'sku', 'confidence': 1.0}

    name_norm = normalize_text(name)
    if not name_norm:
        return None

    active = qs.filter(is_active=True)
    exact = active.filter(name__iexact=name.strip()).first()
    if exact:
        return {'item': exact, 'match_type': 'exact', 'confidence': 1.0}

    prefix = name_norm[:3]
    bucket = active.filter(name__istartswith=prefix) if prefix else active.none()

    best_item, best_ratio = None, 0.0
    for candidate in bucket:
        ratio = difflib.SequenceMatcher(None, name_norm, normalize_text(candidate.name)).ratio()
        if ratio > best_ratio:
            best_item, best_ratio = candidate, ratio

    if best_item and best_ratio >= FUZZY_DUPLICATE_RATIO:
        return {'item': best_item, 'match_type': 'fuzzy', 'confidence': round(best_ratio, 2)}

    return None
