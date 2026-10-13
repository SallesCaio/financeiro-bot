"""FinBot - sheets.py (split de bot.py)."""
from finbot.config import MASTER_SHEET_ID, TEMPLATE_SPREADSHEET_ID, logger
from finbot.auth import get_drive_service, get_sheets_service
from finbot.db import upsert_user


# ═══════════════════════════════════════════════════════
# HELPER: converte valor da planilha para float
# ═══════════════════════════════════════════════════════
def parse_float(val) -> float:
    """Converte valor BR para float: 1.234,56 → 1234.56, 3000.0 → 3000.0"""
    if val is None:
        return 0.0
    try:
        s = str(val).replace("R$", "").strip()
        # Se tem vírgula: formato BR (1.234,56) — troca última vírgula por ponto, remove pontos
        if "," in s:
            s = s.replace(".", "")       # remove separador milhar
            s = s.replace(",", ".")      # vírgula → ponto decimal
        # Se não tem vírgula: formato EN (3000.0) — só converte direto
        return float(s)
    except (ValueError, TypeError):
        return 0.0
# ═══════════════════════════════════════════════════════
# GOOGLE SHEETS — Master Sheet (persistência)
# ═══════════════════════════════════════════════════════
MASTER_USERS_RANGE = "USERS!A:H"

def ensure_master_sheet():
    svc = get_sheets_service()
    try:
        meta = svc.spreadsheets().get(spreadsheetId=MASTER_SHEET_ID).execute()
        sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]
        if "USERS" not in sheets:
            svc.spreadsheets().batchUpdate(spreadsheetId=MASTER_SHEET_ID, body={
                "requests": [{"addSheet": {"properties": {"title": "USERS"}}}]
            }).execute()
            svc.spreadsheets().values().update(
                spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE,
                valueInputOption="USER_ENTERED",
                body={"values": [["user_id","username","first_name","name","income","cards","goal","spreadsheet_id"]]}
            ).execute()
            logger.info("Master Sheet USERS created")
    except Exception as e:
        logger.error(f"Erro master sheet: {e}")

def sync_users_from_master():
    svc = get_sheets_service()
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE
        ).execute()
        rows = result.get("values", [])
        if len(rows) <= 1:
            return 0
        count = 0
        for row in rows[1:]:
            if len(row) >= 8 and row[0]:
                try:
                    uid = int(row[0])
                    upsert_user(uid,
                        username=row[1] if len(row)>1 else "",
                        first_name=row[2] if len(row)>2 else "",
                        name=row[3] if len(row)>3 else "",
                        income=parse_float(row[4]) if row[4] else 0,
                        cards=row[5] if len(row)>5 else "",
                        goal=row[6] if len(row)>6 else "",
                        spreadsheet_id=row[7] if len(row)>7 else "",
                        onboarding_done=1)
                    count += 1
                except (ValueError, IndexError):
                    continue
        logger.info(f"Synced {count} users from master sheet")
        return count
    except Exception as e:
        logger.error(f"Erro sync master: {e}")
        return 0

def save_user_to_master(user_id: int, username: str, first_name: str, name: str,
                        income: float, cards: str, goal: str, spreadsheet_id: str):
    ensure_master_sheet()
    svc = get_sheets_service()
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE
        ).execute()
        rows = result.get("values", [])
        user_str = str(user_id)
        found_row = None
        for i, row in enumerate(rows):
            if row and row[0] == user_str:
                found_row = i + 1
                break
        new_row = [user_str, username, first_name, name, str(income), cards, goal, spreadsheet_id]
        if found_row:
            svc.spreadsheets().values().update(
                spreadsheetId=MASTER_SHEET_ID, range=f"USERS!A{found_row}:H{found_row}",
                valueInputOption="USER_ENTERED", body={"values": [new_row]}
            ).execute()
        else:
            svc.spreadsheets().values().append(
                spreadsheetId=MASTER_SHEET_ID, range=MASTER_USERS_RANGE,
                valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
                body={"values": [new_row]}
            ).execute()
    except Exception as e:
        logger.error(f"Erro save user to master: {e}")

# ═══════════════════════════════════════════════════════
# GOOGLE SHEETS — Operações na planilha do usuário
# ═══════════════════════════════════════════════════════
def create_user_spreadsheet(user_name: str) -> str:
    drive_svc = get_drive_service()
    copy = drive_svc.files().copy(
        fileId=TEMPLATE_SPREADSHEET_ID, body={"name": f"FinBot - {user_name}"}
    ).execute()
    return copy["id"]

def get_or_create_month_sheet(spreadsheet_id: str, year_month: str) -> str:
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == year_month:
            return year_month
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": year_month}}}]
    }).execute()
    headers = [["DATA","DESCRIÇÃO","CATEGORIA","SUBCATEGORIA","PAGAMENTO","VALOR","CARTÃO","NECESSÁRIO?","TIPO","OBS"]]
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{year_month}!A1:J1",
        valueInputOption="USER_ENTERED", body={"values": headers}
    ).execute()
    return year_month

def append_gasto(spreadsheet_id: str, year_month: str, row: list):
    svc = get_sheets_service()
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range=f"{year_month}!A:J",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

def read_range(spreadsheet_id: str, range_str: str):
    svc = get_sheets_service()
    r = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_str).execute()
    return r.get("values", [])

# ── FATURAS ──
# Estrutura: CARTÃO | REF_MÊS | TOTAL | VENCIMENTO | PAGO | VALOR_PAGO | DATA_PAGAMENTO | OBS
# Vencimento padrão: dia 08 de cada mês
# REF_MÊS: YYYY-MM da fatura (mês de referência, não mês de pagamento)

VENCIMENTO_DIA = 8  # Dia de vencimento de todas as faturas

def _calc_vencimento(ref_month: str) -> str:
    """Calcula data de vencimento: dia 08 do mês seguinte ao ref_month."""
    y, m = map(int, ref_month.split("-"))
    if m == 12:
        next_m, next_y = 1, y + 1
    else:
        next_m, next_y = m + 1, y
    return f"{VENCIMENTO_DIA:02d}/{next_m:02d}/{next_y}"

def _calc_prox_ref_month(ref_month: str) -> str:
    """Calcula o próximo mês de referência (para parcelamentos)."""
    y, m = map(int, ref_month.split("-"))
    if m == 12:
        return f"{y + 1}-01"
    return f"{y}-{m + 1:02d}"

def get_fatura_row(spreadsheet_id: str, cartao: str, ref_month: str):
    """Busca fatura por cartão + mês de referência."""
    svc = get_sheets_service()
    ensure_fatura_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="FATURAS!A1:H50").execute()
    values = result.get("values", [])
    if not values:
        return None
    for idx, row in enumerate(values[1:], start=2):
        if len(row) >= 2 and row[0] == cartao and row[1] == ref_month:
            return idx, row
    return None

def get_or_create_fatura(spreadsheet_id: str, cartao: str, ref_month: str):
    """Busca fatura ou cria nova se não existir."""
    existing = get_fatura_row(spreadsheet_id, cartao, ref_month)
    if existing:
        return existing
    # Criar nova fatura
    svc = get_sheets_service()
    ensure_fatura_sheet(spreadsheet_id)
    venc = _calc_vencimento(ref_month)
    new_row = [cartao, ref_month, "0.00", venc, "NAO", "0.00", "", ""]
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="FATURAS!A1:H50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [new_row]}
    ).execute()
    # Retornar a linha criada
    return get_fatura_row(spreadsheet_id, cartao, ref_month)

def update_fatura_total(spreadsheet_id: str, cartao: str, ref_month: str, valor_adicional: float):
    """Soma valor ao TOTAL da fatura. Criar fatura se não existir."""
    existing = get_or_create_fatura(spreadsheet_id, cartao, ref_month)
    if not existing:
        return
    row_idx, row_data = existing
    cur_total = parse_float(row_data[2]) if len(row_data) > 2 and row_data[2] else 0.0
    novo_total = cur_total + valor_adicional
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"FATURAS!C{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[f"{novo_total:.2f}"]]}
    ).execute()

def update_fatura_cell(spreadsheet_id: str, row_idx: int, col_letter: str, value):
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"FATURAS!{col_letter}{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[value]]}
    ).execute()

def append_fatura_row(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_fatura_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="FATURAS!A1:H50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

# ── FIXOS ──
def read_fixos(spreadsheet_id: str) -> list:
    svc = get_sheets_service()
    ensure_fixos_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="FIXOS!A1:F50").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if len(row) >= 1 and row[0]:
            items.append({
                "nome": row[0], "valor": parse_float(row[1]) if row[1] else 0,
                "dia": row[2] if len(row)>2 else "", "categoria": row[3] if len(row)>3 else "outros",
                "ativo": row[4].upper()=="SIM" if len(row)>4 else True,
                "obs": row[5] if len(row)>5 else ""
            })
    return items

def append_fixo(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_fixos_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="FIXOS!A1:F50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

# ── PARCELAMENTOS ──
# Cache global de abas já verificadas (evita chamadas API repetidas)
_sheets_cache = {}

def _sheet_exists(spreadsheet_id, sheet_name):
    """Verifica se aba existe usando cache."""
    key = f"{spreadsheet_id}:{sheet_name}"
    if key in _sheets_cache:
        return _sheets_cache[key]
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    exists = any(s["properties"]["title"] == sheet_name for s in meta.get("sheets", []))
    _sheets_cache[key] = exists
    return exists

def ensure_parcelas_sheet(spreadsheet_id: str):
    """Cria aba PARCELAMENTOS se não existir. Usa cache."""
    if _sheet_exists(spreadsheet_id, "PARCELAMENTOS"):
        return
    svc = get_sheets_service()
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "PARCELAMENTOS", "gridProperties": {"rowCount": 100, "columnCount": 8}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="PARCELAMENTOS!A1:H1",
        valueInputOption="USER_ENTERED",
        body={"values": [["COD","DESCRICAO","VALOR_PARCELA","TOTAL_PARCELAS","PAGAS","RESTANTES","VALOR_PAGO","VALOR_RESTANTE"]]}
    ).execute()
    _sheets_cache[f"{spreadsheet_id}:PARCELAMENTOS"] = True

def ensure_fixos_sheet(spreadsheet_id: str):
    """Cria aba FIXOS se não existir. Usa cache."""
    if _sheet_exists(spreadsheet_id, "FIXOS"):
        return
    svc = get_sheets_service()
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "FIXOS", "gridProperties": {"rowCount": 100, "columnCount": 6}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="FIXOS!A1:F1",
        valueInputOption="USER_ENTERED",
        body={"values": [["NOME","VALOR","DIA_VENCIMENTO","CATEGORIA","ATIVO","OBS"]]}
    ).execute()
    _sheets_cache[f"{spreadsheet_id}:FIXOS"] = True

def ensure_fatura_sheet(spreadsheet_id: str):
    """Cria aba FATURAS se não existir. Usa cache."""
    if _sheet_exists(spreadsheet_id, "FATURAS"):
        return
    svc = get_sheets_service()
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "FATURAS", "gridProperties": {"rowCount": 100, "columnCount": 8}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="FATURAS!A1:H1",
        valueInputOption="USER_ENTERED",
        body={"values": [["CARTÃO","REF_MÊS","TOTAL","VENCIMENTO","PAGO","VALOR_PAGO","DATA_PAGAMENTO","OBS"]]}
    ).execute()
    _sheets_cache[f"{spreadsheet_id}:FATURAS"] = True

def read_parcelas(spreadsheet_id: str) -> list:
    svc = get_sheets_service()
    ensure_parcelas_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="PARCELAMENTOS!A1:H50").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if len(row) >= 1 and row[0]:
            cod = row[0]
            descricao = row[1] if len(row) > 1 else ""
            valor_parcela = parse_float(row[2]) if len(row) > 2 and row[2] else 0
            total_parcelas = int(parse_float(row[3])) if len(row) > 3 and row[3] else 0
            pagas = int(parse_float(row[4])) if len(row) > 4 and row[4] else 0
            restantes = int(parse_float(row[5])) if len(row) > 5 and row[5] else (total_parcelas - pagas)
            valor_pago = parse_float(row[6]) if len(row) > 6 and row[6] else (valor_parcela * pagas)
            valor_restante = parse_float(row[7]) if len(row) > 7 and row[7] else (valor_parcela * restantes)
            items.append({
                "cod": cod, "descricao": descricao, "valor_parcela": valor_parcela,
                "total_parcelas": total_parcelas, "pagas": pagas, "restantes": restantes,
                "valor_pago": valor_pago, "valor_restante": valor_restante
            })
    return items

def append_parcela(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_parcelas_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="PARCELAMENTOS!A1:H50",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

def update_parcela_cell(spreadsheet_id: str, row_idx: int, col: str, value):
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"PARCELAMENTOS!{col}{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[value]]}
    ).execute()

# ── COMPRAS (Google Sheets) ──
def ensure_compras_sheet(spreadsheet_id: str):
    """Cria aba COMPRAS no Sheets para persistência."""
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if "COMPRAS" in sheets:
        return
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "COMPRAS", "gridProperties": {"rowCount": 500, "columnCount": 7}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="COMPRAS!A1:G1",
        valueInputOption="USER_ENTERED",
        body={"values": [["COD","ITEM","QTY","CATEGORIA","PRECO","COMPRADO","DATA"]]}
    ).execute()

def read_compras(spreadsheet_id: str, apenas_pendentes=True) -> list:
    svc = get_sheets_service()
    ensure_compras_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="COMPRAS!A:G").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        comprado = row[5].upper() == "SIM" if len(row) > 5 else False
        if apenas_pendentes and comprado:
            continue
        items.append({
            "cod": row[0], "item": row[1] if len(row) > 1 else "",
            "qty": row[2] if len(row) > 2 else "1",
            "categoria": row[3] if len(row) > 3 else "outros",
            "preco": parse_float(row[4]) if len(row) > 4 and row[4] else 0,
            "comprado": comprado,
            "data": row[6] if len(row) > 6 else ""
        })
    return items

def append_compra(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_compras_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="COMPRAS!A:G",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

def update_compra_cell(spreadsheet_id: str, row_idx: int, col: str, value):
    svc = get_sheets_service()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"COMPRAS!{col}{row_idx}",
        valueInputOption="USER_ENTERED", body={"values": [[value]]}
    ).execute()
def ensure_metas_sheet(spreadsheet_id: str):
    svc = get_sheets_service()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    if any(s["properties"]["title"] == "METAS" for s in meta.get("sheets", [])):
        return
    svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={
        "requests": [{"addSheet": {"properties": {"title": "METAS", "gridProperties": {"rowCount": 500, "columnCount": 6}}}}]
    }).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="METAS!A1:F1",
        valueInputOption="USER_ENTERED",
        body={"values": [["NOME","META","ATUAL","CATEGORIA","MENSAL","ATIVO"]]}
    ).execute()

def read_metas(spreadsheet_id: str) -> list:
    svc = get_sheets_service()
    ensure_metas_sheet(spreadsheet_id)
    result = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="METAS!A:F").execute()
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    items = []
    for row in rows[1:]:
        if len(row) >= 2 and row[0]:
            items.append({
                "nome": row[0], "meta": parse_float(row[1]) if row[1] else 0,
                "atual": parse_float(row[2]) if len(row)>2 and row[2] else 0,
                "categoria": row[3] if len(row)>3 else "",
                "mensal": row[4].upper()=="SIM" if len(row)>4 else False,
                "ativo": row[5].upper()=="SIM" if len(row)>5 else True
            })
    return items

def append_meta(spreadsheet_id: str, row: list):
    svc = get_sheets_service()
    ensure_metas_sheet(spreadsheet_id)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range="METAS!A:F",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()

