"""FinBot - config.py (split de bot.py)."""
import os
import logging
from pathlib import Path


# ════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TEMPLATE_SPREADSHEET_ID = os.environ.get("TEMPLATE_SPREADSHEET_ID", "1m-GTVEJcqzzEBoslIJ5OpeSPj1HJnd3U-6m3JCH_uv8")
ROOT = Path(__file__).resolve().parent.parent      # raiz do repo (este arquivo mora em finbot/)
DB_PATH = ROOT / "finbot.db"                       # raiz, nao finbot/: smart_categorizer aponta pra ca
RENDER_DB_PATH = Path("/tmp/finbot.db")
MASTER_SHEET_ID = os.environ.get("MASTER_SHEET_ID", "1tTn01DomMhi5mrXW9yhrHzyE2-Uo9A85RlM_GsFTjzc")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("FinBot")

# ═══════════════════════════════════════════════════════
# CONVERSATION STATES
# ═══════════════════════════════════════════════════════
(NAME, INCOME, CARDS, GOAL,
 AMOUNT, DESC, CATEGORY, PAYMENT, CARD_SEL, NECESSARY, OBS,
 IS_SUBSCRIPTION, SUBSCRIPTION_NAME, SUBSCRIPTION_VALOR,
 IS_INSTALMENT, INSTALMENT_QTY,
 FIXO_NOME, FIXO_VALOR, FIXO_DIA, FIXO_CATEGORIA,
 PARC_NOME, PARC_TOTAL, PARC_NPARC, PARC_VALOR_PARC, PARC_CATEGORIA,
 META_NOME, META_TARGET, META_CATEGORIA_META,
 BUSCA_TERMO,
 COMPRAS_CATEG, COMPRAS_ITEM, COMPRAS_QTY) = range(32)

CATEGORIES = {
    "alimentacao": "🍽️ Alimentação", "mercado": "🛒 Mercado",
    "moto": "🏍️ Moto", "transporte": "🚌 Transporte",
    "pessoal": "👤 Pessoal", "saude": "🏥 Saúde",
    "assinaturas": "📱 Assinaturas", "dividas": "💰 Dívidas",
    "delivery": "🛵 Delivery", "educacao": "📚 Educação",
    "moradia": "🏠 Moradia", "lazer": "🎮 Lazer",
    "outros": "📦 Outros"
}

PAYMENT_METHODS = {"pix": "💵 Pix", "credito": "💳 Crédito",
                   "debito": "🏧 Débito", "boleto": "📄 Boleto", "dinheiro": "💶 Dinheiro"}

