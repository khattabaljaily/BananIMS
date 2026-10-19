"""نسخة المؤسسات: مدير النشاط لا يحدد الكميات الافتتاحية لمخازن الفروع (المركزي وحده)."""
from decimal import Decimal

from django.urls import reverse

from apps.core.models import Branch
from apps.core.test_utils import TenantTestCase, make_item, make_stock
from apps.stocks.models import Stock, StockQuantity


class OwnerCannotSetBranchOpeningTests(TenantTestCase):
    """نسخة المؤسسات: مدير النشاط لا يحدد الكميات الافتتاحية لمخازن الفروع (المركزي وحده)."""
    version_type = 'multi_branch'
    subscription_plan = 'enterprise'

    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(tenant=self.tenant, name='فرع')
        self.branch_stock = make_stock(self.tenant, name='مستودع الشمال', branch=self.branch)
        self.central = Stock.objects.create(tenant=self.tenant, name='المركزي', is_central=True)
        self.item = make_item(self.tenant, name='صنف')

    def _save(self, stock, qty='5'):
        import json
        return self.client.post(reverse('stocks:opening_save_api'), json.dumps(
            {'stock_id': stock.pk, 'rows': [{'item_id': self.item.pk, 'quantity': qty}]}),
            content_type='application/json')

    def test_owner_saving_branch_stock_opening_is_rejected(self):
        resp = self._save(self.branch_stock)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(StockQuantity.objects.get(stock=self.branch_stock, item=self.item).opening_quantity, 0)

    def test_owner_can_still_set_central_stock_opening(self):
        resp = self._save(self.central)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(StockQuantity.objects.get(stock=self.central, item=self.item).opening_quantity, Decimal('5'))

    def test_owner_page_lists_only_central_stocks_and_table_blocks_branch(self):
        page = self.client.get(reverse('stocks:opening_balance_list'))
        self.assertContains(page, 'المركزي')
        self.assertNotContains(page, 'مستودع الشمال')
        resp = self.client.get(reverse('stocks:opening_table_api'), {'stock_id': self.branch_stock.pk})
        self.assertEqual(resp.status_code, 403)

    def test_branch_user_still_sets_own_stock(self):
        from apps.accounts.models import User
        sup = User.objects.create_user(username='op-sup', password='x12345678', tenant=self.tenant,
                                       branch=self.branch, is_branch_supervisor=True)
        self.client.force_login(sup)
        resp = self._save(self.branch_stock)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(StockQuantity.objects.get(stock=self.branch_stock, item=self.item).opening_quantity, Decimal('5'))
