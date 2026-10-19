# BANAN IMS — Inventory Management for Merchants

A multi-tenant SaaS system for inventory and sales management, built for merchants and product-selling companies — spare parts, electronics and electrical appliances, phones and computers, tools and equipment — with full Arabic (RTL) support.

---

## Tech Stack

| | |
|---|---|
| **Backend** | Django 4.2, Python 3.8+, MySQL |
| **Frontend** | Bootstrap 5 RTL, jQuery 3.7, DataTables 1.13.6, FontAwesome 6 |
| **AI** | DeepSeek API |
| **Font** | Cairo (Google Fonts) |

---

## Key Features

### Infrastructure
- Full data isolation between tenants via `TenantMixin`
- Three business setups: single store / multiple warehouses / multiple branches
- Subscription plans: trial / basic / professional / enterprise
- RBAC system: 30 sections, 170+ permissions, split-panel UI for managing groups
- Activity log for every operation

### Core Modules
- **Customers & Suppliers** — CRUD + ledger + payments
- **Items** — hierarchical categories, units of measure with conversion factors, barcode/SKU, serial-number tracking, manufacturer and country of origin
- **Stocks** — opening balances, inter-warehouse transfers, stocktaking, write-offs (damaged / defective / lost)
- **Sales** — invoices, quotes, returns, POS, deferred delivery
- **Purchases** — invoices, RFQ (request for quotation), purchase orders, returns
- **Expenses** — categories + linked to treasuries
- **Treasury** — cash and bank accounts, inter-treasury transfers
- **Employees** — records, salary payments, instant advances, incentives/deductions, auto-linked to treasuries
- **Sales Agents** — accounts with commission based on invoice, collection, or both, plus a self-service portal for their invoices and statements

### Advanced Features
- **AI Assistant** — chat with your real data + automatic daily business insights (DeepSeek)
- **Online Store** — a public storefront per tenant (unique slug), cart, checkout, business-hours scheduling, printable QR code
- **Customer Portal** — magic-link access for customers to view their invoices and statements
- **Notifications** — automatic (low stock, overdue invoice, new order...) with smart analysis
- **Backups** — per-tenant, no mysqldump, 7-day retention
- **Support** — built-in ticketing system

### Reports (36+ reports)
Sales, purchases, inventory, expenses, treasury, income statement (P&L)

---

## Quick Start

```bash
# Activate the virtual environment
source .env/bin/activate

# Install requirements
pip install -r requirements.txt

# Apply migrations
python manage.py migrate

# Business types are synced automatically after migrate
# (apps/core/data/business_types.json); this re-syncs them manually
python manage.py create_business_types

# Install the git pre-commit hook (forbidden-terms check)
bash scripts/install_git_hooks.sh

# Create the superuser
python manage.py createsuperuser

# Run the server
python manage.py runserver
```

---

## Project Structure

```
bananims/
├── PROJECT/          # Django settings
├── apps/
│   ├── core/         # Tenant, middleware, backup, support tickets
│   ├── accounts/     # User, RBAC, permission groups, activity log
│   ├── customers/    # Customers + customer portal
│   ├── suppliers/    # Suppliers
│   ├── items/        # Products, categories, units
│   ├── stocks/       # Warehouses, transfers, stocktaking, write-offs
│   ├── sales/        # Sales, quotes, POS, returns
│   ├── purchases/    # Purchases, RFQ, returns
│   ├── expenses/     # Expenses
│   ├── treasury/     # Treasuries and bank accounts
│   ├── employees/    # Payroll, advances, incentives
│   ├── agents/       # Sales agents, commissions, agent portal
│   ├── notifications/# Smart notifications
│   ├── ai/           # Chat + insights (DeepSeek)
│   ├── store/        # Public online store
│   └── portal/       # Customer portal
├── static/
│   ├── css/          # CSS files (main, layout, dashboard + per-feature)
│   └── js/
├── media/
├── branding/         # App name + logo + favicon — see branding/README.md
└── manage.py
```

### White-labeling

Everything that displays the product name, logo, or favicon (login, register,
password reset, navbar, sidebar, footer, about, pricing, PWA manifest,
transactional emails) reads from the `branding/` folder — see
[`branding/README.md`](branding/README.md). Replacing its contents (and
restarting the service) re-skins the whole app; no template edits needed.

---

## Development Patterns

```python
# Every model inherits TenantMixin — automatic isolation
class Item(TenantMixin):
    name = models.CharField(max_length=300)

# Every sensitive view is permission-protected
@require_permission('add_sale_invoice')
def invoice_create(request): ...

# Every financial/stock mutation goes through services.py only
@transaction.atomic
def confirm_invoice(invoice): ...
```

```javascript
// AJAX only — no native location.reload() or alert()
$.ajax({ url: '/sales/api/', ... success: () => showToast('success', '...') });
```

---

## Product Boundary

BANAN IMS was forked from a sister BANAN edition built for another sector,
and is maintained as a separate product with its own roadmap. It must never
carry that sector's vocabulary or any country-specific positioning — the
exact list lives in `scripts/check_forbidden_terms.py`, which runs as a
pre-commit hook and inside the test suite (`apps/core/tests_forbidden_terms.py`).

Shared-core fixes from the sister edition can be brought over with
`git fetch upstream && git cherry-pick <sha>` (pushing to `upstream` is
disabled).

---

## Platform Admin Dashboard

For superusers and platform staff:
- Tenant management (activate / suspend / renew)
- Revenue, subscription, and activity reports
- Support ticket management
- Audit log
- Backup management

---

**Version:** 1.0 — **Last updated:** October 2026
