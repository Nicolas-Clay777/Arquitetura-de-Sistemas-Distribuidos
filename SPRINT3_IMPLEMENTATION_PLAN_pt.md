# Sprint 3: Protocolo Master-to-Master de Pedido de Ajuda — Plano de Implementação

> **Para agentes executores:** USAR subagent-driven-development ou executing-plans para implementar passo a passo.

**Objetivo:** Implementar o protocolo completo Master-to-Master (Sprint 3) com monitoramento de carga, empréstimo/devolução de workers e integração com Sprints 1–2.

**Arquitetura:** Estender master.py e worker.py com cliente/servidor M2M não bloqueantes, rastreamento por UUID, registries thread-safe e loop de monitoramento em daemon.

**Tecnologias:** Python 3.x, threading, socket, uuid, json, queue, logging

---

## Resumo da Implementação

O que foi adicionado:
1. Constantes e locks (thresholds, locks, registries)
2. Funções cliente M2M: `send_request_help()`, `try_request_help()`
3. Handlers servidor M2M em `process_message()` para tipos: request_help, response_accepted/rejected, command_redirect, register_temporary_worker, command_release, notify_worker_returned
4. Loop de monitor (daemon) que verifica carga e aciona pedidos/liberações
5. Melhorias no Worker: tratar redirect/release e enviar register_temporary_worker
6. Logging e contadores visíveis

---

## Alterações por arquivo

### master.py

- Imports: `uuid`, `logging`, `time`
- Constantes:
  - `SATURATION_THRESHOLD = 0.8`
  - `RELEASE_THRESHOLD = SATURATION_THRESHOLD * 0.6  # 0.48`
  - `REQUEST_TIMEOUT = 5.0`
  - `NEIGHBORS = [("127.0.0.1", 5001)]`
- Locks: `queue_lock`, `workers_lock`, `borrowed_lock`
- Registries: `workers_map`, `borrowed_registry`

Novas funções:
- `log_m2m(request_id, mtype, info='')` — logging padronizado
- `send_request_help(neighbor, request_id, payload)` — envia request_help e espera resposta (5s)
- `try_request_help()` — calcula carga e tenta pedir ajuda aos vizinhos
- `release_borrowed_worker(worker_uuid, lender_info)` — envia command_release e notifica o doador
- `monitor_loop()` — daemon que executa a cada 2s

Modificações:
- `process_message()` agora detecta mensagens M2M por `type` e trata os novos tipos. O protocolo Worker permanece compatível.
- `start_master()` inicializa `monitor_thread` como daemon antes de aceitar conexões.

---

### worker.py

- Imports: `uuid`, `logging`
- Constante nova: `ORIGINAL_SERVER_UUID = SERVER_UUID`
- No `start_worker()`:
  - Ao reconectar, se `SERVER_UUID` foi alterado, envia `register_temporary_worker`
  - Tratamento de `command_redirect`: atualiza SERVER_UUID e reconecta
  - Tratamento de `command_release`: atualiza HOST/PORT para retorno e restaura SERVER_UUID

---

## Estrutura de Arquivos

- `master.py`: funções cliente M2M, handlers, monitor, filas e locks
- `worker.py`: loop de worker com tratamento de mensagens de controle

---

## Checklist de Verificação

- `python -m py_compile master.py worker.py` — sem erros
- Imports disponíveis: `uuid`, `logging`, `time`
- Thresholds: 0.8 / 0.48 configurados
- Locks inicializados e usados
- Mensagens M2M terminam com `\n`
- `type` em minúsculas; controles UPPERCASE
- logging configurado `%(asctime)s %(message)s`
- Contadores visíveis atualizados em cada mudança de estado
- Compatibilidade com Sprints 1–2 garantida

---

## Instruções de Teste (manuais)

1. Teste básico (1 Master + 1 Worker):
   - `python master.py`
   - `python worker.py`
   - Verificar fluxo ALIVE → TASK → OK → ACK

2. Gatilho de carga (2 Masters + 1 Worker):
   - Master B (porta 5001) vazio
   - Master A (porta 5000) com `NEIGHBORS=[('127.0.0.1',5001)]`
   - Iniciar Worker
   - Inserir 10+ tarefas em Master A
   - Esperado: Master A faz request_help; Master B aceita; Worker redirecionado e registrado

3. Liberação quando normaliza:
   - Após processamento, Master A detecta carga < 0.48
   - Master A envia command_release; Worker retorna; Master B é notificado

---

## Cenários de Erro

- Timeout de vizinho (5s): tenta próximo vizinho
- Todos rejeitam: mantém estado atual e re-tenta em ciclo seguinte
- Worker desconecta no redirect: reinicia e reconecta ao Master original
- Falha na notificação: log e continuação do serviço

---

## Boas Práticas

- Testar em ambiente com portas distintas por Master
- Ajustar `NEIGHBORS` conforme topologia real
- Monitorar logs para `M2M <request_id>` e contadores

---

**Fim do Plano de Implementação**