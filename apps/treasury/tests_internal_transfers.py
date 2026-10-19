"""شاشة الخزائن: التحويل داخلي فقط (خزائن الفرع في لوحة الفرع، وخزائن الإدارة في لوحة الإدارة)."""
import json
from decimal import Decimal

from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import Branch
from apps.core.test_utils import TenantTestCase
from apps.treasury.models import Treasury

D = Decimal


class InternalTreasuryTransferTests(TenantTestCase):
    version_type = 'multi_branch'
    subscription_plan = 'enterprise'

    def setUp(self):
        super().setUp()
        self.a = Branch.objects.create(tenant=self.tenant, name='فرع أ')
        self.b = Branch.objects.create(tenant=self.tenant, name='فرع ب')
        self.sup_a = User.objects.create_user(username='it-a', password='x12345678', tenant=self.tenant,
                                              branch=self.a, is_branch_supervisor=True)
        self.ho = Treasury.objects.get(tenant=self.tenant, is_head_office=True)
        self.ho2 = Treasury.objects.create(tenant=self.tenant, name='خزينة إدارة ثانية', is_head_office=True)
        self.a_cash = Treasury.objects.get(tenant=self.tenant, branch=self.a, is_branch_main=True)
        self.a2 = Treasury.objects.create(tenant=self.tenant, name='خزينة فرع أ ثانية', branch=self.a)
        self.b_cash = Treasury.objects.get(tenant=self.tenant, branch=self.b, is_branch_main=True)
        for t in (self.ho, self.ho2, self.a_cash, self.a2, self.b_cash):
            Treasury.objects.filter(pk=t.pk).update(current_balance=D('1000'))

    def transfer(self, user, frm, to, amount='500'):
        self.client.force_login(user)
        return self.client.post('/treasury/api/transfer/', json.dumps({
            'from_treasury': frm.pk, 'to_treasury': to.pk, 'amount': amount,
            'transfer_date': '2026-10-11'}), content_type='application/json')

    def names(self, user):
        self.client.force_login(user)
        resp = self.client.get(reverse('treasury:list'))
        self.assertEqual(resp.status_code, 200)
        return {t['name'] for t in resp.context['transfer_treasuries']}, resp

    def test_owner_dashboard_lists_only_head_office_treasuries(self):
        names, resp = self.names(self.user)
        self.assertEqual(names, {self.ho.name, self.ho2.name})
        self.assertContains(resp, 'خزائن الإدارة المركزية فقط')
        self.assertContains(resp, 'data-require-any-perm="transfer_treasuries,transfer_head_office_treasury"')

    def test_branch_dashboard_lists_only_its_own_treasuries(self):
        names, resp = self.names(self.sup_a)
        self.assertEqual(names, {self.a_cash.name, self.a2.name})
        self.assertContains(resp, 'خزائن فرعك فقط')

    def test_owner_transfers_inside_head_office(self):
        resp = self.transfer(self.user, self.ho, self.ho2)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.ho.refresh_from_db(); self.ho2.refresh_from_db()
        self.assertEqual((self.ho.current_balance, self.ho2.current_balance), (D('500'), D('1500')))

    def test_branch_transfers_inside_its_own_treasuries(self):
        self.assertEqual(self.transfer(self.sup_a, self.a_cash, self.a2).status_code, 200)

    def test_nothing_crosses_between_head_office_and_branches_or_between_branches(self):
        for user, frm, to in ((self.user, self.ho, self.a_cash), (self.sup_a, self.a_cash, self.ho),
                              (self.sup_a, self.a_cash, self.b_cash), (self.user, self.ho2, self.a2)):
            resp = self.transfer(user, frm, to)
            self.assertEqual(resp.status_code, 400, (frm.name, to.name))
        for t in (self.ho, self.ho2, self.a_cash, self.a2, self.b_cash):
            t.refresh_from_db()
            self.assertEqual(t.current_balance, D('1000'))

    def test_owner_cannot_start_a_transfer_from_a_branch_treasury(self):
        self.assertEqual(self.transfer(self.user, self.a_cash, self.a2).status_code, 403)


class SingleStoreTreasuryTransferUnaffectedTests(TenantTestCase):
    def test_page_renders_and_has_no_internal_only_note(self):
        resp = self.client.get(reverse('treasury:list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'خزائن الإدارة المركزية فقط')
