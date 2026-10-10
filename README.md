<div align="center">

![header](https://capsule-render.vercel.app/api?type=venom&color=gradient&customColorList=12&height=300&section=header&text=🤖%20FinBot&fontSize=80&fontColor=fff&animation=fadeIn&fontAlignY=35&desc=Gestão%20Financeira%20via%20Telegram%20%2B%20Google%20Sheets&descAlignY=55&descSize=18)

<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" />
  <img src="https://img.shields.io/badge/Google_Sheets-34A853?style=for-the-badge&logo=google-sheets&logoColor=white" />
  <img src="https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white" />
</p>

**Bot de gestão financeira pessoal via Telegram + Google Sheets**
Multi-user · Deploy automático · 24/7 no ar

[🌐 Demo](https://financeiro-bot-12go.onrender.com) · [📖 Docs](#-funcionalidades) · [🚀 Deploy](#-deploy)

</div>

---

## 📸 Preview

<div align="center">

| Menu Principal | Lançamento | Relatórios |
|:---:|:---:|:---:|
| ![menu](https://via.placeholder.com/280x420/1a1a2e/ffffff?text=Menu+Principal) | ![gasto](https://via.placeholder.com/280x420/1a1a2e/ffffff?text=Lançamento+Guiado) | ![relatorio](https://via.placeholder.com/280x420/1a1a2e/ffffff?text=Relatórios) |

</div>

---

## ✨ Funcionalidades

### 💸 Lançamentos
- **Modo guiado** (`/gasto`): fluxo passo-a-passo com botões inline
- **Modo rápido** (`/g 50 mercado pix`): registro em um comando
- Suporte a **crédito** (à vista e parcelado) e **débito/pix**
- Categorização automática (13 categoridas)
- Vinculação com **faturas de cartão**
- Registro de **parcelamentos** com cálculo automático

### 📊 Relatórios
- **Parcelamentos**: lista completa com progresso (barra visual)
- **Fixos/Assinaturas**: gastos recorrentes com total mensal/anual
- **Resumo do mês**: totais por categoria com barras de progresso
- **Relatório completo**: tudo combinado + projeção financeira
- Todos os relatórios incluem **link da planilha**

### 💳 Faturas
- Criação automática de faturas por **cartão + mês referência**
- **Vencimento padrão**: dia 08 de cada mês
- Distinção **à vista** (valor total) vs **parcelado** (valor da parcela)
- Parcelamentos distribuem automaticamente nas faturas dos meses seguintes
- Gatilho para **baixa de faturamento** (campo PAGO/VALOR_PAGO/DATA_PAGAMENTO)

### 📅 Parcelamentos
- Aba própria no Google Sheets
- Cálculo automático de VALOR_PAGO e VALOR_RESTANTE
- Barra de progresso visual (█░)
- Integração com faturas do cartão

### 📌 Fixos (Assinaturas)
- Lançamentos recorrentes vão para aba FIXOS
- Cálculo de total mensal e anual estimado
- Gestão de ativação/desativação

### 🛒 Lista de Compras
- CRUD completo: adicionar, remover, marcar como comprado
- Suporte a categorias, quantidade e preço
- Persistência via Google Sheets

### 👤 Perfil
- Configuração de nome, renda, cartões, objetivo
- Edição via comandos rápidos

---

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                        TELEGRAM                             │
│  User → /gasto → Botões Inline → Respostas → Confirmação   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   python-telegram-bot v22                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Onboarding   │  │  Lançamentos │  │  Relatórios  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Faturas      │  │ Parcelamentos│  │    Fixos     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────┬───────────────────────────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Google Sheets│  │    SQLite    │  │    Render    │
│ (fonte da    │  │   (cache     │  │   (deploy    │
│  verdade)    │  │    local)    │  │    24/7)     │
└──────────────┘  └──────────────┘  └──────────────┘
```

### Estrutura da Planilha Google Sheets

| Aba | Conteúdo |
|-----|----------|
| `YYYY-MM` | Lançamentos do mês (DATA, DESCRIÇÃO, CATEGORIA, PAGAMENTO, VALOR, CARTÃO, NECESSÁRIO, TIPO, OBS) |
| `FATURAS` | Faturas por cartão/mês (CARTÃO, REF_MÊS, TOTAL, VENCIMENTO, PAGO, VALOR_PAGO, DATA_PAGAMENTO, OBS) |
| `PARCELAMENTOS` | Parcelas (COD, DESCRIÇÃO, VALOR_PARCELA, TOTAL_PARCELAS, PAGAS, RESTANTES, VALOR_PAGO, VALOR_RESTANTE) |
| `FIXOS` | Gastos fixos (NOME, VALOR, DIA_VENCIMENTO, CATEGORIA, ATIVO, OBS) |
| `COMPRAS` | Lista de compras (COD, ITEM, QTY, CATEGORIA, PRECO, COMPRADO, DATA) |
| `RECEITAS` | Rendas extras (DATA, DESCRIÇÃO, VALOR, CATEGORIA, OBS) |
| `METAS` | Metas financeiras (NOME, META, ATUAL, CATEGORIA, MENSAL, ATIVO) |
| `RESUMO` | Fórmulas SUMIF automáticas |
| `USERS` | Sync de usuários (user_id, username, name, income, spreadsheet_id) |

---




## 🛡️ Segurança

- Validação de entrada em todos os formulários
- Sem dados sensíveis no código (tudo via env vars)
- Google Sheets como fonte da verdade (não perde dados)
- Master Sheet para recovery de usuários

---


## 📝 Licença

MIT License — sinta-se livre para usar e modificar.

---

<div align="center">

**Feito com ❤️ por [Caio Salles](https://github.com/SallesCaio)**

[![LinkedIn](https://img.shields.io/badge/-LinkedIn-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/salles-caio-silva/)

</div>
