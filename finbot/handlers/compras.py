"""FinBot - compras.py (split de bot.py)."""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from finbot.db import get_user
from finbot.sheets import append_compra, read_compras, update_compra_cell
from finbot.keyboards import main_menu_keyboard
from finbot.handlers.common import ensure_user


# ═══════════════════════════════════════════════════════
# /compras — Lista de Compras (Google Sheets)
# ═══════════════════════════════════════════════════════
async def cmd_compras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerencia lista de compras via Google Sheets."""
    if not ensure_user(update):
        await update.message.reply_text("Use /start primeiro.")
        return
    args = context.args
    user = get_user(update.effective_user.id)
    sid = user["spreadsheet_id"]

    if not args:
        items = read_compras(sid, apenas_pendentes=True)
        if not items:
            await update.message.reply_text(
                "🛒 *Lista de Compras*\n\n📭 Nenhum item na lista.\n"
                "Use */compras add <item>* para adicionar.",
                parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
            return
        cats = {}
        for it in items:
            cat = it["categoria"]
            if cat not in cats:
                cats[cat] = []
            preco_str = f" (R$ {it['preco']:.2f})" if it['preco'] > 0 else ""
            qty_str = f" ({it['qty']})" if it['qty'] and it['qty'] != "1" else ""
            cats[cat].append(f"• {it['item']}{qty_str}{preco_str}")
        lines = ["🛒 *Lista de Compras*\n"]
        for cat, itens in cats.items():
            icon = "🛒" if cat == "mercado" else "📦" if cat == "online" else "📋"
            lines.append(f"{icon} *{cat.upper()}*:")
            lines.extend(itens)
            lines.append("")
        lines.append(f"📝 Total: {len(items)} itens")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    sub = args[0].lower()

    if sub == "add" and len(args) >= 2:
        item_args = args[1:]
        cat = "mercado"
        qty = "1"
        preco = 0.0
        if item_args[0].lower() in ("mercado", "online", "farmacia", "casa", "outros"):
            cat = item_args[0].lower()
            item_args = item_args[1:]
        if item_args and item_args[-1].lower().endswith("x"):
            try:
                q = int(item_args[-1][:-1])
                if q > 0:
                    qty = str(q)
                    item_args = item_args[:-1]
            except ValueError:
                pass
        if item_args and item_args[-1].startswith("R$"):
            try:
                preco = float(item_args[-1][2:].replace(",", "."))
                item_args = item_args[:-1]
            except ValueError:
                pass
        elif item_args:
            try:
                preco = float(item_args[-1].replace(",", "."))
                item_args = item_args[:-1]
            except (ValueError, IndexError):
                pass
        item = " ".join(item_args) if item_args else "item"
        items = read_compras(sid, apenas_pendentes=False)
        cod = str(len(items) + 1)
        append_compra(sid, [cod, item, qty, cat, preco, "NAO", datetime.now().strftime("%d/%m/%Y")])
        preco_str = f" — R$ {preco:.2f}" if preco > 0 else ""
        await update.message.reply_text(
            f"✅ Adicionado: *{item}* ({cat}){preco_str}",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )

    elif sub == "rm" and len(args) >= 2:
        try:
            idx = int(args[1]) - 1
        except ValueError:
            await update.message.reply_text("❌ Use: /compras rm <número>")
            return
        items = read_compras(sid, apenas_pendentes=True)
        if 0 <= idx < len(items):
            row_idx = idx + 2  # +2 para cabeçalho
            update_compra_cell(sid, row_idx, "G", "SIM")  # Marca como comprado
            await update.message.reply_text(f"🗑️ Removido: *{items[idx]['item']}*", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"❌ Item #{args[1]} não encontrado.")

    elif sub == "comprado" and len(args) >= 2:
        try:
            idx = int(args[1]) - 1
        except ValueError:
            await update.message.reply_text("❌ Use: /compras comprado <número>")
            return
        items = read_compras(sid, apenas_pendentes=True)
        if 0 <= idx < len(items):
            row_idx = idx + 2
            update_compra_cell(sid, row_idx, "F", "SIM")
            await update.message.reply_text(f"✅ Comprado: *{items[idx]['item']}* 🎉", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"❌ Item #{args[1]} não encontrado.")

    else:
        await update.message.reply_text(
            "🛒 *Compras*\n\n"
            "*/compras* — Ver lista\n"
            "*/compras add mercado leite 2x* — Adicionar\n"
            "*/compras add online kindle 200* — Com preço\n"
            "*/compras rm 1* — Remover\n"
            "*/compras comprado 1* — Marcar como comprado",
            parse_mode="Markdown"
        )

