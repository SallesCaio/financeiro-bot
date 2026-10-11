#!/usr/bin/env python3
"""FinBot - entrypoint. Render sobe este arquivo: python bot.py"""
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from finbot.config import logger
from finbot.db import init_db
from finbot.sheets import ensure_master_sheet, sync_users_from_master
from finbot.handlers import build_app


def main():
    init_db()
    
    # Dashboard só inicia localmente (não no Render para evitar conflito de porta)
    if not os.environ.get("RENDER"):
        try:
            from dashboard import start_dashboard
            start_dashboard(blocking=False)
            logger.info("📊 Dashboard iniciado na porta 8888")
        except Exception as e:
            logger.warning(f"Dashboard não iniciado: {e}")
    else:
        logger.info("📊 Dashboard desabilitado no Render (porta 8080 reservada)")

    # Sincronizar usuários da Master Sheet (se disponível)
    try:
        ensure_master_sheet()
        count = sync_users_from_master()
        if count > 0:
            logger.info(f"Restored {count} users from master sheet")
    except Exception as e:
        logger.warning(f"Master sheet sync unavailable: {e}")
    app = build_app()

    # ── HTTP Health Check Server (para Render) ──
    port = int(os.environ.get("PORT", 8080))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"FinBot OK\n")
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
        def log_message(self, format, *args):
            pass

    http_server = HTTPServer(("0.0.0.0", port), HealthHandler)
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()

    logger.info(f"🤖 FinBot iniciado na porta {port}")
    # ponytail: False porque o Render free hiberna e descarta a fila ao acordar;
    # com pinger no /health o backlog nem se forma.
    app.run_polling(drop_pending_updates=False, close_loop=False)

if __name__ == "__main__":
    main()
