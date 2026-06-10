# Bot Financeiro Telegram + Google Sheets

Bot para lançamentos financeiros via Telegram, integrado ao Google Sheets.

## Comandos
- `/gasto <valor> <descrição> <categoria> [pagamento] [cartão]`
- `/resumo` — Resumo financeiro
- `/fixos` — Gastos fixos mensais
- `/parcelas` — Parcelamentos
- `/limite` — Saldo livre
- `/categorias` — Gastos por categoria

## Deploy no Render (grátis)

1. Crie conta em https://render.com
2. New → Web Service → Connect GitHub repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python bot.py`
5. Environment variables:
   - `TELEGRAM_BOT_TOKEN` — Token do @BotFather
