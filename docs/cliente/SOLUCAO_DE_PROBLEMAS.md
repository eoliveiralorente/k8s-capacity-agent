# Solução de problemas

Comece sempre por **Suporte → Saúde da instalação**: cada item com erro traz "O que fazer".

| Sintoma | Causa provável | Como resolver |
|---|---|---|
| Pod em `Pending` | PVC sem StorageClass/disco | `kubectl -n capacity-agent describe pvc`; defina `persistence.storageClassName` |
| Pod em `ImagePullBackOff` | Registry/tag incorretos ou imagem privada | Confira `image.repository`/`image.tag`; use `imagePullSecrets` |
| Pod em `CrashLoopBackOff` com "CAPACITY_AGENT_ENCRYPTION_KEY inválida" | Secret da chave corrompido ou criado manualmente errado | Instalação nova: apague o Secret e rode `helm upgrade`. Com dados: restaure o Secret do backup |
| "Connection refused" no port-forward | O pod ainda não está pronto | Aguarde `Running 1/1`; veja `kubectl -n capacity-agent logs deploy/capacity-agent` |
| Consumo "sem métrica" | metrics-server ausente ou recém-instalado | `kubectl top nodes`; aguarde ~2 min após instalar |
| Recomendações sempre MANUAL | Histórico curto, namespace protegido, GitOps ou licença sem execução | Veja o motivo na recomendação; o histórico precisa de ~3 h para confiança média |
| "Permissão insuficiente" | Papel do usuário | Admin ajusta em **Usuários** |
| "Recurso não incluído na licença" (HTTP 402) | Plano atual | Fale com o fornecedor para ampliar o plano |
| Execução falha com `Forbidden` | Instalação somente leitura | `--set rbac.allowRightsizing=true` |
| Mudança aplicada "volta sozinha" | Workload gerenciado por ArgoCD/Flux | Altere no repositório Git |
| Assistente: "Não foi possível conectar ao provedor" | Saída de rede bloqueada ou URL errada | Libere HTTPS até o provedor ou use Ollama interno |
| Assistente demora/estoura tempo | IA local em CPU | Aumente `aiTimeoutSeconds` ou use modelo menor |
| Alertas não chegam | Canal não configurado ou URL inválida | **Usuários → Alertas → Enviar teste** mostra o erro de cada canal |
| Coletor (agente) sem envio | Token revogado, `panelUrl` errada ou sem saída HTTPS | `kubectl -n capacity-agent logs deploy/capacity-collector` |

Se não resolver, gere o **pacote de suporte** e abra um chamado ([SUPORTE.md](SUPORTE.md)).
