# Documentação — Sistema P2P com Balanceamento de Carga Dinâmico

**Grupo 7** — Nicolas Clay, João Victor Aires e Rafael Gouveia

## Índice

| Documento | Descrição |
|---|---|
| [architecture.md](architecture.md) | Diagrama de componentes, fluxos de histerese, ciclo de vida dos workers e variáveis de ambiente |
| [protocol.md](protocol.md) | Especificação completa de todos os tipos de mensagem P2P e Worker↔Master |
| [master.md](master.md) | Referência técnica de `src/master.py` (funções, estado global, limiares) |
| [worker.md](worker.md) | Referência técnica de `src/worker.py` (loop de conexão, heartbeat, simulação de falha) |
| [monitor.md](monitor.md) | Referência técnica de `src/monitor.py` — Sprint 4 (telemetria TLS) |

## Sprints

| Sprint | Funcionalidade |
|---|---|
| Sprint 01 | Comunicação básica Master↔Worker: `ALIVE` / `TASK: QUERY` / `STATUS: OK\|NOK` / `ACK` |
| Sprint 02 | Heartbeat independente no worker via thread daemon separada |
| Sprint 03 | Protocolo P2P completo: empréstimo e devolução de workers entre masters |
| Sprint 04 | Monitor de telemetria: envio de métricas ao supervisor via TLS/TCP a cada 10s |

## Como Executar

**Master:**
```bash
P2P_SERVER_UUID=Master_01 P2P_HOST=<seu_ip> python src/master.py
```

**Worker:**
```bash
P2P_WORKER_UUID=Worker_01 P2P_HOST=<ip_do_master> P2P_PORT=8000 python src/worker.py
```

**Dependência opcional (métricas de sistema no Monitor):**
```bash
pip install psutil
```
