# Capacity Agent: demonstração no seu computador

Esta demonstração mostra o Capacity Agent com uma **empresa e um cluster fictícios** (Nimbus Pay).
Ela **não acessa nenhum cluster** e não envia dados para fora do seu computador.

## Você vai precisar

- **Docker Desktop** (Windows ou macOS) ou Docker (Linux), aberto e rodando.
- Cerca de 1 GB livre em disco.

## Iniciar (2 minutos)

- **Windows:** clique com o botão direito em `iniciar-demo.ps1` e escolha **Executar com o PowerShell**.
- **macOS, Linux ou WSL:** no terminal, dentro desta pasta, rode `./iniciar-demo.sh`.

No fim, o script mostra o endereço (`http://localhost:8090`), o login e a senha. No Windows o
navegador abre sozinho.

## O que olhar (10 minutos)

1. **Visão Geral:** a nota de saúde, os riscos que exigem ação agora e as maiores economias.
2. **Custos:** quanto o cluster custa por mês, quanto está pago e sem uso e o custo por namespace.
   O pool *memory* usa autoscaling, e o painel percebe isso pelo histórico.
3. **Recomendações:** abra uma, clique em **Aprovar**, depois em **Simular** e em **Executar**. Na
   demonstração a execução é simulada: o painel mostra o comando kubectl e como reverter.
4. **Nodes e capacidade:** clique num node para ver os pods, o uso real e o que está reservado.
5. **Diário de bordo** e **Auditoria:** pendências com responsável e prazo, e o registro de cada ação.

## Renovar, parar e remover

| O quê | Windows | macOS / Linux |
|---|---|---|
| Renovar os dados (histórico de 7 dias) | rode `iniciar-demo.ps1` de novo | `./iniciar-demo.sh` |
| Parar | `parar-demo.ps1` | `./parar-demo.sh` |
| Remover tudo (dados e imagem) | `parar-demo.ps1 -Apagar` | `./parar-demo.sh --apagar` |

## Quer ver no seu cluster?

A instalação real roda **dentro do seu cluster**, somente leitura, e leva cerca de 15 minutos.
Nada muda no cluster sem aprovação, simulação e auditoria. O contato aparece no topo do painel
da demonstração.

*Os nomes, números e valores desta demonstração são fictícios.*
