"""
Items Views - عمليات CRUD للمنتجات والتصنيفات والوحدات
كل العمليات عبر JSON API (AJAX) + صفحة واحدة لكل قسم
"""
from apps.accounts.activity_service import log_activity
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponseNotAllowed, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from decimal import Decimal
from apps.accounts.decorators import require_permission, branch_scope_exempt
from apps.core.utils import filter_by_branch_via
from .forms import CategoryForm, ItemForm, UnitForm
from .models import Category, Item, Unit
from apps.sales.models import StockMovement
from apps.stocks.models import StockQuantity


def _ensure_tenant(request):
    return getattr(request, 'tenant', None)


def _serialize_errors(form):
    return {f: [str(e) for e in errs] for f, errs in form.errors.items()}


# ============================================================
# صفحة المنتجات الرئيسية
# ============================================================

@login_required
@require_permission('view_items')
def item_list(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return redirect('core:no_tenant')

    qs = Item.objects.for_tenant(tenant)
    total = qs.count()
    active = qs.filter(is_active=True).count()
    out_of_stock = qs.filter(is_active=True, min_quantity__gt=0).count()

    from apps.core.utils import currency_symbol
    from apps.suppliers.models import Supplier
    local_cur = tenant.currency
    context = {
        'item_form': ItemForm(tenant=tenant),
        'suppliers': Supplier.objects.for_tenant(tenant).for_branch(getattr(request, 'branch', None)).filter(is_active=True).order_by('name'),
        'local_currency': local_cur,
        'local_currency_symbol': currency_symbol(local_cur),
        'stats': {
            'total': total,
            'active': active,
            'inactive': total - active,
            'out_of_stock': out_of_stock,
        },
    }
    return render(request, 'items/item_list.html', context)


# ============================================================
# صفحة التصنيفات
# ============================================================

@login_required
@require_permission('view_categories')
def category_list(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return redirect('core:no_tenant')

    qs = Category.objects.for_tenant(tenant)
    total = qs.count()
    root_count = qs.filter(parent=None).count()

    context = {
        'form': CategoryForm(tenant=tenant),
        'stats': {
            'total': total,
            'root_count': root_count,
            'active': qs.filter(is_active=True).count(),
        },
    }
    return render(request, 'items/category_list.html', context)


# ============================================================
# صفحة وحدات القياس
# ============================================================

@login_required
@require_permission('view_items')
def unit_list(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return redirect('core:no_tenant')

    qs = Unit.objects.for_tenant(tenant)
    context = {
        'form': UnitForm(tenant=tenant),
        'stats': {
            'total': qs.count(),
            'active': qs.filter(is_active=True).count(),
        },
    }
    return render(request, 'items/unit_list.html', context)


# ============================================================
# Items: جدول API
# ============================================================

@login_required
@require_permission('view_items')
def item_table_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 25))
    search_value = request.GET.get('search[value]', '').strip()
    status_filter = request.GET.get('status', '').strip()
    category_id = request.GET.get('category', '').strip()
    supplier_id = request.GET.get('supplier', '').strip()

    from .models import ItemUnit
    qs = Item.objects.for_tenant(tenant).select_related('category', 'supplier').prefetch_related('item_units')
    records_total = qs.count()

    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if category_id:
        qs = qs.filter(category_id=category_id)

    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)

    if search_value:
        qs = qs.filter(
            Q(name__icontains=search_value) |
            Q(sku__icontains=search_value) |
            Q(barcode__icontains=search_value) |
            Q(name_en__icontains=search_value)
        )

    records_filtered = qs.count()

    order_col = request.GET.get('order[0][column]', '0')
    order_dir = request.GET.get('order[0][dir]', 'asc')
    col_name = request.GET.get(f'columns[{order_col}][data]', 'name')
    allowed = {
        'sku': 'sku', 'name': 'name', 'barcode': 'barcode',
        'selling_price': 'selling_price', 'cost_price': 'cost_price',
        'is_active': 'is_active', 'created_at': 'created_at',
    }
    order_field = allowed.get(col_name, 'name')
    if order_dir == 'desc':
        order_field = f'-{order_field}'

    qs = qs.order_by(order_field)[start:start + length]

    def _unit_label(item):
        units = list(item.item_units.order_by('factor'))
        if not units:
            return item.base_unit_name or '-'
        if len(units) == 1:
            return units[0].name
        return '-'   # multi-unit: show — per user request

    data = [
        {
            'id': item.id,
            'sku': item.sku,
            'name': item.name,
            'item_type': item.item_type,
            'barcode': item.barcode or '-',
            'category': item.category.name if item.category else '-',
            'supplier': item.supplier.name if item.supplier else '-',
            'unit': _unit_label(item),
            'has_multiple_units': item.has_multiple_units,
            'cost_price': str(item.cost_price),
            'selling_price': str(item.selling_price),
            'track_serial': item.track_serial,
            'is_active': item.is_active,
        }
        for item in qs
    ]

    return JsonResponse({
        'draw': draw,
        'recordsTotal': records_total,
        'recordsFiltered': records_filtered,
        'data': data,
    })


# ============================================================
# Helpers
# ============================================================

def _save_item_units(item, units_json_str, tenant):
    """Parse units_json and sync ItemUnit records for this item."""
    import json
    from decimal import Decimal, InvalidOperation
    from .models import ItemUnit

    if not units_json_str:
        return

    try:
        units_data = json.loads(units_json_str)
    except (ValueError, TypeError):
        return

    if not isinstance(units_data, list) or not units_data:
        return

    # Delete old and recreate
    ItemUnit.objects.filter(item=item).delete()

    has_multiple = len(units_data) > 1
    for row in units_data:
        name = str(row.get('name', '')).strip()
        if not name:
            continue
        try:
            factor = Decimal(str(row.get('factor', 1)))
        except InvalidOperation:
            factor = Decimal('1')
        ItemUnit.objects.create(tenant=tenant, item=item, name=name, factor=factor)

    item.has_multiple_units = has_multiple
    item.save(update_fields=['has_multiple_units'])


# ============================================================
# Items: إنشاء
# ============================================================

@login_required
@require_permission('add_items')
@transaction.atomic
def item_create_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    from django.db import IntegrityError
    form = ItemForm(request.POST, request.FILES, tenant=tenant)
    if form.is_valid():
        item = form.save(commit=False)
        item.tenant = tenant
        item.created_by = request.user
        item.updated_by = request.user
        try:
            item.save()
        except IntegrityError:
            return JsonResponse({'success': False, 'message': 'رمز المنتج (SKU) مستخدم بالفعل، يرجى اختيار رمز آخر', 'errors': {'sku': ['رمز المنتج مستخدم بالفعل']}}, status=400)
        form.save_m2m()
        _save_item_units(item, request.POST.get('units_json', ''), tenant)
        log_activity(request, 'إضافة منتج جديد',
                     f"المنتج: {item.name}\nكود: {item.sku or '—'}\nالنوع: {item.get_item_type_display()}", 'create')
        return JsonResponse({'success': True, 'message': 'تم إضافة المنتج بنجاح', 'id': item.id})

    return JsonResponse({
        'success': False,
        'message': 'يرجى التحقق من الحقول المطلوبة',
        'errors': _serialize_errors(form),
    }, status=400)


# ============================================================
# Items: تفاصيل
# ============================================================

@login_required
@require_permission('view_items')
def item_detail_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    try:
        item = Item.objects.for_tenant(tenant).select_related('category', 'unit', 'purchase_unit', 'supplier').get(pk=pk)
    except Item.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'المنتج غير موجود'}, status=404)

    iu_list = list(item.item_units.order_by('factor').values('id', 'name', 'factor'))
    return JsonResponse({
        'success': True,
        'data': {
            'id': item.id,
            'name': item.name,
            'name_en': item.name_en,
            'sku': item.sku,
            'barcode': item.barcode,
            'item_type': item.item_type,
            'category': item.category_id,
            'category_name': item.category.name if item.category else '',
            'supplier': item.supplier_id,
            'supplier_name': item.supplier.name if item.supplier else '',
            'unit': item.unit_id,
            'unit_name': item.unit.name if item.unit else '',
            'purchase_unit': item.purchase_unit_id,
            'purchase_unit_name': item.purchase_unit.name if item.purchase_unit else '',
            'cost_price': str(item.cost_price),
            'selling_price': str(item.selling_price),
            'min_selling_price': str(item.min_selling_price),
            'tax_rate': str(item.tax_rate),
            'min_quantity': str(item.min_quantity),
            'max_quantity': str(item.max_quantity),
            'track_serial': item.track_serial,
            'manufacturer': item.manufacturer,
            'country_of_origin': item.country_of_origin,
            'description': item.description,
            'is_active': item.is_active,
            'is_sellable': item.is_sellable,
            'is_purchasable': item.is_purchasable,
            'has_multiple_units': item.has_multiple_units,
            'item_units': [
                {'id': u['id'], 'name': u['name'], 'factor': str(u['factor'])}
                for u in iu_list
            ],
        },
    })


@login_required
@require_permission('view_items')
def item_transactions_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    try:
        item = Item.objects.for_tenant(tenant).get(pk=pk)
    except Item.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'المنتج غير موجود'}, status=404)

    is_service = item.item_type == 'service'
    if is_service:
        current_qty = 0
        movements = []
    else:
        branch = getattr(request, 'branch', None)
        current_qty = (
            filter_by_branch_via(
                StockQuantity.objects.for_tenant(tenant).filter(item=item), branch, field='stock__branch',
            )
            .aggregate(total=Sum('quantity'))['total']
            or 0
        )

        movements = (
            filter_by_branch_via(
                StockMovement.objects.for_tenant(tenant).filter(item=item), branch, field='stock__branch',
            )
            .select_related('stock')
            .order_by('-id')[:200]
        )

    data = [
        {
            'movement_date': m.movement_date.strftime('%Y-%m-%d'),
            'stock': m.stock.name,
            'movement_type': m.movement_type,
            'movement_type_label': m.get_movement_type_display(),
            'direction': m.direction,
            'quantity': str(m.quantity),
            'balance_after': str(m.balance_after),
            'reference_type': m.reference_type or '—',
            'notes': m.notes or '—',
            'is_reversal': m.is_reversal,
        }
        for m in movements
    ]

    return JsonResponse({
        'success': True,
        'data': {
            'item_id': item.id,
            'item_name': item.name,
            'item_sku': item.sku,
            'item_type': item.item_type,
            'is_service': is_service,
            'current_qty': str(current_qty),
            'movements': data,
        }
    })


# ============================================================
# Items: تعديل
# ============================================================

@login_required
@require_permission('change_items')
@transaction.atomic
def item_update_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        item = Item.objects.for_tenant(tenant).get(pk=pk)
    except Item.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'المنتج غير موجود'}, status=404)

    form = ItemForm(request.POST, request.FILES, instance=item, tenant=tenant)
    if form.is_valid():
        updated = form.save(commit=False)
        updated.updated_by = request.user
        updated.save()
        form.save_m2m()
        _save_item_units(item, request.POST.get('units_json', ''), tenant)
        log_activity(request, 'تعديل منتج', updated.name, 'update')
        return JsonResponse({'success': True, 'message': 'تم تحديث المنتج بنجاح'})

    return JsonResponse({
        'success': False,
        'message': 'يرجى التحقق من الحقول',
        'errors': _serialize_errors(form),
    }, status=400)


# ============================================================
# Items: حذف
# ============================================================

@login_required
@require_permission('delete_items')
@require_permission('change_items')
def item_delete_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        item = Item.objects.for_tenant(tenant).get(pk=pk)
    except Item.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'المنتج غير موجود'}, status=404)

    name = item.name
    try:
        item.delete()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error('item_delete_api error pk=%s: %s', pk, e, exc_info=True)
        return JsonResponse({'success': False, 'message': 'تعذر الحذف: المنتج مرتبط بسجلات لا يمكن حذفها (فواتير، تحويلات، جرد)'}, status=400)
    log_activity(request, 'حذف منتج', name, 'delete')
    return JsonResponse({'success': True, 'message': f'تم حذف المنتج "{name}" بنجاح'})


# ============================================================
# API: بحث سريع (للاستخدام في فواتير البيع/الشراء)
# ============================================================

@login_required
@require_permission('view_items')
def item_search_api(request):
    """
    بحث سريع عن المنتجات - يُستخدم مستقبلاً في فواتير البيع والشراء.
    يرجع أول 15 نتيجة مطابقة.
    """
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    q = request.GET.get('q', '').strip()
    try:
        min_chars = int(request.GET.get('min_chars', 2))
    except (TypeError, ValueError):
        min_chars = 2
    min_chars = max(0, min(min_chars, 5))

    if len(q) < min_chars:
        return JsonResponse({'results': []})

    from .models import ItemUnit as ItemUnitModel
    limit = 100 if not q else 15
    types_param = request.GET.get('types', '').strip()
    type_list = [t.strip() for t in types_param.split(',') if t.strip()] if types_param else []
    if type_list:
        base_qs = Item.objects.for_tenant(tenant).filter(is_active=True, item_type__in=type_list)
    else:
        base_qs = Item.objects.for_tenant(tenant).filter(is_active=True, is_sellable=True)
    if q:
        qs = base_qs.filter(
            Q(name__icontains=q) |
            Q(barcode__icontains=q) |
            Q(sku__icontains=q)
        ).prefetch_related('item_units')[:limit]
    else:
        qs = base_qs.order_by('name').prefetch_related('item_units')[:limit]

    results = []
    for item in qs:
        # Use per-product ItemUnit if defined, else fall back to legacy unit/purchase_unit
        iu_qs = list(item.item_units.order_by('factor'))
        if iu_qs:
            units    = [{'id': iu.id, 'name': iu.name, 'factor': str(iu.factor)} for iu in iu_qs]
            base_iu  = iu_qs[0]
            unit_id   = base_iu.id
            unit_name = base_iu.name
            unit_factor = '1'
        else:
            units = []
            unit_id   = None
            unit_name = ''
            unit_factor = '1'

        results.append({
            'id': item.id,
            'name': item.name,
            'sku': item.sku,
            'barcode': item.barcode,
            'item_type': item.item_type,
            'item_type_label': item.get_item_type_display(),
            'cost_price': str(item.cost_price),
            'selling_price': str(item.selling_price),
            'unit_id': unit_id,
            'unit_name': unit_name,
            'unit_factor': unit_factor,
            'units': units,
            'track_serial': item.track_serial,
        })
    return JsonResponse({'results': results})


# ============================================================
# Categories: CRUD APIs
# ============================================================

@login_required
@require_permission('view_categories')
def category_table_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 50))
    search_value = request.GET.get('search[value]', '').strip()

    qs = Category.objects.for_tenant(tenant).select_related('parent')
    records_total = qs.count()

    if search_value:
        qs = qs.filter(Q(name__icontains=search_value))

    records_filtered = qs.count()
    qs = qs[start:start + length]

    data = [
        {
            'id': c.id,
            'name': c.name,
            'full_path': c.full_path,
            'parent': c.parent.name if c.parent else '-',
            'icon': c.icon or 'fa-tag',
            'is_active': c.is_active,
            'display_order': c.display_order,
        }
        for c in qs
    ]
    return JsonResponse({
        'draw': draw, 'recordsTotal': records_total,
        'recordsFiltered': records_filtered, 'data': data,
    })


@login_required
@require_permission('view_categories')
def category_options_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    qs = Category.objects.for_tenant(tenant).order_by('display_order', 'name')
    if request.GET.get('all') != '1':
        qs = qs.filter(is_active=True)
    cats = qs.values('id', 'name', 'parent_id', 'icon', 'is_active', 'display_order')
    return JsonResponse({'success': True, 'categories': list(cats)})


@login_required
@require_permission('add_categories')
@transaction.atomic
def category_create_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    post_data = request.POST.copy()
    if not post_data.get('display_order'):
        post_data['display_order'] = '0'
    form = CategoryForm(post_data, tenant=tenant)
    if form.is_valid():
        cat = form.save(commit=False)
        cat.tenant = tenant
        cat.created_by = request.user
        cat.updated_by = request.user
        cat.display_order = cat.display_order or 0
        cat.save()
        return JsonResponse({'success': True, 'message': 'تم إضافة التصنيف بنجاح', 'id': cat.id})

    return JsonResponse({'success': False, 'message': 'خطأ في البيانات', 'errors': _serialize_errors(form)}, status=400)


@login_required
@require_permission('view_categories')
def category_detail_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    try:
        cat = Category.objects.for_tenant(tenant).get(pk=pk)
    except Category.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'التصنيف غير موجود'}, status=404)

    return JsonResponse({'success': True, 'data': {
        'id': cat.id, 'name': cat.name, 'parent': cat.parent_id,
        'icon': cat.icon, 'description': cat.description,
        'display_order': cat.display_order, 'is_active': cat.is_active,
    }})


@login_required
@require_permission('change_categories')
@transaction.atomic
def category_update_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        cat = Category.objects.for_tenant(tenant).get(pk=pk)
    except Category.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'التصنيف غير موجود'}, status=404)

    form = CategoryForm(request.POST, instance=cat, tenant=tenant)
    if form.is_valid():
        updated = form.save(commit=False)
        updated.updated_by = request.user
        updated.save()
        return JsonResponse({'success': True, 'message': 'تم تحديث التصنيف بنجاح'})

    return JsonResponse({'success': False, 'message': 'خطأ في البيانات', 'errors': _serialize_errors(form)}, status=400)


@login_required
@require_permission('delete_categories')
@require_permission('change_categories')
def category_delete_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        cat = Category.objects.for_tenant(tenant).get(pk=pk)
    except Category.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'التصنيف غير موجود'}, status=404)

    item_count = Item.objects.for_tenant(tenant).filter(category=cat).count()
    if item_count:
        return JsonResponse({
            'success': False,
            'message': f'لا يمكن حذف هذا التصنيف لوجود {item_count} منتج مرتبط به.',
        }, status=400)

    name = cat.name
    cat.delete()
    return JsonResponse({'success': True, 'message': f'تم حذف التصنيف "{name}" بنجاح'})


# ============================================================
# Units: CRUD APIs
# ============================================================

@login_required
@require_permission('view_items')
def unit_table_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 50))
    search_value = request.GET.get('search[value]', '').strip()

    qs = Unit.objects.for_tenant(tenant).select_related('base_unit')
    records_total = qs.count()

    if search_value:
        qs = qs.filter(Q(name__icontains=search_value) | Q(abbreviation__icontains=search_value))

    records_filtered = qs.count()
    qs = qs[start:start + length]

    data = [
        {
            'id': u.id,
            'name': u.name,
            'abbreviation': u.abbreviation or '-',
            'base_unit': u.base_unit.name if u.base_unit else '-',
            'conversion_factor': str(u.conversion_factor),
            'is_active': u.is_active,
        }
        for u in qs
    ]
    return JsonResponse({
        'draw': draw, 'recordsTotal': records_total,
        'recordsFiltered': records_filtered, 'data': data,
    })


@login_required
@require_permission('view_items')
def unit_options_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    units = (
        Unit.objects.for_tenant(tenant)
        .filter(is_active=True)
        .order_by('name')
        .values('id', 'name')
    )
    return JsonResponse({'success': True, 'units': list(units)})


@login_required
@require_permission('add_items')
@transaction.atomic
def unit_create_api(request):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    form = UnitForm(request.POST, tenant=tenant)
    if form.is_valid():
        unit = form.save(commit=False)
        unit.tenant = tenant
        unit.created_by = request.user
        unit.updated_by = request.user
        unit.save()
        return JsonResponse({'success': True, 'message': 'تم إضافة وحدة القياس بنجاح', 'id': unit.id})

    return JsonResponse({'success': False, 'message': 'خطأ في البيانات', 'errors': _serialize_errors(form)}, status=400)


@login_required
@require_permission('view_items')
def unit_detail_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    try:
        unit = Unit.objects.for_tenant(tenant).get(pk=pk)
    except Unit.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'وحدة القياس غير موجودة'}, status=404)

    return JsonResponse({'success': True, 'data': {
        'id': unit.id, 'name': unit.name, 'abbreviation': unit.abbreviation,
        'base_unit': unit.base_unit_id, 'conversion_factor': str(unit.conversion_factor),
        'is_active': unit.is_active,
    }})


@login_required
@require_permission('change_items')
@transaction.atomic
def unit_update_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        unit = Unit.objects.for_tenant(tenant).get(pk=pk)
    except Unit.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'وحدة القياس غير موجودة'}, status=404)

    form = UnitForm(request.POST, instance=unit, tenant=tenant)
    if form.is_valid():
        updated = form.save(commit=False)
        updated.updated_by = request.user
        updated.save()
        return JsonResponse({'success': True, 'message': 'تم تحديث وحدة القياس بنجاح'})

    return JsonResponse({'success': False, 'message': 'خطأ في البيانات', 'errors': _serialize_errors(form)}, status=400)


@login_required
@require_permission('delete_items')
@require_permission('change_items')
def unit_delete_api(request, pk):
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        unit = Unit.objects.for_tenant(tenant).get(pk=pk)
    except Unit.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'وحدة القياس غير موجودة'}, status=404)

    item_count = Item.objects.for_tenant(tenant).filter(
        Q(unit=unit) | Q(purchase_unit=unit)
    ).count()
    if item_count:
        return JsonResponse({
            'success': False,
            'message': f'لا يمكن حذف هذه الوحدة لوجود {item_count} منتج مرتبط بها.',
        }, status=400)

    name = unit.name
    unit.delete()
    return JsonResponse({'success': True, 'message': f'تم حذف وحدة القياس "{name}" بنجاح'})


# ══════════════════════════════════════════════════════
# IMPORT / EXPORT
# ══════════════════════════════════════════════════════

@login_required
@require_permission('export_items')
def item_export_api(request):
    from apps.core.io_utils import csv_response, csv_writer
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    response = csv_response('items.csv')
    writer = csv_writer(response)
    writer.writerow([
        'الاسم', 'الاسم الإنجليزي', 'الرمز (SKU)', 'الباركود',
        'التصنيف', 'الوحدة', 'وحدة الشراء',
        'سعر التكلفة', 'سعر البيع', 'أدنى سعر بيع',
        'الحد الأدنى للمخزون', 'الحد الأقصى للمخزون',
        'تتبع السيريال',
        'للبيع', 'للشراء', 'نشط',
    ])
    qs = Item.objects.for_tenant(tenant).select_related('category').prefetch_related('item_units').order_by('name')
    for item in qs:
        writer.writerow([
            item.name,
            item.name_en or '',
            item.sku or '',
            item.barcode or '',
            item.category.name if item.category else '',
            item.base_unit_name,
            '',
            item.cost_price, item.selling_price, item.min_selling_price,
            item.min_quantity,
            item.max_quantity,
            'نعم' if item.track_serial else 'لا',
            'نعم' if item.is_sellable else 'لا',
            'نعم' if item.is_purchasable else 'لا',
            'نعم' if item.is_active else 'لا',
        ])
    return response


# ============================================================
# استيراد / تصدير التصنيفات
# ============================================================

@login_required
@require_permission('view_items')
def category_export_api(request):
    from apps.core.io_utils import csv_response, csv_writer
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    response = csv_response('categories_export.csv')
    writer = csv_writer(response)
    writer.writerow(['الاسم', 'التصنيف الرئيسي', 'الوصف', 'الترتيب', 'الحالة'])

    qs = Category.objects.for_tenant(tenant).select_related('parent').order_by('display_order', 'name')
    for cat in qs:
        writer.writerow([
            cat.name,
            cat.parent.name if cat.parent else '',
            cat.description or '',
            cat.display_order,
            'نعم' if cat.is_active else 'لا',
        ])
    return response


_CATEGORY_FIELD_SCHEMA = [
    {"field": "name",          "description": "اسم التصنيف أو القسم أو الفئة", "required": True},
    {"field": "parent",        "description": "التصنيف الرئيسي أو الأب أو التصنيف الأعلى"},
    {"field": "description",   "description": "وصف التصنيف أو تفاصيله"},
    {"field": "display_order", "description": "ترتيب العرض أو الأولوية"},
    {"field": "is_active",     "description": "هل التصنيف نشط أو مفعّل"},
]


@login_required
@require_permission('add_categories')
def category_import_api(request):
    from apps.core.io_utils import parse_uploaded_file, smart_get, bool_from_str
    from apps.ai.services import smart_map_headers

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)

    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'success': False, 'message': 'الرجاء اختيار ملف'}, status=400)

    rows, err = parse_uploaded_file(f)
    if err:
        return JsonResponse({'success': False, 'message': err}, status=400)

    if not rows:
        return JsonResponse({'success': False, 'message': 'الملف فارغ أو لا يحتوي على بيانات'}, status=400)

    actual_headers = list(rows[0].keys())
    try:
        mapping = smart_map_headers(actual_headers, _CATEGORY_FIELD_SCHEMA)
    except Exception:
        mapping = {}

    imported, errors = 0, []
    for i, row in enumerate(rows, start=2):
        name = smart_get(row, 'name', mapping, 'الاسم', 'اسم التصنيف', 'التصنيف', 'name')
        if not name:
            errors.append(f'الصف {i}: اسم التصنيف مطلوب')
            continue
        try:
            parent_name = smart_get(row, 'parent', mapping, 'التصنيف الرئيسي', 'الأب', 'parent')
            parent = None
            if parent_name:
                parent = Category.objects.for_tenant(tenant).filter(name=parent_name).first()

            is_active = bool_from_str(smart_get(row, 'is_active', mapping, 'الحالة', 'is_active', default='نعم'))
            try:
                display_order = int(smart_get(row, 'display_order', mapping, 'الترتيب', 'display_order', default='0'))
            except (ValueError, TypeError):
                display_order = 0

            description = smart_get(row, 'description', mapping, 'الوصف', 'description')

            cat, created = Category.objects.for_tenant(tenant).get_or_create(
                name=name,
                defaults={
                    'tenant': tenant,
                    'parent': parent,
                    'description': description,
                    'display_order': display_order,
                    'is_active': is_active,
                },
            )
            if not created:
                if parent is not None:
                    cat.parent = parent
                cat.is_active = is_active
                cat.display_order = display_order
                if description:
                    cat.description = description
                cat.save()
            imported += 1
        except Exception as exc:
            import logging, traceback
            logging.getLogger('items').error('category import row %d: %s\n%s', i, exc, traceback.format_exc())
            errors.append(f'الصف {i}: {exc}')

    msg = f'تم استيراد {imported} تصنيف بنجاح'
    if errors:
        msg += f'. {len(errors)} أخطاء'
    return JsonResponse({'success': True, 'message': msg, 'imported': imported, 'errors': errors[:10]})


@login_required
@require_permission('add_categories')
def category_download_template(request):
    from apps.core.io_utils import csv_response, csv_writer
    response = csv_response('categories_template.csv')
    writer = csv_writer(response)
    writer.writerow(['الاسم', 'التصنيف الرئيسي', 'الوصف', 'الترتيب', 'الحالة'])
    writer.writerow(['إلكترونيات', '', 'منتجات إلكترونية', '1', 'نعم'])
    writer.writerow(['هواتف', 'إلكترونيات', 'الهواتف الذكية', '1', 'نعم'])
    return response


# ============================================================
# ITEM META API — معلومات المنتج للنماذج الديناميكية
# ============================================================

@login_required
@require_permission('view_items')
def item_meta_api(request, pk):
    """Returns item tracking flags for dynamic form behavior"""
    tenant = _ensure_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'message': 'لا يوجد نشاط تجاري'}, status=400)
    from django.shortcuts import get_object_or_404
    item = get_object_or_404(Item, pk=pk, tenant=tenant)
    iu_qs = list(item.item_units.order_by('factor'))
    if iu_qs:
        units     = [{'id': u.id, 'name': u.name, 'factor': str(u.factor)} for u in iu_qs]
        unit_id   = iu_qs[0].id
        unit_name = iu_qs[0].name
    else:
        units     = []
        unit_id   = None
        unit_name = item.base_unit_name
    return JsonResponse({
        'id': item.id,
        'name': item.name,
        'track_serial': item.track_serial,
        'cost_price': str(item.cost_price),
        'selling_price': str(item.selling_price),
        'unit_id': unit_id,
        'unit_name': unit_name,
        'units': units,
    })

