"""
صفحة «استيراد البيانات» الموحّدة: التصنيفات، المنتجات، العملاء، الموردون، المناديب.
شاشات القوائم نفسها لا تحمل أي زر/نافذة استيراد (التصدير فقط).
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.test_utils import TenantTestCase
from apps.items.models import Category


class HubCardsTests(TenantTestCase):
    subscription_plan = 'pro'

    def _hub(self):
        return self.client.get(reverse('data_import:hub'))

    def test_hub_lists_all_five_in_order(self):
        self.tenant.capabilities.has_agents_module = True
        self.tenant.capabilities.save()
        html = self._hub().content.decode()
        order = [html.find(t) for t in (
            'استيراد التصنيفات', 'استيراد المنتجات', 'استيراد العملاء', 'استيراد الموردين', 'استيراد المناديب')]
        self.assertTrue(all(i > 0 for i in order), order)
        self.assertEqual(order, sorted(order))

    def test_agents_card_hidden_without_agents_module(self):
        self.tenant.capabilities.has_agents_module = False
        self.tenant.capabilities.save()
        self.assertNotContains(self._hub(), 'استيراد المناديب')
        self.assertNotEqual(self.client.get(reverse('data_import:agent_page')).status_code, 200)


class BasicPlanAgentsTests(TenantTestCase):
    subscription_plan = 'basic'

    def test_agents_hidden_on_basic_plan(self):
        self.assertNotContains(self.client.get(reverse('data_import:hub')), 'استيراد المناديب')
        self.assertNotEqual(self.client.get(reverse('data_import:agent_page')).status_code, 200)


class ListScreensHaveNoImportTests(TenantTestCase):
    subscription_plan = 'pro'

    def test_category_and_agent_lists_have_no_import_ui(self):
        self.tenant.capabilities.has_agents_module = True
        self.tenant.capabilities.save()
        cats = self.client.get(reverse('items:category_list'))
        self.assertNotContains(cats, 'importCategoriesModal')
        self.assertNotContains(cats, 'btnOpenImportCategories')
        self.assertContains(cats, 'export_categories')
        agents = self.client.get(reverse('agents:list'))
        self.assertNotContains(agents, 'importAgentsModal')
        self.assertContains(agents, 'btnExportAgents')


class ImportCommitTests(TenantTestCase):
    subscription_plan = 'pro'

    def test_category_import_through_hub_page(self):
        page = self.client.get(reverse('data_import:category_page'))
        self.assertContains(page, reverse('items:category_import_api'))
        csv = 'الاسم,التصنيف الرئيسي\nمشروبات,\nعصائر,مشروبات\n'.encode('utf-8')
        resp = self.client.post(reverse('items:category_import_api'),
                                {'file': SimpleUploadedFile('c.csv', csv)})
        self.assertEqual(resp.json()['imported'], 2)
        self.assertEqual(Category.objects.get(tenant=self.tenant, name='عصائر').parent.name, 'مشروبات')

    def test_agent_import_through_hub_page(self):
        self.tenant.capabilities.has_agents_module = True
        self.tenant.capabilities.save()
        page = self.client.get(reverse('data_import:agent_page'))
        self.assertContains(page, reverse('agents:import_api'))
        csv = 'الاسم,الهاتف\nأحمد,0912345678\n'.encode('utf-8')
        resp = self.client.post(reverse('agents:import_api'), {'file': SimpleUploadedFile('a.csv', csv)})
        self.assertEqual(resp.json()['imported'], 1)


class SidebarPlacementTests(TenantTestCase):
    subscription_plan = 'pro'

    def test_import_link_is_top_level_item_after_settings(self):
        html = self.client.get(reverse('data_import:hub')).content.decode()
        settings_at = html.index('الإعدادات')
        import_at = html.index('استيراد البيانات', settings_at)
        # قائمة المنتجات تأتي بعد الإعدادات؛ رابط الاستيراد يجب أن يسبقها
        products_at = html.index('>\n                المنتجات', settings_at)
        self.assertLess(settings_at, import_at)
        self.assertLess(import_at, products_at)
        # قائمة الإعدادات تُغلق قبل عنصر الاستيراد: هو عنصر رئيسي مستقل لا فرعي داخلها
        self.assertLess(html.index('</ul>', settings_at), import_at)


class ImportRequiresAddPermissionTests(TenantTestCase):
    """الاستيراد يتطلب صلاحية الاستيراد وصلاحية الإضافة معًا لكل نوع بيانات."""
    subscription_plan = 'pro'

    PAGES = {
        'items': ('data_import:product_page', 'استيراد المنتجات'),
        'customers': ('data_import:customer_page', 'استيراد العملاء'),
        'suppliers': ('data_import:supplier_page', 'استيراد الموردين'),
        'agents': ('data_import:agent_page', 'استيراد المناديب'),
    }

    def _user(self, perms):
        from apps.accounts.models import PermissionGroup, User
        self.tenant.capabilities.has_agents_module = True
        self.tenant.capabilities.save()
        group = PermissionGroup.objects.create(
            tenant=self.tenant, name='g-' + '-'.join(sorted(perms)), is_active=True,
            permissions={k: True for k in perms} | {'view_items': True})
        user = User.objects.create_user(username='u-' + str(len(perms)) + str(abs(hash(tuple(sorted(perms))))),
                                        password='x12345678', tenant=self.tenant)
        user.permission_groups.add(group)
        self.client.force_login(user)
        return user

    def test_import_without_add_is_denied_and_hidden(self):
        for kind, (url_name, label) in self.PAGES.items():
            with self.subTest(kind=kind):
                self._user({f'import_{kind}'})
                self.assertNotEqual(self.client.get(reverse(url_name)).status_code, 200)
                self.assertNotContains(self.client.get(reverse('data_import:hub')), label)

    def test_add_without_import_is_denied_and_hidden(self):
        for kind, (url_name, label) in self.PAGES.items():
            with self.subTest(kind=kind):
                self._user({f'add_{kind}'})
                self.assertNotEqual(self.client.get(reverse(url_name)).status_code, 200)

    def test_import_with_add_is_allowed(self):
        for kind, (url_name, label) in self.PAGES.items():
            with self.subTest(kind=kind):
                self._user({f'import_{kind}', f'add_{kind}'})
                self.assertEqual(self.client.get(reverse(url_name)).status_code, 200)
                self.assertContains(self.client.get(reverse('data_import:hub')), label)

    def test_categories_follow_add_categories_only(self):
        self._user({'add_categories'})
        self.assertEqual(self.client.get(reverse('data_import:category_page')).status_code, 200)
        self._user({'view_categories'})
        self.assertNotEqual(self.client.get(reverse('data_import:category_page')).status_code, 200)

    def test_agent_api_also_needs_add_agents(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self._user({'import_agents'})
        csv = 'الاسم\nأحمد\n'.encode('utf-8')
        resp = self.client.post(reverse('agents:import_api'), {'file': SimpleUploadedFile('a.csv', csv)})
        self.assertNotEqual(resp.status_code, 200)


