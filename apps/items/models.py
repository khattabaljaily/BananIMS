"""
Items Models - نماذج المنتجات والأصناف
التصنيفات، المنتجات، الوحدات وعوامل التحويل.
"""
from django.db import models
from django.utils.text import slugify
from apps.core.models import TenantMixin


# ============================================
# CATEGORY (تصنيفات المنتجات)
# ============================================

class Category(TenantMixin):
    """
    تصنيف هرمي للمنتجات (Parent → Children).
    مثال: إلكترونيات → هواتف ذكية → سامسونج
    """

    name = models.CharField('اسم التصنيف', max_length=200)
    slug = models.SlugField('الرمز', max_length=220, blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='children',
        verbose_name='التصنيف الرئيسي'
    )
    icon = models.CharField('الأيقونة', max_length=50, blank=True, default='fa-tag')
    description = models.TextField('الوصف', blank=True)
    is_active = models.BooleanField('نشط', default=True)
    display_order = models.IntegerField('ترتيب العرض', default=0)

    class Meta:
        db_table = 'item_categories'
        verbose_name = 'تصنيف'
        verbose_name_plural = 'التصنيفات'
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
            models.Index(fields=['tenant', 'parent']),
        ]

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} › {self.name}"
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or f"cat-{self.tenant_id}"
            self.slug = f"{self.tenant_id}-{base_slug}"
        super().save(*args, **kwargs)

    @property
    def full_path(self):
        """المسار الكامل: الجد > الأب > الابن"""
        parts = [self.name]
        parent = self.parent
        while parent:
            parts.insert(0, parent.name)
            parent = parent.parent
        return ' › '.join(parts)

    @property
    def is_root(self):
        return self.parent is None


# ============================================
# UNIT (وحدات القياس)
# ============================================

class Unit(TenantMixin):
    """
    وحدة قياس المنتج.
    مثال: قطعة، كرتون (12 قطعة)، كيلوجرام، لتر
    يدعم الوحدات المتداخلة: وحدة أساسية + وحدة تعبئة
    """

    name = models.CharField('اسم الوحدة', max_length=100)
    abbreviation = models.CharField('الاختصار', max_length=20, blank=True)
    # للوحدات المركبة: كرتون = 12 قطعة
    base_unit = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sub_units',
        verbose_name='الوحدة الأساسية'
    )
    conversion_factor = models.DecimalField(
        'عامل التحويل', max_digits=10, decimal_places=4, default=1,
        help_text='كم وحدة أساسية تُعادل هذه الوحدة؟ مثال: كرتون = 12 قطعة'
    )
    is_active = models.BooleanField('نشط', default=True)

    class Meta:
        db_table = 'item_units'
        verbose_name = 'وحدة قياس'
        verbose_name_plural = 'وحدات القياس'
        ordering = ['name']
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
        ]

    def __str__(self):
        if self.abbreviation:
            return f"{self.name} ({self.abbreviation})"
        return self.name


# ============================================
# ITEM (المنتج / الصنف)
# ============================================

class Item(TenantMixin):
    """
    المنتج أو الصنف الأساسي في المخزون.

    track_serial: تتبع رقم تسلسلي لكل وحدة مباعة أو مشتراة.
    """

    ITEM_TYPE_CHOICES = (
        ('product', 'منتج'),
        ('service', 'خدمة'),
    )

    # ------ معلومات أساسية ------
    name = models.CharField('اسم المنتج', max_length=300)
    name_en = models.CharField('الاسم بالإنجليزية', max_length=300, blank=True)
    sku = models.CharField('رمز المنتج (SKU)', max_length=100, blank=True)
    barcode = models.CharField('الباركود', max_length=100, blank=True)
    item_type = models.CharField(
        'نوع الصنف', max_length=20,
        choices=ITEM_TYPE_CHOICES, default='product'
    )

    # ------ التصنيف والوحدة ------
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='items',
        verbose_name='التصنيف'
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='items',
        verbose_name='وحدة البيع'
    )
    purchase_unit = models.ForeignKey(
        Unit,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='purchase_items',
        verbose_name='وحدة الشراء'
    )
    has_multiple_units = models.BooleanField('وحدات متعددة', default=False)
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='supplied_items',
        verbose_name='الشركة الموردة',
        help_text='الشركة/المورد الذي يوفر هذا الصنف — يُستخدم للتصفية، وهو غير الشركة المصنعة'
    )

    # ------ التسعير ------
    cost_price = models.DecimalField(
        'سعر التكلفة', max_digits=14, decimal_places=2, default=0
    )
    selling_price = models.DecimalField(
        'سعر البيع', max_digits=14, decimal_places=2, default=0
    )
    min_selling_price = models.DecimalField(
        'الحد الأدنى للسعر', max_digits=14, decimal_places=2, default=0,
        help_text='أقل سعر يُسمح بالبيع به'
    )

    tax_rate = models.DecimalField(
        'نسبة الضريبة %', max_digits=5, decimal_places=2, default=0
    )

    # ------ المخزون ------
    min_quantity = models.DecimalField(
        'الحد الأدنى للمخزون', max_digits=12, decimal_places=4, default=0,
        help_text='يُنبّه عند الوصول لهذه الكمية'
    )
    max_quantity = models.DecimalField(
        'الحد الأقصى للمخزون', max_digits=12, decimal_places=4, default=0
    )

    # ------ خيارات التتبع ------
    track_serial = models.BooleanField(
        'تتبع الرقم التسلسلي', default=False
    )

    # ------ بيانات المصدر ------
    manufacturer = models.CharField('الشركة المصنعة', max_length=200, blank=True)
    country_of_origin = models.CharField('بلد المنشأ', max_length=100, blank=True)

    # ------ تفاصيل إضافية ------
    description = models.TextField('الوصف', blank=True)
    image = models.ImageField(
        'صورة المنتج', upload_to='items/', blank=True, null=True
    )
    is_active = models.BooleanField('نشط', default=True)
    is_sellable = models.BooleanField('قابل للبيع', default=True)
    is_purchasable = models.BooleanField('قابل للشراء', default=True)

    class Meta:
        db_table = 'items'
        verbose_name = 'منتج'
        verbose_name_plural = 'المنتجات'
        ordering = ['name']
        unique_together = [('tenant', 'sku')]
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
            models.Index(fields=['tenant', 'barcode']),
            models.Index(fields=['tenant', 'category']),
            models.Index(fields=['tenant', 'supplier']),
            models.Index(fields=['tenant', 'name']),
        ]

    def __str__(self):
        return self.name

    @property
    def base_unit_name(self) -> str:
        """Returns the smallest unit name from ItemUnit, falls back to legacy unit FK."""
        try:
            iu = self.item_units.order_by('factor').first()
            if iu:
                return iu.name
        except Exception:
            pass
        return self.unit.name if self.unit else ''

    def save(self, *args, **kwargs):
        # توليد SKU تلقائي إذا لم يُحدَّد
        if not self.sku:
            self.sku = self._next_auto_sku()
        super().save(*args, **kwargs)

    def _next_auto_sku(self):
        """
        أكبر رقم ITM-xxxxx مستخدم لدى المشترك + 1، مع تخطّي أي رمز محجوز —
        لا يعتمد على «آخر صنف أُنشئ» لأن رمزه قد يكون مخصصاً أو أُعيد توليده.
        """
        existing = set(
            Item.objects.filter(tenant=self.tenant, sku__startswith='ITM-').values_list('sku', flat=True)
        )
        numbers = [int(s[4:]) for s in existing if s[4:].isdigit()]
        next_num = (max(numbers) + 1) if numbers else 1
        while f"ITM-{next_num:05d}" in existing:
            next_num += 1
        return f"ITM-{next_num:05d}"


# ============================================
# ITEM UNIT (وحدات المنتج)
# ============================================

class ItemUnit(TenantMixin):
    """
    وحدات قياس مرتبطة بمنتج محدد.
    كل وحدة لها عامل تحويل بالنسبة للوحدة الأصغر (factor=1).
    مثال: قطعة=1، كرتون=12، طرد=144
    """
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='item_units',
        verbose_name='المنتج'
    )
    name = models.CharField('اسم الوحدة', max_length=50)
    factor = models.DecimalField(
        'العامل', max_digits=10, decimal_places=4, default=1,
        help_text='الكمية بالنسبة للوحدة الأصغر — الوحدة الأصغر دائماً = 1'
    )

    class Meta:
        db_table      = 'item_product_units'
        ordering      = ['factor']
        verbose_name  = 'وحدة المنتج'
        unique_together = [('item', 'name')]
        indexes = [
            models.Index(fields=['tenant', 'item']),
        ]

    def __str__(self):
        return self.name


def unit_for_item_unit(tenant, item_unit_id):
    """
    بنود الفواتير ترتبط بجدول الوحدات العام (Unit)، بينما الواجهة ترسل معرّف
    وحدة المنتج (ItemUnit). المعرّفان من جدولين مختلفين، فالبحث بالمعرّف مباشرة
    كان يربط البند بوحدة أخرى لا علاقة لها. نطابق بالاسم، وإلا نترك الوحدة فارغة
    (المعامل unit_factor هو ما يحدد الكمية فعلياً).
    """
    if not item_unit_id:
        return None
    name = ItemUnit.objects.filter(pk=item_unit_id, tenant=tenant).values_list('name', flat=True).first()
    if not name:
        return None
    return Unit.objects.filter(tenant=tenant, name=name).first()
