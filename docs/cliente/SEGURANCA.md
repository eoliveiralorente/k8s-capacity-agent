# Segurança, dados e LGPD

## O que a ferramenta acessa

- **Leitura** (sempre): nodes, pods, eventos, namespaces, deployments/statefulsets/daemonsets,
  HPAs, métricas do metrics-server e logs de pods (logs só para operador/admin e sob demanda).
- **Escrita** (somente com `rbac.allowRightsizing=true` e **sempre após aprovação** de um usuário):
  requests de CPU/memória, réplicas e HPA. Nunca apaga recursos.

## Onde ficam os dados

- Tudo fica **no seu cluster**, no PVC da instalação. Nada é enviado ao fornecedor.
- Segredos (chaves de API, URLs de webhook) ficam **cifrados** (Fernet) no banco.
- Senhas de usuários: scrypt. Sessões: só o hash do token é armazenado.
- A licença é validada **offline** (assinatura digital); não há chamada externa.

## Assistente de IA

- Desligado até um admin configurar. Usa a **chave de API do cliente** ou um modelo local (Ollama).
- Antes de qualquer envio ao modelo, a ferramenta **mascara** tokens, senhas, chaves, e-mails,
  IPs, CPF e credenciais em URLs.
- O assistente é **somente leitura**: não executa nenhuma ação no cluster.
- Cada pergunta fica registrada na auditoria.

## Controle de acesso

- Papéis: **leitor** (visualiza), **operador** (avalia, aprova, simula, vê logs), **admin** (clusters,
  usuários, licença, execução real). Toda ação fica na **auditoria** com o usuário autenticado.
- Login com limite de tentativas; convites de uso único com validade.

## Contêiner

Roda sem root (UID 10001), sistema de arquivos somente leitura, sem capabilities Linux,
seccomp `RuntimeDefault`, com limites de CPU/memória.

## LGPD

Logs de aplicações podem conter dados pessoais. A ferramenta só lê logs sob demanda, não os
armazena e os mascara antes de qualquer uso pela IA. O pacote de suporte **não inclui** logs de
aplicações, banco de dados, chaves ou kubeconfigs.
