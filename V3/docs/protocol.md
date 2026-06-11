# Protocolo de Mensagens P2P

## Formato Base

Todas as mensagens são objetos JSON delimitados por `\n` (newline). Mensagens de controle P2P seguem o envelope:

```json
{
  "type": "<tipo>",
  "request_id": "<uuid4>",
  "payload": { ... }
}
```

Mensagens Worker→Master usam formato legado (sem envelope):

```json
{ "WORKER": "ALIVE", "WORKER_UUID": "<id>" }
```

## Tipos Válidos de Mensagem (`type`)

```python
TIPOS_MENSAGEM_VALIDOS = {
    "request_help", "response_accepted", "response_rejected",
    "command_redirect", "register_temporary_worker", "command_release",
    "notify_worker_returned"
}
```

Mensagens com `type` fora desse conjunto são descartadas com `WARNING`.

---

## Mensagens de Controle P2P

### `request_help` (Master → Master)

Solicita workers emprestados a um vizinho.

**Campos obrigatórios em `payload`:** `master_id`, `current_load`, `capacity`, `workers_needed`

```json
{
  "type": "request_help",
  "request_id": "a1b2c3d4-...",
  "payload": {
    "master_id": "Master_Local",
    "current_load": 15,
    "capacity": 10,
    "workers_needed": 2
  }
}
```

---

### `response_accepted` (Master → Master)

Resposta positiva: vizinho aceita emprestar workers.

**Campos obrigatórios em `payload`:** `workers_offered`, `worker_details`

```json
{
  "type": "response_accepted",
  "request_id": "a1b2c3d4-...",
  "payload": {
    "workers_offered": 1,
    "worker_details": [
      {"id": "Worker_01", "address": "10.62.217.11:8000"}
    ]
  }
}
```

---

### `response_rejected` (Master → Master)

Resposta negativa: vizinho recusa o pedido.

**Campos obrigatórios em `payload`:** `reason`

Valores possíveis de `reason`:
- `"high_load"` — carga local ≥ `SATURATION_THRESHOLD`
- `"no_workers_available"` — nenhum worker local disponível

```json
{
  "type": "response_rejected",
  "request_id": "a1b2c3d4-...",
  "payload": { "reason": "high_load" }
}
```

---

### `command_redirect` (Master → Worker)

Ordena ao worker migrar para outro master.

**Campos obrigatórios em `payload`:** `new_master_address`

```json
{
  "type": "command_redirect",
  "request_id": "b2c3d4e5-...",
  "payload": { "new_master_address": "10.62.217.208:8000" }
}
```

Worker recebe via conexão TCP existente; no próximo ciclo conecta ao novo endereço.

---

### `register_temporary_worker` (Worker → Master)

Worker emprestado se registra no master de destino antes de pedir tarefa.

**Campos obrigatórios em `payload`:** `worker_id`, `original_master_address`

```json
{
  "type": "register_temporary_worker",
  "request_id": "c3d4e5f6-...",
  "payload": {
    "worker_id": "Worker_01",
    "original_master_address": "10.62.217.11:8000"
  }
}
```

---

### `command_release` (Master → Worker)

Ordena ao worker retornar ao master de origem.

**Campos obrigatórios em `payload`:** `original_master_address`

```json
{
  "type": "command_release",
  "request_id": "d4e5f6g7-...",
  "payload": { "original_master_address": "10.62.217.11:8000" }
}
```

Worker atualiza `current_master_addr` para o endereço original e seta `is_borrowed = False`.

---

### `notify_worker_returned` (Master → Master)

Notifica o master emprestador que um worker foi devolvido e pode ser retirado de `LENT_WORKERS`.

**Campos obrigatórios em `payload`:** `worker_id`

```json
{
  "type": "notify_worker_returned",
  "request_id": "e5f6g7h8-...",
  "payload": { "worker_id": "Worker_01" }
}
```

---

## Mensagens Legadas Worker ↔ Master

Estas mensagens **não** usam o envelope `{type, request_id, payload}`. São identificadas pelos campos presentes.

### HEARTBEAT

**Worker → Master:**
```json
{ "SERVER_UUID": "Master_Local", "TASK": "HEARTBEAT" }
```

**Master → Worker:**
```json
{ "SERVER_UUID": "Master_Local", "TASK": "HEARTBEAT", "RESPONSE": "ALIVE" }
```

Enviado pela thread `heartbeat_loop` do worker em uma conexão TCP separada a cada `HEARTBEAT_INTERVAL` segundos (padrão: 5s).

---

### ALIVE (Worker → Master)

Worker local:
```json
{ "WORKER": "ALIVE", "WORKER_UUID": "Worker_01" }
```

Worker emprestado inclui campo adicional `SERVER_UUID` com o endereço do master de origem:
```json
{ "WORKER": "ALIVE", "WORKER_UUID": "Worker_01", "SERVER_UUID": "10.62.217.11:8000" }
```

**Campos obrigatórios:** `WORKER`, `WORKER_UUID`

---

### TASK (Master → Worker)

Tarefa disponível:
```json
{ "TASK": "QUERY", "USER": "Compilar_Kernel" }
```

Sem tarefa na fila:
```json
{ "TASK": "NO_TASK" }
```

Tarefas possíveis: `Compilar_Kernel`, `Processar_Pagamentos`, `Otimizar_Rotas`, `Analisar_Vulnerabilidades`, `Treinar_Rede_Neural`, `Sincronizar_Bancos`.

---

### STATUS (Worker → Master)

Após processar uma tarefa QUERY, o worker reporta o resultado:

```json
{ "STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": "Worker_01" }
```

`STATUS` pode ser:
- `"OK"` — tarefa concluída com sucesso (~90% dos casos)
- `"NOK"` — falha simulada (~10% de probabilidade aleatória)

**Campos obrigatórios:** `STATUS`, `TASK`, `WORKER_UUID`

---

### ACK (Master → Worker)

Confirmação de recebimento do STATUS:

```json
{ "STATUS": "ACK", "WORKER_UUID": "Worker_01" }
```

---

## Diagrama de Sequência — Fluxo Completo de Empréstimo

```
Master A          Master B          Worker X
   │                  │                 │
   │── request_help──►│                 │
   │◄─ accepted ───────│                 │
   │                  │                 │
   │  [enfileira command_redirect p/ Worker X]
   │◄────────────── ALIVE ──────────────│
   │── command_redirect ───────────────►│
   │                  │                 │
   │                  │◄── reg_temp ────│
   │                  │◄── ALIVE ───────│
   │                  │── QUERY ───────►│
   │                  │◄── STATUS: OK ──│
   │                  │── ACK ─────────►│
   │                  │     (loop...)   │
   │  [enfileira command_release p/ Worker X]
   │                  │◄── ALIVE ───────│
   │                  │── release ─────►│
   │◄─ notify_returned─│                 │
   │                  │                 │
   │◄────────────── ALIVE ──────────────│
   │── QUERY ──────────────────────────►│
```
