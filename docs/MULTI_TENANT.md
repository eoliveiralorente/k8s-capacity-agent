# Empresas e conexões Kubernetes

## Configuração do servidor

Instale as dependências. Em produção, gere uma chave Fernet uma única vez:

```bash
python3 -m pip install -r requirements.txt
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Guarde o resultado em um secret manager e configure no ambiente do servidor:

```bash
export CAPACITY_AGENT_ENCRYPTION_KEY="<chave guardada no secret manager>"
export CAPACITY_AGENT_COOKIE_SECURE=true
./serve.sh
```

A chave configurada precisa permanecer estável entre reinicializações. Se
`CAPACITY_AGENT_ENCRYPTION_KEY` não for definida, o agente gera uma chave em
`encryption.key`, no mesmo diretório do banco SQLite. Mantenha esse arquivo
junto com o banco ao mover a instalação para outro ambiente; sem a chave
original, os kubeconfigs armazenados não poderão ser descriptografados. Faça
backup seguro da chave e do arquivo SQLite configurado por
`CAPACITY_AGENT_ACCOUNT_DB`.

O painel remoto deve ser publicado somente por HTTPS, atrás de um proxy reverso
que termine TLS. Não desative `CAPACITY_AGENT_COOKIE_SECURE` em um servidor
remoto. Para desenvolvimento apenas em localhost, a opção pode ser definida
como `false` enquanto o servidor escuta em `127.0.0.1`.

## Cadastro e clusters

1. A primeira visita abre **Criar conta**. O cadastro cria a empresa e o usuário
   administrador inicial.
2. Entre na aba **Cluster**, informe um nome de identificação e envie o arquivo
   kubeconfig.
3. O agente valida o contexto e consulta os nodes antes de aceitar a conexão.
4. Selecione o cluster no menu **Cluster ativo**; os dados de operação ficam
   separados por empresa e cluster.

Os kubeconfigs são cifrados no SQLite. O arquivo temporário de validação tem
permissões restritas e é removido ao terminar a consulta. Kubeconfigs que usam
plugins `exec`, arquivos de certificado externos ou `auth-provider` são
recusados. Para embutir os certificados da conexão atual, gere um arquivo
flattened com:

```bash
kubectl config view --minify --flatten --raw > kubeconfig-flattened.yaml
```

Nunca envie kubeconfigs por canais inseguros nem os inclua no repositório.

## Limites desta versão

O cadastro cria uma empresa por conta; ainda não há convites para colegas
entrarem na mesma empresa, papéis/permissões, recuperação/verificação de e-mail
ou proteção contra tentativas automatizadas de login. Antes de vender o serviço
publicamente, implemente esses fluxos e revise proxy, TLS, backups e gestão de
segredos no ambiente de hospedagem.
