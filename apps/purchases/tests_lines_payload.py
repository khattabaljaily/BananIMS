"""
فاتورة الشراء من الواجهة يجب أن تحفظ الرقم التسلسلي ومعامل الوحدة لكل بند —
كان الـ view يُسقطهما، فلا يُحفظ الرقم التسلسلي، ويُسجَّل الشراء بالكرتونة
كقطعة واحدة في المخزون.
"""
import json
from decimal import Decimal

from apps.core.test_utils import TenantTestCase, make_item, make_supplier
from apps.purchases.models import PurchaseInvoice
from apps.stocks.models import StockQuantity


class PurchaseLinePayloadTests(TenantTestCase):
    def test_serial_and_unit_factor_survive_create_and_confirm(self):
        item = make_item(self.tenant, name='هاتف اختبار', cost_price='1000', selling_price='1500')
        supplier = make_supplier(self.tenant)
        stock = self.default_stock
        payload = {
            'action': 'confirm',
            'header': {'supplier_id': supplier.id, 'stock_id': stock.id, 'payment_method': 'credit',
                       'invoice_date': '2026-10-01'},
            'lines': [{'item_id': item.id, 'quantity': '2', 'unit_cost': '20000', 'tax_rate': '0',
                       'serial_number': 'IMEI-TEST-001', 'unit_factor': '20'}],
        }
        resp = self.client.post('/purchases/create/', data=json.dumps(payload),
                                content_type='application/json', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.assertTrue(resp.json().get('success'), resp.json())

        invoice = PurchaseInvoice.objects.get(tenant=self.tenant)
        line = invoice.lines.get()
        self.assertEqual(invoice.status, 'confirmed')
        self.assertEqual(line.serial_number, 'IMEI-TEST-001')
        self.assertEqual(line.unit_factor, Decimal('20'))
        sq = StockQuantity.objects.get(tenant=self.tenant, stock=stock, item=item)
        self.assertEqual(sq.quantity, Decimal('40'))

    def test_line_unit_matches_selected_item_unit(self):
        from apps.items.models import ItemUnit, Unit
        Unit.objects.create(tenant=self.tenant, name='علبة')  # وحدة أخرى قد يطابق معرّفها معرّف وحدة المنتج
        carton = Unit.objects.create(tenant=self.tenant, name='كرتونة')
        item = make_item(self.tenant, name='شاحن اختبار', cost_price='100', selling_price='150')
        iu = ItemUnit.objects.create(tenant=self.tenant, item=item, name='كرتونة', factor=Decimal('20'))
        supplier = make_supplier(self.tenant)
        payload = {
            'action': 'confirm',
            'header': {'supplier_id': supplier.id, 'stock_id': self.default_stock.id, 'payment_method': 'credit',
                       'invoice_date': '2026-10-01'},
            'lines': [{'item_id': item.id, 'quantity': '1', 'unit_cost': '2000', 'tax_rate': '0',
                       'unit_id': iu.id, 'unit_factor': '20'}],
        }
        resp = self.client.post('/purchases/create/', data=json.dumps(payload),
                                content_type='application/json', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(resp.json().get('success'), resp.json())
        line = PurchaseInvoice.objects.get(tenant=self.tenant).lines.get()
        self.assertEqual(line.unit, carton)
