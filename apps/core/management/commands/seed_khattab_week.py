"""
seed_khattab_week — يُدخل بيانات كثيرة في مشترك المستخدم khattab الحالي،
موزعة على تواريخ متعددة خلال الأسبوع الماضي، لأغراض التقاط لقطات الشاشة.

الاستخدام:
    python manage.py seed_khattab_week
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

random.seed(42)

# (name, category_idx, cost, sell, purchase_qty)
ITEMS_DATA = [
    ('لاب توب Dell XPS 15',    0,  2800, 3500,  30),
    ('تلفاز Samsung 55 بوصة',  0,  3200, 4200,  25),
    ('جوال iPhone 15 Pro',     0,  5500, 6800,  20),
    ('سماعات Sony WH-1000',    0,   450,  650,  60),
    ('طابعة HP LaserJet',      0,   980, 1300,  15),
    ('قميص قطني رجالي',        1,    55,   95, 120),
    ('فستان حريمي كاجوال',     1,    80,  145, 100),
    ('بنطلون جينز',             1,    65,  120,  80),
    ('جاكيت شتوي',              1,   120,  220,  70),
    ('حذاء رياضي نايك',         1,   180,  320,  50),
    ('أرز بسمتي 25 كيلو',      2,  1.80, 2.80, 500),
    ('زيت عباد الشمس 5 لتر',   2,  4.20, 6.50, 300),
    ('سكر أبيض كيلو',           2,  1.50, 2.20, 600),
    ('شاي أحمر علبة 250g',      2, 18.0, 28.0, 200),
    ('معجون طماطم 800g',        2, 12.0, 20.0, 250),
    ('حقيبة جلد يد',            3,    95,  180,  80),
    ('ساعة كاسيو G-Shock',      3,   350,  550,  40),
    ('نظارة شمسية Ray-Ban',     3,   250,  420,  60),
    ('حزام جلدي رجالي',         3,    45,   85,  90),
    ('محفظة جلد',               3,    60,  110, 100),
]

CUSTOMERS_DATA = [
    ('شركة الأمل للمقاولات',   '0912111222', 'الخرطوم',   20000),
    ('مؤسسة البركة التجارية',  '0922333444', 'أمدرمان',   15000),
    ('محلات النور',            '0933555666', 'بحري',       5000),
    ('أحمد إبراهيم سعيد',      '0944777888', 'الخرطوم',       0),
    ('شركة الخليج للتوزيع',    '0955999000', 'شرق النيل', 30000),
    ('مريم عبدالله كرم',       '0966111333', 'أمدرمان',       0),
    ('محمد الحسن آدم',         '0977222444', 'بحري',          0),
    ('شركة النيل الأزرق',      '0988333555', 'الخرطوم',   10000),
    ('فاطمة الزهراء',          '0999444666', 'أمدرمان',       0),
    ('مؤسسة الفجر الجديد',     '0910555777', 'شرق النيل',  8000),
]

SUPPLIERS_DATA = [
    ('شركة التقنية الحديثة',      '0911222333', 'الخرطوم'),
    ('مصنع النسيج السوداني',      '0922444555', 'شندي'),
    ('مجموعة الغذاء والتجارة',    '0933666777', 'أمدرمان'),
    ('موردو الإكسسوارات الدولية', '0944888999', 'الخرطوم'),
    ('شركة الاستيراد الشامل',     '0955000111', 'بورتسودان'),
    ('مؤسسة التوريد السريع',      '0966111222', 'الخرطوم'),
]

PAYMENT_METHODS = ['cash', 'cash', 'cash', 'credit', 'bank']


class Command(BaseCommand):
    help = 'يُدخل بيانات كثيرة في مشترك khattab موزعة على أيام الأسبوع الماضي (للقطات الشاشة)'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='khattab', help='اسم المستخدم صاحب المشترك')

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            user = User.objects.get(username=options['username'])
        except User.DoesNotExist:
            raise CommandError(f"لا يوجد مستخدم باسم {options['username']}")

        tenant = user.tenant
        if not tenant:
            raise CommandError('هذا المستخدم غير مرتبط بأي مشترك')

        from apps.items.models import Item
        if Item.objects.filter(tenant=tenant).exists():
            self.stdout.write(self.style.WARNING(
                'المشترك يحتوي بيانات أصناف بالفعل — سيتم المتابعة وإضافة بيانات جديدة فوقها.'
            ))

        self.stdout.write(f'⏳ جاري إدخال البيانات لمشترك: {tenant.name} ...')

        with transaction.atomic():
            stock = self._get_stock(tenant, user)
            treasury = self._get_treasury(tenant, user)
            categories = self._create_categories(tenant, user)
            units = self._create_units(tenant, user)
            items = self._create_items(tenant, user, categories, units)
            customers = self._create_customers(tenant, user)
            suppliers = self._create_suppliers(tenant, user)
            self._create_purchases(tenant, user, stock, suppliers, items)
            self._create_sales(tenant, user, stock, customers, items)
            self._create_expenses(tenant, user, treasury)
            self._create_employees(tenant, user, treasury)
            self._create_store(tenant, items)
            self._create_notifications(tenant, user)

        self.stdout.write(self.style.SUCCESS(f'✅ اكتمل إدخال البيانات لمشترك {tenant.name}!'))

    # ── مخزن + خزينة موجودان مسبقاً ───────────────────────────────────────
    def _get_stock(self, tenant, user):
        from apps.stocks.models import Stock
        stock = Stock.objects.filter(tenant=tenant, is_active=True).order_by('id').first()
        if not stock:
            stock = Stock.objects.create(
                tenant=tenant, name='المخزن الرئيسي', code='WH-MAIN',
                stock_type='main', is_default=True, is_active=True, created_by=user,
            )
        self.stdout.write(f'  ✓ مخزن: {stock.name}')
        return stock

    def _get_treasury(self, tenant, user):
        from apps.treasury.models import Treasury
        from apps.treasury.services import post_treasury_receipt
        treasury = Treasury.objects.filter(tenant=tenant, is_default=True).order_by('id').first()
        if not treasury:
            treasury = Treasury.objects.create(
                tenant=tenant, name='الخزينة الرئيسية', code='TR-MAIN',
                is_default=True, is_system_default=True, current_balance=Decimal('0'),
                created_by=user,
            )
        if treasury.current_balance == 0:
            post_treasury_receipt(
                tenant=tenant, amount=Decimal('50000'),
                date=date.today() - timedelta(days=14),
                reference_type='opening_balance',
                description='رصيد افتتاحي',
                treasury=treasury,
            )
        self.stdout.write(f'  ✓ خزينة: {treasury.name}')
        return treasury

    # ── تصنيفات ووحدات ─────────────────────────────────────────────────────
    def _create_categories(self, tenant, user):
        from apps.items.models import Category
        names = ['إلكترونيات', 'ملابس وأزياء', 'مواد غذائية', 'إكسسوارات']
        cats = []
        for n in names:
            cat, _ = Category.objects.get_or_create(
                tenant=tenant, name=n, defaults=dict(is_active=True, created_by=user),
            )
            cats.append(cat)
        self.stdout.write(f'  ✓ تصنيفات: {len(cats)}')
        return cats

    def _create_units(self, tenant, user):
        from apps.items.models import Unit
        data = [('قطعة', 'PCS'), ('كيلو', 'KG'), ('لتر', 'LTR'), ('متر', 'MTR')]
        units = []
        for n, a in data:
            unit, _ = Unit.objects.get_or_create(
                tenant=tenant, name=n,
                defaults=dict(abbreviation=a, conversion_factor=Decimal('1'),
                               is_active=True, created_by=user),
            )
            units.append(unit)
        self.stdout.write(f'  ✓ وحدات: {len(units)}')
        return units

    # ── أصناف ──────────────────────────────────────────────────────────────
    def _create_items(self, tenant, user, categories, units):
        from apps.items.models import Item
        items = []
        for idx, (name, cat_idx, cost, sell, _) in enumerate(ITEMS_DATA):
            unit = units[1] if cat_idx == 2 else units[0]
            sku = f'SKU-{idx + 1:03d}'
            item, created = Item.objects.get_or_create(
                tenant=tenant, sku=sku,
                defaults=dict(
                    name=name, category=categories[cat_idx], unit=unit,
                    item_type='product',
                    cost_price=Decimal(str(cost)), selling_price=Decimal(str(sell)),
                    is_active=True, is_sellable=True, is_purchasable=True,
                    created_by=user,
                ),
            )
            items.append(item)
        self.stdout.write(f'  ✓ أصناف: {len(items)}')
        return items

    # ── عملاء وموردون ──────────────────────────────────────────────────────
    def _create_customers(self, tenant, user):
        from apps.customers.models import Customer
        customers = []
        for n, p, c, cl in CUSTOMERS_DATA:
            cust, _ = Customer.objects.get_or_create(
                tenant=tenant, name=n,
                defaults=dict(phone=p, city=c, credit_limit=Decimal(str(cl)), created_by=user),
            )
            customers.append(cust)
        self.stdout.write(f'  ✓ عملاء: {len(customers)}')
        return customers

    def _create_suppliers(self, tenant, user):
        from apps.suppliers.models import Supplier
        suppliers = []
        for n, p, c in SUPPLIERS_DATA:
            sup, _ = Supplier.objects.get_or_create(
                tenant=tenant, name=n, defaults=dict(phone=p, city=c, created_by=user),
            )
            suppliers.append(sup)
        self.stdout.write(f'  ✓ موردون: {len(suppliers)}')
        return suppliers

    # ── فواتير شراء (لتخزين كميات كافية قبل أسبوع البيع) ────────────────
    def _create_purchases(self, tenant, user, stock, suppliers, items):
        from apps.purchases.models import PurchaseInvoice, PurchaseInvoiceLine
        from apps.purchases.services import confirm_purchase_invoice

        today = date.today()
        batches = [
            (13, 0, [0, 1, 2, 3, 4]),
            (12, 1, [5, 6, 7, 8, 9]),
            (11, 2, [10, 11, 12, 13, 14]),
            (10, 3, [15, 16, 17, 18, 19]),
            (9,  4, [0, 5, 10, 15]),
            (8,  5, [1, 6, 11, 16]),
        ]

        confirmed = 0
        for days_ago, sup_idx, item_indices in batches:
            invoice = PurchaseInvoice(
                tenant=tenant, supplier=suppliers[sup_idx], stock=stock,
                invoice_date=today - timedelta(days=days_ago),
                status='draft', payment_method='credit', created_by=user,
            )
            invoice.save()
            subtotal = Decimal('0')
            for i in item_indices:
                name, cat_idx, cost, sell, base_qty = ITEMS_DATA[i]
                qty = base_qty
                line_total = Decimal(str(cost)) * qty
                subtotal += line_total
                PurchaseInvoiceLine.objects.create(
                    tenant=tenant, invoice=invoice,
                    item=items[i], quantity=Decimal(str(qty)),
                    unit_cost=Decimal(str(cost)),
                    line_total=line_total, created_by=user,
                )
            invoice.subtotal = subtotal
            invoice.grand_total = subtotal
            invoice.save(update_fields=['subtotal', 'grand_total'])
            try:
                confirm_purchase_invoice(invoice, user)
                confirmed += 1
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'    ⚠ شراء: {e}'))

        self.stdout.write(f'  ✓ فواتير شراء: {confirmed}/{len(batches)}')

    # ── فواتير بيع موزعة على كل يوم من الأسبوع الماضي ──────────────────
    def _create_sales(self, tenant, user, stock, customers, items):
        from apps.sales.models import SaleInvoice, SaleInvoiceLine
        from apps.sales.services import confirm_sale_invoice

        today = date.today()
        confirmed = 0
        total_invoices = 0

        for days_ago in range(6, -1, -1):
            invoice_date = today - timedelta(days=days_ago)
            n_invoices = random.randint(4, 6)
            for _ in range(n_invoices):
                total_invoices += 1
                use_customer = random.random() < 0.7
                customer = random.choice(customers) if use_customer else None
                payment = random.choice(PAYMENT_METHODS) if customer else random.choice(['cash', 'bank'])

                n_lines = random.randint(1, 3)
                chosen_idx = random.sample(range(len(items)), n_lines)

                invoice = SaleInvoice(
                    tenant=tenant, customer=customer, stock=stock,
                    invoice_date=invoice_date,
                    status='draft', payment_method=payment,
                    delivery_type='immediate', created_by=user,
                )
                invoice.save()
                subtotal = Decimal('0')
                for item_idx in chosen_idx:
                    name, cat_idx, cost, sell, base_qty = ITEMS_DATA[item_idx]
                    max_qty = max(1, min(5, base_qty // 10))
                    qty = random.randint(1, max_qty)
                    price = Decimal(str(sell))
                    cost_d = Decimal(str(cost))
                    line_total = price * qty
                    subtotal += line_total
                    SaleInvoiceLine.objects.create(
                        tenant=tenant, invoice=invoice,
                        item=items[item_idx],
                        quantity=Decimal(str(qty)),
                        unit_price=price,
                        cost_price_snapshot=cost_d,
                        discount_amount=Decimal('0'),
                        line_total=line_total,
                        created_by=user,
                    )
                invoice.subtotal = subtotal
                invoice.grand_total = subtotal
                invoice.save(update_fields=['subtotal', 'grand_total'])
                try:
                    confirm_sale_invoice(invoice, user)
                    confirmed += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'    ⚠ بيع ({invoice_date}): {e}'))

        self.stdout.write(f'  ✓ فواتير بيع: {confirmed}/{total_invoices} (موزعة على 7 أيام)')

    # ── مصروفات موزعة على أيام الأسبوع ─────────────────────────────────
    def _create_expenses(self, tenant, user, treasury):
        from apps.expenses.models import ExpenseCategory, Expense
        from apps.expenses.services import confirm_expense

        cat_names = ['إيجار', 'كهرباء وماء', 'مواصلات', 'صيانة', 'متنوع']
        cats = {}
        for name in cat_names:
            cat, _ = ExpenseCategory.objects.get_or_create(
                tenant=tenant, name=name, defaults=dict(created_by=user),
            )
            cats[name] = cat

        descriptions = [
            ('كهرباء وماء', 'فاتورة كهرباء', 480),
            ('مواصلات', 'بنزين ومواصلات', 200),
            ('صيانة', 'صيانة أجهزة', 350),
            ('متنوع', 'مستلزمات مكتبية', 150),
            ('مواصلات', 'أجرة توصيل بضاعة', 120),
            ('كهرباء وماء', 'فاتورة مياه', 150),
            ('متنوع', 'ضيافة عملاء', 90),
        ]

        today = date.today()
        count = 0
        for days_ago in range(6, -1, -1):
            exp_date = today - timedelta(days=days_ago)
            cat_name, desc, amount = descriptions[days_ago]
            exp = Expense.objects.create(
                tenant=tenant, category=cats[cat_name], description=desc,
                amount=Decimal(str(amount)), expense_date=exp_date,
                payment_method='cash', treasury=treasury,
                status='draft', created_by=user,
            )
            try:
                confirm_expense(exp, user)
                count += 1
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'    ⚠ مصروف: {e}'))

        # إيجار الشهر (مصروف كبير أول الأسبوع)
        exp = Expense.objects.create(
            tenant=tenant, category=cats['إيجار'], description='إيجار المحل الشهري',
            amount=Decimal('4500'), expense_date=today - timedelta(days=6),
            payment_method='bank', treasury=treasury,
            status='draft', created_by=user,
        )
        try:
            confirm_expense(exp, user)
            count += 1
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'    ⚠ مصروف: {e}'))

        self.stdout.write(f'  ✓ مصروفات: {count}')

    # ── موظفون ─────────────────────────────────────────────────────────────
    def _create_employees(self, tenant, user, treasury):
        from apps.employees.models import Employee, EmployeeAdvance, EmployeeSalaryPayment

        today = date.today()
        emp_data = [
            ('محمد أحمد علي', 'مدير المبيعات', 'المبيعات', 'fixed', 3500),
            ('فاطمة إبراهيم', 'محاسبة', 'المحاسبة', 'fixed', 2800),
            ('خالد عبدالله', 'مسؤول المخزن', 'المخزن', 'fixed', 2200),
            ('سارة يوسف', 'موظفة مبيعات', 'المبيعات', 'fixed', 1800),
        ]
        count = 0
        for i, (name, pos, dept, stype, salary) in enumerate(emp_data):
            emp, created = Employee.objects.get_or_create(
                tenant=tenant, name=name,
                defaults=dict(
                    position=pos, department=dept, salary_type=stype,
                    base_salary=Decimal(str(salary)),
                    hire_date=today - timedelta(days=random.randint(90, 365)),
                    is_active=True, created_by=user,
                ),
            )
            if not created:
                continue
            EmployeeAdvance.objects.create(
                tenant=tenant, employee=emp,
                amount=Decimal(str(random.randint(200, 400))),
                date=today - timedelta(days=i + 1),
                payment_method='cash', treasury=treasury,
                status='pending', created_by=user,
            )
            period_start = date(today.year, today.month, 1) - timedelta(days=30)
            period_start = date(period_start.year, period_start.month, 1)
            period_end = date(today.year, today.month, 1) - timedelta(days=1)
            EmployeeSalaryPayment.objects.create(
                tenant=tenant, employee=emp,
                period_start=period_start, period_end=period_end,
                base_salary=emp.base_salary, bonus=Decimal('100'),
                advances_deducted=Decimal('0'), deductions=Decimal('0'),
                payment_method='cash', treasury=treasury,
                status='paid', created_by=user,
            )
            count += 1
        self.stdout.write(f'  ✓ موظفون: {count} (مع سلف ورواتب)')

    # ── متجر إلكتروني وطلبات ────────────────────────────────────────────
    def _create_store(self, tenant, items):
        from apps.store.models import StoreSettings, OnlineOrder, OnlineOrderLine

        store, _ = StoreSettings.objects.get_or_create(
            tenant=tenant,
            defaults=dict(
                is_enabled=True, display_name=tenant.name,
                description='أفضل المنتجات بأفضل الأسعار',
                accent_color='#132539', show_prices=True,
                show_stock_quantity=False, status_override='open',
            ),
        )

        today = date.today()
        statuses = ['pending', 'approved', 'pending', 'delivered']
        count = 0
        for i, status in enumerate(statuses):
            item = items[i * 4]
            qty = Decimal('2')
            order = OnlineOrder.objects.create(
                tenant=tenant, store=store,
                customer_name=f'عميل أونلاين {i + 1}',
                customer_phone=f'091{i}000111',
                payment_method='bank', status=status,
                subtotal=item.selling_price * qty,
                total_amount=item.selling_price * qty,
            )
            OnlineOrderLine.objects.create(
                tenant=tenant, order=order, item=item,
                item_name=item.name, unit_price=item.selling_price,
                quantity=qty,
            )
            count += 1
        self.stdout.write(f'  ✓ متجر إلكتروني: {count} طلبات')

    # ── إشعارات ────────────────────────────────────────────────────────────
    def _create_notifications(self, tenant, user):
        from apps.notifications.models import Notification
        data = [
            ('low_stock', 'high', 'تنبيه مخزون منخفض', 'الصنف «سماعات Sony WH-1000» وصل للحد الأدنى'),
            ('online_order', 'high', 'طلب جديد من المتجر', 'طلب جديد بقيمة تستحق المراجعة'),
            ('overdue_invoice', 'medium', 'فاتورة متأخرة السداد', 'إحدى الفواتير الآجلة تجاوزت موعد السداد'),
            ('transfer_done', 'low', 'تم تحديث المخزون', 'تمت مراجعة أرصدة المخزون بنجاح'),
            ('general', 'low', 'مرحباً في بنان IMS', 'حسابك جاهز — تابع أداءك من لوحة التحكم'),
            ('general', 'medium', 'تقرير أسبوعي جاهز', 'تقرير المبيعات الأسبوعي أصبح متاحاً للمراجعة'),
        ]
        count = 0
        for ntype, priority, title, msg in data:
            Notification.objects.create(
                tenant=tenant, user=user, notification_type=ntype,
                priority=priority, title=title, message=msg, is_read=False,
            )
            count += 1
        self.stdout.write(f'  ✓ إشعارات: {count}')
