"""
اختبار خطوة التسجيل الثانية (بيانات النشاط) — نوع النشاط لم يعد اختياراً
للمستخدم: يُسند النوع الافتراضي تلقائياً عند إنشاء الحساب، وبيانات الخطوة
الثانية تبقى محفوظة في الجلسة عند العودة إليها.
"""
from django.test import TestCase
from django.urls import reverse

from apps.core.models import BusinessType


class RegisterStep2SessionRoundTripTests(TestCase):
    def setUp(self):
        BusinessType.objects.all().delete()
        self.default_bt = BusinessType.objects.create(
            name='default-bt', name_ar='النوع الافتراضي', slug='default-bt', display_order=1,
        )
        BusinessType.objects.create(
            name='later-bt', name_ar='نوع لاحق', slug='later-bt', display_order=2,
        )

    def _complete_step1(self):
        session = self.client.session
        session['reg_step1'] = {
            'username': 'newowner', 'email': 'owner@example.com',
            'first_name': 'خطاب', 'last_name': 'الجعيلي',
        }
        session.save()

    def test_step2_does_not_ask_for_business_type(self):
        self._complete_step1()
        resp = self.client.get(reverse('accounts:register_step2'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('business_type', resp.context['form'].fields)
        self.assertNotContains(resp, 'name="business_type"')

    def test_step2_data_survives_revisiting_step2(self):
        self._complete_step1()

        resp = self.client.post(reverse('accounts:register_step2'), {
            'business_name': 'معرض الاختبار للإلكترونيات',
            'country': 'الإمارات العربية المتحدة',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload.get('success'), payload)
        self.assertNotIn('business_type_id', self.client.session['reg_step2'])

        resp2 = self.client.get(reverse('accounts:register_step2'))
        self.assertEqual(resp2.status_code, 200)
        form = resp2.context['form']
        self.assertEqual(form['business_name'].value(), 'معرض الاختبار للإلكترونيات')

    def test_default_business_type_is_lowest_display_order(self):
        self.assertEqual(BusinessType.get_default(), self.default_bt)


class RegisterCountryChoiceTests(TestCase):
    """الدولة اختيار إجباري بلا قيمة افتراضية، ومنها تُشتق العملة والمنطقة الزمنية."""

    def setUp(self):
        BusinessType.objects.all().delete()
        BusinessType.objects.create(name='default-bt', name_ar='النوع الافتراضي', slug='default-bt')
        session = self.client.session
        session['reg_step1'] = {
            'username': 'newowner', 'email': 'owner@example.com',
            'password': 'pass12345', 'first_name': 'خطاب', 'last_name': 'الجعيلي',
        }
        session.save()

    def _step2(self, country):
        return self.client.post(reverse('accounts:register_step2'), {
            'business_name': 'معرض الاختبار', 'phone': '+000 000', 'address': 'عنوان',
            'country': country,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_country_is_required_with_empty_placeholder(self):
        resp = self.client.get(reverse('accounts:register_step2'))
        field = resp.context['form'].fields['country']
        self.assertEqual(field.choices[0], ('', 'اختر الدولة'))
        self.assertEqual(self._step2('').status_code, 400)

    def test_tenant_currency_and_timezone_are_derived_from_country(self):
        from apps.core.constants import COUNTRY_CURRENCY_MAP, get_timezone_for_country
        from apps.core.models import Tenant

        country = 'مصر'
        self.assertEqual(self._step2(country).status_code, 200)
        resp = self.client.post(reverse('accounts:register_step3'), {
            'subscription_plan': 'basic',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200, resp.content)
        tenant = Tenant.objects.get(name='معرض الاختبار')
        self.assertEqual(tenant.country, country)
        self.assertEqual(tenant.currency, COUNTRY_CURRENCY_MAP[country])
        self.assertEqual(tenant.timezone, get_timezone_for_country(country))
