#!/usr/bin/env python3
"""
FinBot Smart Categorizer — Categorização inteligente de gastos sem IA externa.
Usa heurísticas + matching de keywords + aprendizado com correções manuais.
"""
import sqlite3
from pathlib import Path

# ════════════════════════════════════════════════════════
# KEYWORDS POR CATEGORIA
# ════════════════════════════════════════════════════════
KEYWORDS = {
    "alimentacao": [
        "mercado", "supermercado", "padaria", "pao", "cafe", "lanche", "comida",
        "refeicao", "almoco", "janta", "cafe da manhã", "lanchonete", "suco",
        "fruta", "verdura", "legume", "carne", "fruto", "leite", "queijo",
        "cerveja", "vinho", "chopp", "cachaca", "wisky", "drink", "bebida",
        "agua", "gasolina", "combustivel", "uber", "taxi", "onibus", "metro",
        "bilhete", "passagem", "transporte", "combustivel", "gas", "etanol",
        "ipva", "multa", "estacionamento", "pedagio", "lavagem", "oleo",
        "pneu", "revisao", "moto", "motoca", "moto"
    ],
    "mercado": [
        "mercado", "supermercado", "hipermercado", "atacado", "atacadao",
        "carrefour", "assai", "pao de acucar", "extra", "assai", "makro",
        "atenda", "supernosso", "supermercado"
    ],
    "delivery": [
        "ifood", "rappi", "uber eats", "aiqfome", "delivery", "entrega",
        "pedido", "comida online", "groceries", "food delivery"
    ],
    "assinaturas": [
        "netflix", "spotify", "youtube premium", "ytb premium", "hbo max",
        "prime video", "amazon prime", "disney plus", "disney+", "apple tv",
        "apple music", "icloud", "google one", "photoshop", "adobe",
        "office 365", "notion", "evernote", "tredu", "zoom",
        "plano claro", "plano vivo", "plano tim", "plano oi", "plano net",
        "assinatura", "mensalidade", "streaming"
    ],
    "moto": [
        "moto", "motoca", "yamaha", "honda", "harley", "ducati", "bmw",
        "pneu moto", "oleo moto", "revisao moto", "peca moto", "acessorio moto",
        "ipva moto", "seguro moto"
    ],
    "transporte": [
        "uber", "taxi", "onibus", "metro", "trem", "ubereats",
        "cabify", "99pop", "app旅行", "passagem", "bilhete",
        "combustivel", "gasolina", "etanol", "gas", "diesel",
        "ipva", "multa", "estacionamento", "pedagio", "lavagem",
        "transporte", "trajeto", "corrida"
    ],
    "pessoal": [
        "barbeiro", "cabeleireiro", "salao", "beleza", "cosmetico",
        "shampoo", "sabonete", "perfume", "crema", "protetor solar",
        "roupa", "tenis", "sapatilha", "camiseta", "calca", "bermuda",
        "roupa intima", "meia", "calcado"
    ],
    "saude": [
        "farmacia", "remedio", "medicamento", "consulta medica", "dentista",
        "hospital", "clinica", "exame", "raio x", "sangue", "vacina",
        "plano de saude", "unimed", "amil", "bradesco saude",
        "psicologo", "terapeuta", "nutricionista", "academia", "ginastica",
        "pilates", "yoga", "personal trainer"
    ],
    "dividas": [
        "divida", "emprestimo", "cartao de credito", "fatura", "parcela",
        "juros", "multa", "atraso", "negativacao", "_serasa",
        "consorcio", "financiamento", "credito"
    ],
    "moradia": [
        "aluguel", "condominio", "iptu", "agua", "luz", "gas", "internet",
        "wifi", "tv a cabo", "net claro", "vivo", "tim", "oi",
        "casa", "apartamento", "reforma", "manutencao", "marceneiro",
        "eletricista", "encanador", "pintor", "diarista", "faxina"
    ],
    "educacao": [
        "curso", "escola", "faculdade", "pos graduacao", "mestrado",
        "doutorado", "certificacao", "treinamento", "workshop",
        "aula", "professor", "mestre", "tutoria", "reforco",
        "idioma", "ingles", "espanhol", "frances", "alemaocurso online",
        "udemy", "alura", "dio", "coursera", "edx"
    ],
    "lazer": [
        "cinema", "teatro", "show", "evento", "festival", "festa",
        "parque", "zoo", "aquario", "museu", "exposicao",
        "viagem", "hotel", "pousada", "hostel", "trip", "ferias",
        "jogo", "videogame", "playstation", "xbox", "nintendo",
        "livro", "kindle", "hq", "manga", "revista", "tabuleiro"
    ],
}

def _normalize(text):
    """Normaliza texto para minúsculo e sem acentos."""
    text = text.lower().strip()
    # Remove acentos comuns
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for acc, norm in replacements.items():
        text = text.replace(acc, norm)
    return text


def categorizar_gasto(descricao):
    """Categoriza um gasto baseado em keywords. Retorna (categoria, confianca)."""
    desc_lower = _normalize(descricao)
    scores = {}
    
    for categoria, keywords in KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw.lower() in desc_lower:
                score += 1
        if score > 0:
            scores[categoria] = score
    
    if not scores:
        return "outros", 0.0
    
    best_cat = max(scores, key=scores.get)
    confidence = min(scores[best_cat] / 3, 1.0)  # Max 1.0
    return best_cat, confidence


def salvar_aprendizado(user_id, descricao, categoria_correta):
    """Salva correção manual do usuário para aprendizado."""
    db_path = Path(__file__).parent / "finbot.db"
    if not db_path.exists():
        db_path = Path("/tmp/finbot.db")
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS aprendizado_categoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO aprendizado_categoria (user_id, descricao, categoria) VALUES (?, ?, ?)",
            (user_id, descricao, categoria_correta)
        )
        conn.commit()


def corrigir_categoria(user_id, descricao, categoria_errada, categoria_correta):
    """Registra correção manual para melhorar futuras categorizações."""
    salvar_aprendizado(user_id, descricao, categoria_correta)


if __name__ == "__main__":
    # Teste rápido
    testes = [
        "Netflix", "Uber", "Supermercado", "Farmacia", "Barbeiro",
        "Gasolina", "ICloud", "Spotify", "Curso Ingles", "Pneu moto",
        "Restaurante", "Cinema", "Aluguel", "Ifood", "Dog"
    ]
    print("=== TESTE CATEGORIZADOR ===")
    for t in testes:
        cat, conf = categorizar_gasto(t)
        print(f"  {t:25s} → {cat:15s} ({conf:.0%})")
