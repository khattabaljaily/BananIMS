# الدول المدعومة: تُعرض مرتبة أبجدياً ويُجبَر المشترك على اختيار دولته عند التسجيل (لا دولة افتراضية).
# عملة المشترك = عملة بلده المحلية فقط.
DEFAULT_TIMEZONE = 'UTC'

# ── العملات (المحلية فقط) ──
CURRENCY_AR = {
    'AED': 'د.إ',
    'BHD': 'د.ب',
    'DJF': 'ف.ج',
    'DZD': 'د.ج',
    'EGP': 'ج.م',
    'ILS': '₪',
    'IQD': 'د.ع',
    'JOD': 'د.أ',
    'KMF': 'ف.ق',
    'KWD': 'د.ك',
    'LBP': 'ل.ل',
    'LYD': 'د.ل',
    'MAD': 'د.م',
    'MRU': 'أ.م',
    'OMR': 'ر.ع',
    'QAR': 'ر.ق',
    'SAR': 'ر.س',
    'SDG': 'ج.س',
    'SOS': 'ش.ص',
    'SYP': 'ل.س',
    'TND': 'د.ت',
    'YER': 'ر.ي',
}

CURRENCY_CHOICES = [(code, f'{name} — {code}') for code, name in CURRENCY_AR.items()]

# country name (Arabic) → local currency code
COUNTRY_CURRENCY_MAP = {
    'الأردن': 'JOD',
    'الإمارات العربية المتحدة': 'AED',
    'البحرين': 'BHD',
    'تونس': 'TND',
    'الجزائر': 'DZD',
    'جزر القمر': 'KMF',
    'جيبوتي': 'DJF',
    'السودان': 'SDG',
    'سوريا': 'SYP',
    'الصومال': 'SOS',
    'العراق': 'IQD',
    'عمان': 'OMR',
    'فلسطين': 'ILS',
    'قطر': 'QAR',
    'الكويت': 'KWD',
    'لبنان': 'LBP',
    'ليبيا': 'LYD',
    'مصر': 'EGP',
    'المغرب': 'MAD',
    'المملكة العربية السعودية': 'SAR',
    'موريتانيا': 'MRU',
    'اليمن': 'YER',
}

# IANA timezone → local currency code
TIMEZONE_CURRENCY_MAP = {
    'Asia/Amman': 'JOD',
    'Asia/Dubai': 'AED',
    'Asia/Bahrain': 'BHD',
    'Africa/Tunis': 'TND',
    'Africa/Algiers': 'DZD',
    'Indian/Comoro': 'KMF',
    'Africa/Djibouti': 'DJF',
    'Africa/Khartoum': 'SDG',
    'Asia/Damascus': 'SYP',
    'Africa/Mogadishu': 'SOS',
    'Asia/Baghdad': 'IQD',
    'Asia/Muscat': 'OMR',
    'Asia/Gaza': 'ILS',
    'Asia/Qatar': 'QAR',
    'Asia/Kuwait': 'KWD',
    'Asia/Beirut': 'LBP',
    'Africa/Tripoli': 'LYD',
    'Africa/Cairo': 'EGP',
    'Africa/Casablanca': 'MAD',
    'Asia/Riyadh': 'SAR',
    'Africa/Nouakchott': 'MRU',
    'Asia/Aden': 'YER',
}

COUNTRY_CHOICES = [
    ('الأردن', 'الأردن'),
    ('الإمارات العربية المتحدة', 'الإمارات العربية المتحدة'),
    ('البحرين', 'البحرين'),
    ('تونس', 'تونس'),
    ('الجزائر', 'الجزائر'),
    ('جزر القمر', 'جزر القمر'),
    ('جيبوتي', 'جيبوتي'),
    ('السودان', 'السودان'),
    ('سوريا', 'سوريا'),
    ('الصومال', 'الصومال'),
    ('العراق', 'العراق'),
    ('عمان', 'عمان'),
    ('فلسطين', 'فلسطين'),
    ('قطر', 'قطر'),
    ('الكويت', 'الكويت'),
    ('لبنان', 'لبنان'),
    ('ليبيا', 'ليبيا'),
    ('مصر', 'مصر'),
    ('المغرب', 'المغرب'),
    ('المملكة العربية السعودية', 'المملكة العربية السعودية'),
    ('موريتانيا', 'موريتانيا'),
    ('اليمن', 'اليمن'),
]

COUNTRY_TIMEZONE_MAP = {
    'الأردن': 'Asia/Amman',
    'الإمارات العربية المتحدة': 'Asia/Dubai',
    'البحرين': 'Asia/Bahrain',
    'تونس': 'Africa/Tunis',
    'الجزائر': 'Africa/Algiers',
    'جزر القمر': 'Indian/Comoro',
    'جيبوتي': 'Africa/Djibouti',
    'السودان': 'Africa/Khartoum',
    'سوريا': 'Asia/Damascus',
    'الصومال': 'Africa/Mogadishu',
    'العراق': 'Asia/Baghdad',
    'عمان': 'Asia/Muscat',
    'فلسطين': 'Asia/Gaza',
    'قطر': 'Asia/Qatar',
    'الكويت': 'Asia/Kuwait',
    'لبنان': 'Asia/Beirut',
    'ليبيا': 'Africa/Tripoli',
    'مصر': 'Africa/Cairo',
    'المغرب': 'Africa/Casablanca',
    'المملكة العربية السعودية': 'Asia/Riyadh',
    'موريتانيا': 'Africa/Nouakchott',
    'اليمن': 'Asia/Aden',
}


def get_timezone_for_country(country):
    return COUNTRY_TIMEZONE_MAP.get(str(country).strip(), DEFAULT_TIMEZONE)
