"""
خدمات شحنات المخزن المركزي .

الدورة: مسودة ← (إرسال) في الطريق ← (تأكيد الجهة المستلِمة للكمية الفعلية) تم الاستلام.
  - الإرسال: تخرج الكمية من المخزن المُرسِل فوراً.
  - الاستلام: تؤكد الجهة المستلِمة الكمية الفعلية لكل بند (≤ المرسلة)؛ تدخل مخزنها ما استُلم
    فعلاً، ويعود الفرق تلقائياً إلى المخزن المُرسِل مع تعليم الشحنة.
  - الإلغاء: للمسودة أو للشحنة في الطريق فقط، فتعود الكمية إلى المخزن المُرسِل.
  - التكلفة: تكلفة الشراء المركزي للصنف وقت الإرسال، تُسجَّل على حركات المخزون.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.sales.models import StockMovement

from .models import Shipment, ShipmentLine, Stock, StockQuantity


def _sq(tenant, stock, item):
    sq, created = StockQuantity.objects.get_or_create(
        tenant=tenant, stock=stock, item=item,
        defaults={'quantity': Decimal('0'), 'reserved_quantity': Decimal('0')})
    if not created:
        sq = StockQuantity.objects.select_for_update().get(pk=sq.pk)
    return sq


def _movement(tenant, item, stock, direction, qty, unit_cost, date, ref_type, ref_id, balance, notes):
    return StockMovement.objects.create(
        tenant=tenant, item=item, stock=stock,
        movement_type='transfer_out' if direction == 'out' else 'transfer_in',
        direction=direction, quantity=qty, unit_cost=unit_cost, movement_date=date,
        reference_type=ref_type, reference_id=ref_id, balance_after=balance, notes=notes,
    )


def _is_service(item):
    return getattr(item, 'item_type', None) == 'service'


@transaction.atomic
def create_shipment(tenant, from_stock, to_stock, shipment_date, notes, lines, user=None, direction='to_branch',
                    requisition=None):
    """
    ينشئ شحنة مسودة. lines: [{'item': Item, 'quantity': Decimal}].
      - to_branch: من المخزن المركزي إلى مخزن فرع.
      - to_central: مرتجع من مخزن فرع إلى المخزن المركزي.
    """
    if not tenant.has_central_warehouse():
        raise ValueError('الشحنات متاحة في نسخة المؤسسات فقط.')
    if direction == 'to_branch':
        if not from_stock.is_central:
            raise ValueError('الشحنة يجب أن تخرج من المخزن المركزي.')
        branch_stock, label = to_stock, 'تصل إلى'
    elif direction == 'to_central':
        if not to_stock.is_central or not to_stock.is_active:
            raise ValueError('المرتجع يجب أن يصل إلى المخزن المركزي.')
        branch_stock, label = from_stock, 'تخرج من'
    else:
        raise ValueError('اتجاه شحنة غير صالح.')
    if branch_stock.is_central or branch_stock.branch_id is None:
        raise ValueError(f'الشحنة يجب أن {label} مخزن تابع لفرع.')
    if not branch_stock.is_active:
        raise ValueError('مخزن الفرع المختار غير نشط.')
    clean = [(ln['item'], Decimal(str(ln['quantity']))) for ln in lines if Decimal(str(ln['quantity'])) > 0]
    if not clean:
        raise ValueError('أضف بنداً واحداً على الأقل بكمية أكبر من صفر.')
    seen = set()
    for item, _qty in clean:
        if item.pk in seen:
            raise ValueError(f'الصنف «{item.name}» مكرر في الشحنة.')
        seen.add(item.pk)

    req_lines = {}
    if requisition is not None:
        # شحنة تلبّي طلب شراء من فرع: للتوزيع فقط، وإلى مخزن الفرع صاحب الطلب، وضمن الكميات المعتمدة المتبقية.
        requisition = type(requisition).objects.select_for_update().get(pk=requisition.pk)
        if direction != 'to_branch' or requisition.status != 'approved':
            raise ValueError('الشحنة تُربط بطلب شراء معتمد فقط.')
        if branch_stock.branch_id != requisition.branch_id:
            raise ValueError('مخزن الشحنة يجب أن يتبع فرع صاحب الطلب.')
        by_item = {ln.item_id: ln for ln in requisition.lines.select_related('item')}
        for item, qty in clean:
            rl = by_item.get(item.pk)
            if rl is None:
                raise ValueError(f'الصنف «{item.name}» ليس ضمن طلب الشراء.')
            if qty > rl.remaining_quantity:
                raise ValueError(
                    f'كمية «{item.name}» ({qty:.2f}) تتجاوز المتبقي من المعتمد ({rl.remaining_quantity:.2f}).')
            req_lines[item.pk] = rl

    shipment = Shipment.objects.create(
        tenant=tenant, direction=direction, from_stock=from_stock, to_stock=to_stock,
        branch_id=branch_stock.branch_id, shipment_date=shipment_date, notes=notes or '',
        requisition=requisition, created_by=user, updated_by=user)
    for item, qty in clean:
        ShipmentLine.objects.create(
            tenant=tenant, shipment=shipment, item=item, quantity_sent=qty,
            requisition_line=req_lines.get(item.pk),
            unit_cost=item.cost_price or Decimal('0'), created_by=user, updated_by=user)
    return shipment


def _refresh_requisition(shipment):
    """بعد تغيّر حالة شحنة مرتبطة بطلب شراء: يحدّث حالة الطلب (معتمد ↔ مكتمل التوريد)."""
    if shipment.requisition_id:
        from apps.requisitions.services import refresh_status
        refresh_status(shipment.requisition)


@transaction.atomic
def send_shipment(shipment, user=None):
    """يُخرج الكميات من المخزن المُرسِل ويجعل الشحنة «في الطريق»."""
    shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
    if shipment.status != 'draft':
        raise ValueError('يمكن إرسال المسودات فقط.')
    tenant = shipment.tenant
    lines = list(shipment.lines.select_related('item'))
    if not lines:
        raise ValueError('لا توجد بنود في الشحنة.')

    for line in lines:
        item = line.item
        if _is_service(item):
            raise ValueError(f'«{item.name}» خدمة ولا تُشحن.')
        sq = _sq(tenant, shipment.from_stock, item)
        available = sq.quantity - sq.reserved_quantity
        if available < line.quantity_sent:
            raise ValueError(
                f'الكمية غير كافية للمنتج «{item.name}» في {shipment.from_stock.name} '
                f'(متاح: {available:.2f}، مطلوب: {line.quantity_sent:.2f}).')
        sq.quantity -= line.quantity_sent
        sq.save(update_fields=['quantity', 'updated_at'])
        line.unit_cost = item.cost_price or Decimal('0')
        line.save(update_fields=['unit_cost', 'updated_at'])
        _movement(tenant, item, shipment.from_stock, 'out', line.quantity_sent, line.unit_cost,
                  shipment.shipment_date, 'central_shipment', shipment.id, sq.quantity,
                  f'شحنة {shipment.shipment_number} — إلى {shipment.to_stock.name}')

    shipment.status = 'in_transit'
    shipment.sent_at = timezone.now()
    shipment.updated_by = user
    shipment.save(update_fields=['status', 'sent_at', 'updated_by', 'updated_at'])
    _refresh_requisition(shipment)
    return shipment






@transaction.atomic
def receive_shipment(shipment, received_quantities, user=None):
    """
    تأكيد الفرع للاستلام. received_quantities: {line_id: Decimal} — الكمية الفعلية
    لكل بند (0 ≤ كمية ≤ المرسلة). ما لم يُذكر بند يُعدّ مستلَماً بالكامل.
    """
    shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
    if shipment.status != 'in_transit':
        raise ValueError('يمكن تأكيد استلام الشحنات التي في الطريق فقط.')
    tenant = shipment.tenant
    lines = list(shipment.lines.select_related('item'))
    today = timezone.localdate()

    # تحقق أولاً من كل الكميات قبل أي تعديل.
    actual = {}
    for line in lines:
        raw = received_quantities.get(line.id, line.quantity_sent)
        try:
            qty = Decimal(str(raw))
        except Exception:
            raise ValueError(f'كمية غير صالحة للمنتج «{line.item.name}».')
        if qty < 0 or qty > line.quantity_sent:
            raise ValueError(
                f'الكمية المستلَمة للمنتج «{line.item.name}» يجب أن تكون بين 0 و {line.quantity_sent:.2f}.')
        actual[line.id] = qty

    has_difference = False
    for line in lines:
        item = line.item
        received = actual[line.id]
        diff = line.quantity_sent - received
        line.quantity_received = received
        line.save(update_fields=['quantity_received', 'updated_at'])

        if received > 0:
            sq_in = _sq(tenant, shipment.to_stock, item)
            sq_in.quantity += received
            sq_in.save(update_fields=['quantity', 'updated_at'])
            _movement(tenant, item, shipment.to_stock, 'in', received, line.unit_cost, today,
                      'central_shipment', shipment.id, sq_in.quantity,
                      f'شحنة {shipment.shipment_number} — من {shipment.from_stock.name}')

        if diff > 0:
            has_difference = True
            sq_c = _sq(tenant, shipment.from_stock, item)
            sq_c.quantity += diff
            sq_c.save(update_fields=['quantity', 'updated_at'])
            _movement(tenant, item, shipment.from_stock, 'in', diff, line.unit_cost, today,
                      'central_shipment_difference', shipment.id, sq_c.quantity,
                      f'فرق استلام شحنة {shipment.shipment_number} (عاد للمخزن المركزي)')


    shipment.status = 'received'
    shipment.has_difference = has_difference
    shipment.received_at = timezone.now()
    shipment.received_by = user
    shipment.updated_by = user
    shipment.save(update_fields=['status', 'has_difference', 'received_at', 'received_by', 'updated_by', 'updated_at'])
    _refresh_requisition(shipment)
    return shipment




@transaction.atomic
def cancel_shipment(shipment, user=None):
    """إلغاء مسودة، أو شحنة في الطريق (فتعود كميتها إلى المخزن المُرسِل)."""
    shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
    if shipment.status not in ('draft', 'in_transit'):
        raise ValueError('لا يمكن إلغاء شحنة تم استلامها أو ملغاة.')
    tenant = shipment.tenant
    if shipment.status == 'in_transit':
        today = timezone.localdate()
        for line in shipment.lines.select_related('item'):
            sq = _sq(tenant, shipment.from_stock, line.item)
            sq.quantity += line.quantity_sent
            sq.save(update_fields=['quantity', 'updated_at'])
            _movement(tenant, line.item, shipment.from_stock, 'in', line.quantity_sent, line.unit_cost,
                      today, 'central_shipment_cancel', shipment.id, sq.quantity,
                      f'إلغاء شحنة {shipment.shipment_number}')
    shipment.status = 'cancelled'
    shipment.updated_by = user
    shipment.save(update_fields=['status', 'updated_by', 'updated_at'])
    _refresh_requisition(shipment)
    return shipment
