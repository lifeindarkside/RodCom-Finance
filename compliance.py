import io
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from database import AsyncSessionLocal
from models import Transaction, Collection, User, AuditLog
from config import JWT_SECRET, JWT_ALGORITHM

router = APIRouter(prefix="/api/compliance", tags=["compliance"])
_security = HTTPBearer(auto_error=False)


async def _get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    db: AsyncSession = Depends(_get_db),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Недействительный токен")
    user_id = int(payload.get("sub"))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return {"sub": str(user.id), "tid": user.telegram_id, "role": user.role, "name": user.name}


def _require_role(*roles):
    async def checker(user=Depends(_get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user
    return checker

MONEY_FMT = '#,##0.00 "₽"'
HEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
HEADER_FONT = Font(name="Calibri", bold=True, size=11)
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
TITLE_FONT = Font(name="Calibri", bold=True, size=14)
SUBTITLE_FONT = Font(name="Calibri", bold=True, size=12)
SECTION_FONT = Font(name="Calibri", bold=True, size=11, color="1F4E79")
BODY_FONT = Font(name="Calibri", size=11)
WRAP_ALIGN = Alignment(wrap_text=True, vertical="top")


def parse_date(date_str: str, param_name: str) -> date:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Неверный формат даты '{param_name}': ожидается YYYY-MM-DD")


def _style_header_row(ws, row_num: int, col_count: int):
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row_num, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _style_data_cell(cell, is_money=False):
    cell.border = THIN_BORDER
    cell.font = BODY_FONT
    if is_money:
        cell.number_format = MONEY_FMT
        cell.alignment = Alignment(horizontal="right")


def _build_summary_sheet(ws, transactions, date_from: date, date_to: date, collections_map: dict, users_map: dict):
    ws.title = "Сводка"

    # Title
    ws.merge_cells("A1:F1")
    title_cell = ws["A1"]
    title_cell.value = "Финансовый отчёт родительского комитета"
    title_cell.font = TITLE_FONT
    title_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:F2")
    period_cell = ws["A2"]
    period_cell.value = f"Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}"
    period_cell.font = Font(name="Calibri", size=11, italic=True)
    period_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells("A3:F3")
    gen_cell = ws["A3"]
    gen_cell.value = f"Дата формирования: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    gen_cell.font = Font(name="Calibri", size=10, color="666666")
    gen_cell.alignment = Alignment(horizontal="center")

    # Summary stats
    total_income = sum(t.amount for t in transactions if t.type == "income")
    total_expense = sum(t.amount for t in transactions if t.type == "expense")
    balance = total_income - total_expense

    row = 5
    ws.cell(row=row, column=1, value="Показатель").font = HEADER_FONT
    ws.cell(row=row, column=2, value="Сумма").font = HEADER_FONT
    for c in range(1, 3):
        ws.cell(row=row, column=c).fill = HEADER_FILL
        ws.cell(row=row, column=c).border = THIN_BORDER

    for label, val in [
        ("Всего поступлений", total_income),
        ("Всего расходов", total_expense),
        ("Баланс (остаток)", balance),
    ]:
        row += 1
        c1 = ws.cell(row=row, column=1, value=label)
        c1.font = BODY_FONT
        c1.border = THIN_BORDER
        c2 = ws.cell(row=row, column=2, value=val)
        _style_data_cell(c2, is_money=True)
        if label == "Баланс (остаток)":
            c2.font = Font(name="Calibri", bold=True, size=11, color="006600" if val >= 0 else "CC0000")

    row += 1
    c1 = ws.cell(row=row, column=1, value="Количество операций")
    c1.font = BODY_FONT
    c1.border = THIN_BORDER
    c2 = ws.cell(row=row, column=2, value=len(transactions))
    c2.border = THIN_BORDER

    # Income by collection
    row += 2
    ws.cell(row=row, column=1, value="Поступления по сборам").font = SUBTITLE_FONT
    row += 1
    ws.cell(row=row, column=1, value="Сбор").font = HEADER_FONT
    ws.cell(row=row, column=2, value="Сумма").font = HEADER_FONT
    ws.cell(row=row, column=3, value="Кол-во взносов").font = HEADER_FONT
    for c in range(1, 4):
        ws.cell(row=row, column=c).fill = HEADER_FILL
        ws.cell(row=row, column=c).border = THIN_BORDER

    income_by_coll = {}
    for t in transactions:
        if t.type == "income":
            coll_name = collections_map.get(t.collection_id, "Без сбора")
            if coll_name not in income_by_coll:
                income_by_coll[coll_name] = {"amount": 0, "count": 0}
            income_by_coll[coll_name]["amount"] += t.amount
            income_by_coll[coll_name]["count"] += 1

    for coll_name, data in sorted(income_by_coll.items(), key=lambda x: -x[1]["amount"]):
        row += 1
        c1 = ws.cell(row=row, column=1, value=coll_name)
        c1.border = THIN_BORDER
        c2 = ws.cell(row=row, column=2, value=data["amount"])
        _style_data_cell(c2, is_money=True)
        c3 = ws.cell(row=row, column=3, value=data["count"])
        c3.border = THIN_BORDER
        c3.alignment = Alignment(horizontal="center")

    # Expense by category
    row += 2
    ws.cell(row=row, column=1, value="Расходы по категориям").font = SUBTITLE_FONT
    row += 1
    ws.cell(row=row, column=1, value="Категория").font = HEADER_FONT
    ws.cell(row=row, column=2, value="Сумма").font = HEADER_FONT
    ws.cell(row=row, column=3, value="Доля, %").font = HEADER_FONT
    for c in range(1, 4):
        ws.cell(row=row, column=c).fill = HEADER_FILL
        ws.cell(row=row, column=c).border = THIN_BORDER

    expense_by_cat = {}
    for t in transactions:
        if t.type == "expense":
            cat = t.category or "Прочее"
            expense_by_cat[cat] = expense_by_cat.get(cat, 0) + t.amount

    for cat, amt in sorted(expense_by_cat.items(), key=lambda x: -x[1]):
        row += 1
        c1 = ws.cell(row=row, column=1, value=cat)
        c1.border = THIN_BORDER
        c2 = ws.cell(row=row, column=2, value=amt)
        _style_data_cell(c2, is_money=True)
        pct = round(amt / total_expense * 100, 1) if total_expense > 0 else 0
        c3 = ws.cell(row=row, column=3, value=pct)
        c3.border = THIN_BORDER
        c3.number_format = "0.0"
        c3.alignment = Alignment(horizontal="center")

    # Column widths
    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 18

    # Print settings
    ws.print_area = f"A1:C{row}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _build_operations_sheet(ws, transactions, collections_map: dict, users_map: dict):
    ws.title = "Все операции"

    headers = [
        "№", "Дата", "Тип", "Сумма", "За кого (ФИО ребёнка)",
        "Сбор", "Категория", "Описание", "Записал(а)"
    ]
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)
    _style_header_row(ws, 1, len(headers))

    for i, t in enumerate(transactions, 1):
        row = i + 1
        type_label = "Поступление" if t.type == "income" else "Расход"
        coll_name = collections_map.get(t.collection_id, "")
        user_name = users_map.get(t.created_by, "")
        tx_date = t.date.strftime("%d.%m.%Y") if t.date else ""

        values = [
            i, tx_date, type_label, t.amount,
            t.payer_name or "", coll_name,
            t.category or "", t.description or "", user_name
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            _style_data_cell(cell, is_money=(col == 4))

    # Totals row
    if transactions:
        total_row = len(transactions) + 2
        ws.cell(row=total_row, column=1, value="ИТОГО").font = Font(name="Calibri", bold=True, size=11)
        ws.cell(row=total_row, column=1).border = THIN_BORDER

        total_income = sum(t.amount for t in transactions if t.type == "income")
        total_expense = sum(t.amount for t in transactions if t.type == "expense")
        total_cell = ws.cell(row=total_row, column=4, value=total_income - total_expense)
        _style_data_cell(total_cell, is_money=True)
        total_cell.font = Font(name="Calibri", bold=True, size=11)

        for col in range(2, len(headers) + 1):
            ws.cell(row=total_row, column=col).border = THIN_BORDER

    # Column widths
    widths = [5, 12, 14, 16, 28, 24, 18, 30, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Print settings
    last_row = len(transactions) + 2
    ws.print_area = f"A1:{get_column_letter(len(headers))}{last_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:1"


def _build_legal_sheet(ws):
    ws.title = "Правовое обоснование"

    ws.column_dimensions["A"].width = 100

    sections = [
        ("ПРАВОВОЕ ОБОСНОВАНИЕ ФИНАНСОВОЙ ОТЧЁТНОСТИ РОДИТЕЛЬСКОГО КОМИТЕТА", None, TITLE_FONT),
        ("", None, None),
        ("1. Правовой статус родительского комитета", None, SECTION_FONT),
        (
            "Родительский комитет действует на основании ст. 26 Федерального закона "
            "от 29.12.2012 № 273-ФЗ «Об образовании в Российской Федерации». "
            "Родительский комитет является формой участия родителей (законных представителей) "
            "в управлении образовательной организацией. Деятельность комитета носит "
            "добровольный характер и основывается на принципах открытости и прозрачности.",
            None, BODY_FONT
        ),
        ("", None, None),
        ("2. Добровольность взносов", None, SECTION_FONT),
        (
            "В соответствии с п. 2 ст. 582 ГК РФ и Письмом Минобрнауки РФ от 09.09.2015 "
            "№ ВК-2227/08, все взносы родителей являются исключительно добровольными. "
            "Принуждение к внесению денежных средств не допускается. Каждый родитель "
            "самостоятельно принимает решение об участии в финансировании мероприятий "
            "и нужд класса/группы.",
            None, BODY_FONT
        ),
        ("", None, None),
        ("3. Требования к ведению учёта (115-ФЗ)", None, SECTION_FONT),
        (
            "Федеральный закон от 07.08.2001 № 115-ФЗ «О противодействии легализации "
            "(отмыванию) доходов, полученных преступным путём, и финансированию терроризма» "
            "устанавливает требования к идентификации и учёту операций. Хотя родительский "
            "комитет не является субъектом закона напрямую, ведение прозрачного учёта "
            "соответствует духу закона и является лучшей практикой для обеспечения "
            "доверия всех участников.",
            None, BODY_FONT
        ),
        ("", None, None),
        ("4. Обязательные элементы учёта", None, SECTION_FONT),
        (
            "Для обеспечения прозрачности финансовой деятельности рекомендуется фиксировать:\n"
            "- ФИО ребёнка, за которого вносится оплата (для идентификации плательщика);\n"
            "- Дату и сумму каждой операции;\n"
            "- Целевое назначение (сбор/мероприятие);\n"
            "- Категорию расхода;\n"
            "- Подтверждающие документы (чеки, квитанции);\n"
            "- Сведения о лице, внёсшем запись.",
            None, BODY_FONT
        ),
        ("", None, None),
        ("5. Хранение и защита данных", None, SECTION_FONT),
        (
            "Обработка персональных данных осуществляется в соответствии с Федеральным "
            "законом от 27.07.2006 № 152-ФЗ «О персональных данных». Данные используются "
            "исключительно в целях ведения финансового учёта родительского комитета. "
            "Доступ к данным ограничен кругом уполномоченных лиц (казначей, председатель).",
            None, BODY_FONT
        ),
        ("", None, None),
        ("6. Отчётность", None, SECTION_FONT),
        (
            "Родительский комитет обязан периодически отчитываться перед родителями "
            "о расходовании собранных средств (п. 3 ст. 26 273-ФЗ). Настоящий отчёт "
            "формируется автоматически на основании данных системы учёта и включает:\n"
            "- Сводную информацию по доходам и расходам;\n"
            "- Детализированный перечень всех операций;\n"
            "- Разбивку по сборам и категориям расходов.",
            None, BODY_FONT
        ),
        ("", None, None),
        ("7. Ответственность", None, SECTION_FONT),
        (
            "Казначей родительского комитета несёт ответственность за корректность "
            "ведения учёта и сохранность подтверждающих документов. В случае выявления "
            "нарушений применяются нормы гражданского законодательства РФ (ГК РФ, "
            "ст. 1064 — возмещение вреда).\n\n"
            "Настоящий документ подготовлен для информационных целей и не является "
            "юридической консультацией.",
            None, BODY_FONT
        ),
    ]

    for i, (text, _, font) in enumerate(sections, 1):
        cell = ws.cell(row=i, column=1, value=text)
        if font:
            cell.font = font
        cell.alignment = WRAP_ALIGN

    # Print settings
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True


async def _get_transactions(db: AsyncSession, date_from: date, date_to: date):
    dt_from = datetime.combine(date_from, datetime.min.time())
    dt_to = datetime.combine(date_to, datetime.max.time())

    q = (
        select(Transaction)
        .where(Transaction.date >= dt_from, Transaction.date <= dt_to)
        .order_by(Transaction.date)
    )
    result = await db.execute(q)
    return result.scalars().all()


async def _get_maps(db: AsyncSession, transactions):
    coll_ids = set(t.collection_id for t in transactions if t.collection_id)
    user_ids = set(t.created_by for t in transactions if t.created_by)

    collections_map = {}
    if coll_ids:
        res = await db.execute(select(Collection).where(Collection.id.in_(coll_ids)))
        for c in res.scalars().all():
            collections_map[c.id] = c.name

    users_map = {}
    if user_ids:
        res = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in res.scalars().all():
            users_map[u.id] = u.name

    return collections_map, users_map


@router.get("/summary")
async def compliance_summary(
    date_from: str = Query(..., description="Дата начала (YYYY-MM-DD)"),
    date_to: str = Query(..., description="Дата окончания (YYYY-MM-DD)"),
    user=Depends(_require_role("admin", "treasurer")),
    db: AsyncSession = Depends(_get_db),
):
    d_from = parse_date(date_from, "date_from")
    d_to = parse_date(date_to, "date_to")

    transactions = await _get_transactions(db, d_from, d_to)

    total_income = sum(t.amount for t in transactions if t.type == "income")
    total_expense = sum(t.amount for t in transactions if t.type == "expense")

    expense_by_cat = {}
    for t in transactions:
        if t.type == "expense":
            cat = t.category or "Прочее"
            expense_by_cat[cat] = expense_by_cat.get(cat, 0) + t.amount

    return {
        "period": {"from": date_from, "to": date_to},
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": total_income - total_expense,
        "transaction_count": len(transactions),
        "expense_by_category": [
            {"category": cat, "amount": amt}
            for cat, amt in sorted(expense_by_cat.items(), key=lambda x: -x[1])
        ],
    }


@router.get("/transactions")
async def compliance_transactions(
    date_from: str = Query(..., description="Дата начала (YYYY-MM-DD)"),
    date_to: str = Query(..., description="Дата окончания (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user=Depends(_require_role("admin", "treasurer")),
    db: AsyncSession = Depends(_get_db),
):
    d_from = parse_date(date_from, "date_from")
    d_to = parse_date(date_to, "date_to")

    dt_from = datetime.combine(d_from, datetime.min.time())
    dt_to = datetime.combine(d_to, datetime.max.time())

    count_q = select(func.count(Transaction.id)).where(
        Transaction.date >= dt_from, Transaction.date <= dt_to
    )
    total = (await db.execute(count_q)).scalar()

    q = (
        select(Transaction)
        .where(Transaction.date >= dt_from, Transaction.date <= dt_to)
        .order_by(Transaction.date)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(q)
    transactions = result.scalars().all()

    collections_map, users_map = await _get_maps(db, transactions)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
        "items": [
            {
                "id": t.id,
                "date": t.date.isoformat() if t.date else None,
                "type": t.type,
                "amount": t.amount,
                "payer_name": t.payer_name or "",
                "collection_name": collections_map.get(t.collection_id, ""),
                "category": t.category or "",
                "description": t.description or "",
                "created_by_name": users_map.get(t.created_by, ""),
            }
            for t in transactions
        ],
    }


@router.get("/export")
async def compliance_export(
    date_from: str = Query(..., description="Дата начала (YYYY-MM-DD)"),
    date_to: str = Query(..., description="Дата окончания (YYYY-MM-DD)"),
    user=Depends(_require_role("admin", "treasurer")),
    db: AsyncSession = Depends(_get_db),
):
    d_from = parse_date(date_from, "date_from")
    d_to = parse_date(date_to, "date_to")

    transactions = await _get_transactions(db, d_from, d_to)

    if not transactions:
        raise HTTPException(status_code=404, detail="Нет операций за указанный период")

    collections_map, users_map = await _get_maps(db, transactions)

    wb = Workbook()
    ws_summary = wb.active
    _build_summary_sheet(ws_summary, transactions, d_from, d_to, collections_map, users_map)

    ws_operations = wb.create_sheet()
    _build_operations_sheet(ws_operations, transactions, collections_map, users_map)

    ws_legal = wb.create_sheet()
    _build_legal_sheet(ws_legal)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    # Audit log
    entry = AuditLog(
        user_id=int(user["sub"]),
        action="export",
        entity_type="compliance",
        details=f"Экспорт отчёта {d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}, {len(transactions)} операций",
    )
    db.add(entry)
    await db.commit()

    filename = f"financial_report_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/collections-summary")
async def compliance_collections_summary(
    date_from: str = Query(..., description="Дата начала (YYYY-MM-DD)"),
    date_to: str = Query(..., description="Дата окончания (YYYY-MM-DD)"),
    user=Depends(_require_role("admin", "treasurer")),
    db: AsyncSession = Depends(_get_db),
):
    d_from = parse_date(date_from, "date_from")
    d_to = parse_date(date_to, "date_to")

    transactions = await _get_transactions(db, d_from, d_to)
    collections_map, _ = await _get_maps(db, transactions)

    coll_data = {}
    for t in transactions:
        coll_name = collections_map.get(t.collection_id, "Без сбора")
        cid = t.collection_id or 0
        if cid not in coll_data:
            coll_data[cid] = {"name": coll_name, "income": 0, "expense": 0, "count": 0}
        if t.type == "income":
            coll_data[cid]["income"] += t.amount
        else:
            coll_data[cid]["expense"] += t.amount
        coll_data[cid]["count"] += 1

    return [
        {
            "collection_id": cid,
            "name": data["name"],
            "income": data["income"],
            "expense": data["expense"],
            "balance": data["income"] - data["expense"],
            "count": data["count"],
        }
        for cid, data in sorted(coll_data.items(), key=lambda x: -(x[1]["income"] + x[1]["expense"]))
    ]


@router.get("/payers")
async def compliance_payers(
    date_from: str = Query(..., description="Дата начала (YYYY-MM-DD)"),
    date_to: str = Query(..., description="Дата окончания (YYYY-MM-DD)"),
    user=Depends(_require_role("admin", "treasurer")),
    db: AsyncSession = Depends(_get_db),
):
    d_from = parse_date(date_from, "date_from")
    d_to = parse_date(date_to, "date_to")

    transactions = await _get_transactions(db, d_from, d_to)
    collections_map, _ = await _get_maps(db, transactions)

    payer_data = {}
    for t in transactions:
        if t.type == "income" and t.payer_name:
            name = t.payer_name
            if name not in payer_data:
                payer_data[name] = {"total": 0, "count": 0, "collections": set()}
            payer_data[name]["total"] += t.amount
            payer_data[name]["count"] += 1
            if t.collection_id:
                coll_name = collections_map.get(t.collection_id, "")
                if coll_name:
                    payer_data[name]["collections"].add(coll_name)

    return [
        {
            "payer_name": name,
            "total": data["total"],
            "count": data["count"],
            "collections": sorted(data["collections"]),
        }
        for name, data in sorted(payer_data.items(), key=lambda x: -x[1]["total"])
    ]
