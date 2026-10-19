"""
اختبار خزينة الإدارة المركزية لنسخة المؤسسات (multi_branch):
  1. الإنشاء التلقائي عند إنشاء الـ tenant وعند ترقيته إلى باقة المؤسسات.
  2. قواعد التحويل: فرع↔إدارة من شاشة الخزينة مرفوض (يتم من «تحويلات الفروع»)، فرع↔فرع
     مباشرة ممنوع، ومدير النشاط لا يبدأ تحويلاً إلا من خزينته هو.
  3. الإلغاء/العكس: يعكس الأرصدة على الطرفين، لا يحذف الحركات الأصلية، يُرفض
     لو التحويل ملغى بالفعل أو لو تعذّر عكس الطرف الآخر لعدم كفاية الرصيد.
"""
import json
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Branch, BusinessType, Tenant
from apps.core.signals import _ensure_head_office_treasuries
from apps.core.test_utils import TenantTestCase
from apps.treasury.models import Treasury, TreasuryTransfer
from apps.treasury.services import cancel_treasury_transfer, post_treasury_transfer


class HeadOfficeTreasuryAutoCreationTests(TestCase):
    def setUp(self):
        self.bt = BusinessType.objects.create(name='bt-hq-tr', name_ar='نوع', slug='bt-hq-tr')
        self.terms = dict(terms_version=settings.TERMS_VERSION, terms_accepted_at=timezone.now())

    def test_enterprise_tenant_creation_creates_head_office_treasury(self):
        tenant = Tenant.objects.create(
            name='HQ Co', business_type=self.bt, subscription_plan='enterprise',
            version_type='multi_branch', currency='EGP', **self.terms,
        )
        hq = list(Treasury.objects.filter(tenant=tenant, is_head_office=True))
        self.assertEqual(len(hq), 1)
        self.assertTrue(all(t.branch_id is None for t in hq))

    def test_upgrading_existing_tenant_to_enterprise_creates_head_office_treasury(self):
        """
        ترقية باقة مشترك موجود إلى 'مؤسسات' (subscription_plan + version_type)
        يجب أن تُنشئ خزينة الإدارة المركزية فوراً (لا تنتظر تشغيل أمر backfill يدوياً).
        """
        tenant = Tenant.objects.create(
            name='Upgrading Co', business_type=self.bt, subscription_plan='basic',
            version_type='single_store', currency='EGP', **self.terms,
        )
        self.assertEqual(Treasury.objects.filter(tenant=tenant, is_head_office=True).count(), 0)

        tenant.subscription_plan = 'enterprise'
        tenant.version_type = 'multi_branch'
        tenant.save()

        self.assertEqual(Treasury.objects.filter(tenant=tenant, is_head_office=True).count(), 1)

    def test_single_store_tenant_gets_no_head_office_treasury(self):
        tenant = Tenant.objects.create(
            name='Single Co', business_type=self.bt, subscription_plan='basic',
            version_type='single_store', currency='EGP', **self.terms,
        )
        self.assertEqual(Treasury.objects.filter(tenant=tenant, is_head_office=True).count(), 0)

    def test_backfill_function_is_idempotent(self):
        tenant = Tenant.objects.create(
            name='HQ Co Backfill', business_type=self.bt, subscription_plan='enterprise',
            version_type='multi_branch', currency='EGP', **self.terms,
        )
        _ensure_head_office_treasuries(tenant)
        _ensure_head_office_treasuries(tenant)
        self.assertEqual(Treasury.objects.filter(tenant=tenant, is_head_office=True).count(), 1)


class HeadOfficeTransferTests(TenantTestCase):
    version_type = 'multi_branch'
    subscription_plan = 'enterprise'

    def setUp(self):
        super().setUp()
        self.branch_a = Branch.objects.create(tenant=self.tenant, name='Branch A')
        self.branch_b = Branch.objects.create(tenant=self.tenant, name='Branch B')

        self.user_a = User.objects.create_user(
            username='sup-a', password='secret123', tenant=self.tenant,
            branch=self.branch_a, is_branch_supervisor=True,
        )
        self.user_b = User.objects.create_user(
            username='sup-b', password='secret123', tenant=self.tenant,
            branch=self.branch_b, is_branch_supervisor=True,
        )

        self.hq_local = Treasury.objects.get(tenant=self.tenant, is_head_office=True)
        self.branch_a_local = Treasury.objects.get(tenant=self.tenant, branch=self.branch_a)
        self.branch_b_local = Treasury.objects.get(tenant=self.tenant, branch=self.branch_b)

        for t in (self.hq_local, self.branch_a_local, self.branch_b_local):
            t.current_balance = Decimal('1000')
            t.save(update_fields=['current_balance'])

    def _transfer(self, from_id, to_id, amount, notes=''):
        return self.client.post(
            '/treasury/api/transfer/',
            data=json.dumps({
                'from_treasury': from_id, 'to_treasury': to_id,
                'amount': str(amount), 'transfer_date': timezone.localdate().isoformat(),
                'notes': notes,
            }),
            content_type='application/json',
        )

    def assert_moved_to_branch_transfers_section(self, resp):
        self.assertEqual(resp.status_code, 400)
        self.assertIn('تحويلات الفروع', resp.json()['message'])
        for t in (self.hq_local, self.branch_a_local):
            t.refresh_from_db()
            self.assertEqual(t.current_balance, Decimal('1000'))  # لم يتحرك شيء

    def test_branch_user_cannot_transfer_to_head_office_from_the_treasury_screen(self):
        """التحويل بين الفرع والإدارة صار حصراً من قسم «تحويلات الفروع» (إرسال ثم تأكيد استلام)."""
        self.client.force_login(self.user_a)
        self.assert_moved_to_branch_transfers_section(self._transfer(self.branch_a_local.id, self.hq_local.id, '100'))

    def test_branch_user_cannot_transfer_directly_to_another_branch(self):
        self.client.force_login(self.user_a)
        resp = self._transfer(self.branch_a_local.id, self.branch_b_local.id, '100')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['success'])
        self.assertIn('مباشر', resp.json()['message'])

    def test_owner_cannot_transfer_from_head_office_to_branch_from_the_treasury_screen(self):
        self.client.force_login(self.user)  # self.user = tenant admin/owner, from TenantTestCase
        self.assert_moved_to_branch_transfers_section(self._transfer(self.hq_local.id, self.branch_a_local.id, '200'))

    def test_owner_cannot_source_transfer_from_a_branch_treasury(self):
        self.client.force_login(self.user)
        resp = self._transfer(self.branch_a_local.id, self.hq_local.id, '50')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()['success'])

class TransferCancelTests(TenantTestCase):
    version_type = 'multi_branch'
    subscription_plan = 'enterprise'

    def setUp(self):
        super().setUp()
        self.branch_a = Branch.objects.create(tenant=self.tenant, name='Branch A')
        self.hq_local = Treasury.objects.get(tenant=self.tenant, is_head_office=True)
        self.branch_a_local = Treasury.objects.get(tenant=self.tenant, branch=self.branch_a)
        self.hq_local.current_balance = Decimal('1000')
        self.hq_local.save(update_fields=['current_balance'])
        self.branch_a_local.current_balance = Decimal('500')
        self.branch_a_local.save(update_fields=['current_balance'])

    def test_cancel_reverses_balances_on_both_sides(self):
        transfer = post_treasury_transfer(
            tenant=self.tenant, from_treasury=self.branch_a_local, to_treasury=self.hq_local,
            amount=Decimal('100'),
            transfer_date=timezone.localdate(), user=self.user,
        )
        self.branch_a_local.refresh_from_db()
        self.hq_local.refresh_from_db()
        self.assertEqual(self.branch_a_local.current_balance, Decimal('400'))
        self.assertEqual(self.hq_local.current_balance, Decimal('1100'))

        cancel_treasury_transfer(transfer, user=self.user)
        self.branch_a_local.refresh_from_db()
        self.hq_local.refresh_from_db()
        self.assertEqual(self.branch_a_local.current_balance, Decimal('500'))
        self.assertEqual(self.hq_local.current_balance, Decimal('1000'))

        transfer.refresh_from_db()
        self.assertTrue(transfer.is_cancelled)
        self.assertIsNotNone(transfer.cancelled_at)
        # الحركتان الأصليتان تبقيان كما هما — لا حذف ولا تعديل، أُضيفت حركتان جديدتان فقط
        self.assertEqual(transfer.from_movement.amount, Decimal('100'))
        self.assertEqual(transfer.to_movement.amount, Decimal('100'))

    def test_double_cancel_is_rejected(self):
        transfer = post_treasury_transfer(
            tenant=self.tenant, from_treasury=self.branch_a_local, to_treasury=self.hq_local,
            amount=Decimal('100'),
            transfer_date=timezone.localdate(), user=self.user,
        )
        cancel_treasury_transfer(transfer, user=self.user)
        with self.assertRaises(ValueError):
            cancel_treasury_transfer(transfer, user=self.user)

    def test_cancel_fails_gracefully_if_destination_already_spent(self):
        transfer = post_treasury_transfer(
            tenant=self.tenant, from_treasury=self.branch_a_local, to_treasury=self.hq_local,
            amount=Decimal('100'),
            transfer_date=timezone.localdate(), user=self.user,
        )
        # يُصرف كل رصيد الإدارة المركزية (1100) في مكان آخر قبل محاولة الإلغاء
        self.hq_local.current_balance = Decimal('0')
        self.hq_local.save(update_fields=['current_balance'])

        with self.assertRaises(ValueError):
            cancel_treasury_transfer(transfer, user=self.user)
        transfer.refresh_from_db()
        self.assertFalse(transfer.is_cancelled)

    def test_cancel_api_respects_branch_ownership(self):
        other_branch = Branch.objects.create(tenant=self.tenant, name='Branch C')
        outsider = User.objects.create_user(
            username='outsider', password='secret123', tenant=self.tenant,
            branch=other_branch, is_branch_supervisor=True,
        )
        transfer = post_treasury_transfer(
            tenant=self.tenant, from_treasury=self.branch_a_local, to_treasury=self.hq_local,
            amount=Decimal('100'),
            transfer_date=timezone.localdate(), user=self.user,
        )
        self.client.force_login(outsider)
        resp = self.client.post(f'/treasury/api/transfer/{transfer.id}/cancel/')
        self.assertEqual(resp.status_code, 404)

        self.client.force_login(self.user)  # owner: request.branch=None, enforce_branch_ownership no-ops
        resp = self.client.post(f'/treasury/api/transfer/{transfer.id}/cancel/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
