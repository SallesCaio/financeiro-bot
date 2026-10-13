# 📖 Guia Passo-a-Passo — FinBot V6

## 🚀 Começando (primeira vez)

### 1. Iniciar o bot
```
/start
```
O bot vai pedir: nome, renda, cartões, objetivo. Pronto, você está cadastrado!

### 2. Menu principal
Após o cadastro, o bot mostra:
```
💸 Registrar gasto  |  📊 Resumo
📌 Fixos            |  📅 Parcelas
📄 Relatório        |  🛒 Compras
🔍 Buscar           |  📈 Insights
💵 Receita           |  👤 Perfil
```

---

## 💸 Registrando Gastos

### Modo rápido (1 linha)
```
/g 50 mercado pix
/g 25 padaria debito
/g 150 netflix credito nubank
```
Formato: `/g <valor> <descrição> <categoria> [pagamento] [cartão]`

### Modo guiado (passo a passo)
```
/gasto
→ Quanto gastou? 50
→ O que comprou? Mercado
→ Categoria? [botões]
→ Pagamento? [botões]
→ Necessário? [Sim/Não]
→ É assinatura? [Sim/Não]  ← NOVO!
→ Alguma observação? /pular
```

### O que é "Assinatura"?
Se você responder **SIM**, o bot pergunta:
- Nome da assinatura (ex: Netflix)
- Valor mensal (ex: 55,90)

Isso registra o gasto E adiciona automaticamente na aba **FIXOS** da planilha. No futuro, o bot pode mostrar:
> "Você gasta R$ 670/mês em assinaturas: 3 streamings, 2 clouds..."

### O que é "Parcelado"?
Se você pagar no **crédito**, o bot pergunta:
- Compra parcelada ou à vista?
- Se parcelado: em quantas vezes?

Isso registra o gasto E cria as parcelas na aba **PARCELAMENTOS**.

---

## 📊 Vendo Resumo e Relatório

### Resumo do mês
```
/resumo
```
Mostra: total gasto, número de gastos, barras por categoria.

### Relatório completo
```
/relatorio
```
Mostra: receita, gastos, saldo, necessários vs supérfluos, fixos, parcelas, projeção de fim de mês, link da planilha.

---

## 📈 Insights Automáticos

```
/insights
```
O bot analisa seus gastos e gera alertas:
- "Você gastou 40% mais em delivery essa semana"
- "Seus gastos com moto aumentaram 25%"
- "Economia do mês: R$ 500"
- "Transação acima do normal: Pneu moto R$ 450"

---

## 🛒 Lista de Compras

### Adicionar item
```
/compras add leite
/compras add mercado arroz 2x
/compras add online kindle 200
/compras add farmacia dipirona
```

### Ver lista
```
/compras
```
Mostra itens agrupados por categoria (mercado, online, farmácia, casa).

### Marcar como comprado
```
/compras comprado 1
```

### Remover item
```
/compras rm 1
```

### Limpar lista
```
/compras done
```

### Lista de desejos
```
/compras desejo iphone 15
/compras desejos
```

---

## 👤 Configurando seu Perfil

### Ver perfil
```
/perfil
```

### Alterar renda
```
/perfil renda 3500
```

### Alterar nome
```
/perfil nome Caio Salles
```

### Alterar cartões
```
/perfil cards Nubank, Itau
```

---

## 💵 Registrando Renda Extra

```
/receita 500 freela
/receita 1500 bonus
/receita 200 ifood
```
Registra na aba **RECEITAS** da planilha.

---

## 🔍 Buscando Gastos

```
/busca mercado
/busca gasolina
/busca categoria:alimentacao
/busca valor:>100
```

---

## 📌 Fixos e 📅 Parcelas

### Ver fixos
```
/fixo
```

### Adicionar fixo
```
/fixo add
→ Nome: Netflix
→ Valor: 55,90
→ Dia: 15
→ Categoria: [botões]
```

### Ver parcelas
```
/parcela
```

---

## 💡 Dicas

1. **Menu sempre volta** — após qualquer ação, o bot mostra o menu. Não precisa digitar `/start`!
2. **Use `/g` para rapidez** — `/g 50 mercado pix` é o jeito mais rápido
3. **Assinaturas são automáticas** — responda "SIM" e o bot cuida do resto
4. **Parcelas são automáticas** — informe que é parcelado e o bot cria as parcelas
5. **Dashboard** — acesse pelo link do relatório para ver gráficos
6. **Insights** — use `/insights` para descobrir padrões nos seus gastos
