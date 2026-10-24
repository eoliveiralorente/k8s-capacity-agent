# Suporte

## Como abrir um chamado

1. No painel: **Suporte → Baixar pacote de suporte** (admin).
   Se o painel não abrir:
   ```bash
   kubectl -n capacity-agent exec deploy/capacity-agent -- python agent.py support-bundle -o - > suporte.zip
   ```
2. Envie para o canal de suporte do seu contrato com:
   - o que aconteceu e o que era esperado;
   - horário aproximado;
   - o arquivo `suporte.zip`.

O pacote **não contém** senhas, chaves, kubeconfigs, tokens, banco de dados nem logs das suas
aplicações. Você pode abrir o .zip e conferir antes de enviar.

## Prazos de primeira resposta (por plano)

| Plano | Canal | Primeira resposta |
|---|---|---|
| Community | Documentação | — |
| Pro | E-mail | até 2 dias úteis |
| Enterprise | E-mail + canal dedicado | até 1 dia útil (crítico: 4 h úteis) |

> Os prazos acima são o modelo padrão; o que vale é o definido no seu contrato.

## Versões suportadas

São suportadas as **duas últimas versões menores** (ex.: 1.4.x e 1.3.x). Atualize com
`helm upgrade` conforme [ATUALIZACAO.md](ATUALIZACAO.md).
