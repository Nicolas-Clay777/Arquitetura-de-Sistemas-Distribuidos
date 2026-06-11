# Master Node — Referência Técnica

**Arquivo:** `src/master.py` | **Porta padrão:** `8000` | **Sprints:** 01, 02, 03, 04

## Constantes e Limiares

| Constante | Valor padrão | Descrição |
|---|---|---|
| `CAPACITY` | `10` | Capacidade máxima de tarefas |
| `SATURATION_THRESHOLD` | `10` | Limiar de saturação: acima disso, solicita ajuda a vizinhos |
| `RELEASE_THRESHOLD` | `4` | Limiar de liberação: abaixo disso, devolve workers emprestados |
| `NEGOTIATION_TIMEOUT` | `5` | Timeout (s) para conexões P2P entre masters |
| `LOAD_CHECK_INTERVAL` | `3` | Intervalo (s) do loop de verificação de carga |
| `HEARTBEAT_INTERVAL` | `5` | Intervalo (s) entre heartbeats (workers) |

## Variáveis de Estado Global (Thread-safe)

| Variável | Tipo | Lock | Descrição |
|---|---|---|---|
| `WORKERS_ATIVOS` | `dict[str, addr]` | `_lock` | Todos os workers com conexão ativa (local + emprestados recebidos) |
| `LENT_WORKERS` | `dict[str, str]` | `_lock` | Workers locais emprestados a outros masters (`worker_id → master_id`) |
| `BORROWED_WORKERS` | `dict[str, str]` | `_lock` | Workers recebidos de outros masters (`worker_id → original_master_address`) |
| `PENDING_WORKER_COMMANDS` | `dict[str, dict]` | `_lock` | Comandos pendentes a entregar no próximo ALIVE do worker (`worker_id → cmd_dict`) |
| `BORROWED_WORKER_TASKS` | `dict[str, int]` | — | Contador de tarefas executadas por worker emprestado (lifecycle log) |
| `FILA_TAREFAS` | `list[str]` | `fila_lock` | Fila FIFO de tarefas pendentes |
| `_tasks_completed` | `int` | `_monitor_lock` | Tarefas concluídas com `STATUS: OK` (Sprint 4) |
| `_tasks_failed` | `int` | `_monitor_lock` | Tarefas com `STATUS: NOK` (Sprint 4) |
| `_task_dispatch_times` | `dict[str, float]` | `_monitor_lock` | Timestamp Unix do despacho por `worker_id` (Sprint 4) |

## Funções Públicas

### `start_master()`

Ponto de entrada. Sequência de inicialização:

1. Inicia thread daemon `monitor_carga`
2. Inicia thread daemon `gerador_tarefas`
3. Chama `start_monitor(SERVER_UUID, get_farm_snapshot)` (Sprint 4)
4. Abre servidor TCP em `0.0.0.0:{PORT}` com `SO_REUSEADDR` e timeout de 1s no `accept()` (permite `KeyboardInterrupt`)
5. Loop: aceita conexões e lança `handle_client(conn, addr)` em thread daemon por conexão

Encerramento via `KeyboardInterrupt`: loga `OFFLINE` e chama `os._exit(0)`.

---

### `handle_client(conn, addr)`

Handler de cada conexão TCP aceita. Lê dados em loop, separando mensagens pelo `DELIMITER` (`\n`).

**Prioridade de despacho (ordem avaliada):**

| Condição | Ação |
|---|---|
| `type == "request_help"` | Avalia carga local e workers disponíveis; empresta ou rejeita |
| `type == "register_temporary_worker"` | Adiciona worker em `BORROWED_WORKERS` e `WORKERS_ATIVOS`; mantém conexão aberta |
| `type == "notify_worker_returned"` | Remove worker de `LENT_WORKERS` |
| `WORKER == "ALIVE"` + pending command | Entrega o comando pendente (ex: `command_redirect`) e retorna sem processar tarefa |
| Mensagem padrão worker | Chama `processar_requisicao_worker()` |

**Lógica de `keep_open`:**
- `True` quando master envia `TASK: QUERY` (aguarda STATUS de retorno)
- `True` quando worker emprestado é registrado (conexão de longa duração)
- `False` nos demais casos

---

### `processar_requisicao_worker(msg, worker_id, is_borrowed)`

Processa mensagens legadas do worker. Retorna `dict` a ser enviado como resposta, ou `{}` se nenhuma resposta for necessária.

| Mensagem recebida | Resposta enviada | Efeito colateral |
|---|---|---|
| `TASK == "HEARTBEAT"` | `{TASK: HEARTBEAT, RESPONSE: ALIVE, SERVER_UUID: ...}` | — |
| `WORKER == "ALIVE"` + tarefa na fila | `{TASK: QUERY, USER: <tarefa>}` | Remove tarefa da fila; registra timestamp em `_task_dispatch_times` |
| `WORKER == "ALIVE"` + fila vazia | `{TASK: NO_TASK}` | Loga aviso único "todas concluídas" |
| `STATUS == "OK"` | `{STATUS: ACK, WORKER_UUID: <id>}` | Incrementa `_tasks_completed`; remove de `_task_dispatch_times` |
| `STATUS == "NOK"` | `{STATUS: ACK, WORKER_UUID: <id>}` | Incrementa `_tasks_failed`; remove de `_task_dispatch_times` |

---

### `monitor_carga()`

Thread daemon. Executa a cada `LOAD_CHECK_INTERVAL` (3s):

1. **Limpeza:** remove entradas de `PENDING_WORKER_COMMANDS` para workers que não estão em `WORKERS_ATIVOS`
2. **Saturação:** se `carga > SATURATION_THRESHOLD` → `solicitar_ajuda_vizinhos(workers_needed)`
3. **Liberação:** se `carga < RELEASE_THRESHOLD` e há `BORROWED_WORKERS`:
   - Para cada worker emprestado: enfileira `command_release` em `PENDING_WORKER_COMMANDS` e remove de `BORROWED_WORKERS`
   - Chama `enviar_notify_worker_returned(original_master, wid)` em thread separada

---

### `solicitar_ajuda_vizinhos(workers_needed)`

Itera sobre `NEIGHBORS`. Para cada vizinho:

1. Conecta via TCP com timeout `NEGOTIATION_TIMEOUT`
2. Envia `request_help` com estado atual
3. Se `response_accepted`: registra workers em `BORROWED_WORKERS`, decrementa `workers_needed`
4. Se `response_rejected`: loga motivo e tenta próximo
5. Para quando `workers_needed ≤ 0`

Erros de conexão (timeout, recusa) são capturados e logados; o loop continua para o próximo vizinho.

---

### `enviar_notify_worker_returned(original_master_address, worker_id)`

Abre uma nova conexão TCP ao master original e envia `notify_worker_returned`. Falhas são capturadas e logadas sem propagar.

**Parâmetros:**
- `original_master_address` (str): no formato `"host:port"`
- `worker_id` (str): UUID do worker devolvido

---

### `gerador_tarefas()`

Thread daemon. Desabilitável via `P2P_DISABLE_GENERATOR=true`.

- Aguarda 5s antes de começar
- A cada 8s: injeta 1–3 tarefas aleatórias se `len(FILA_TAREFAS) < 15`

Tarefas possíveis: `Compilar_Kernel`, `Processar_Pagamentos`, `Otimizar_Rotas`, `Analisar_Vulnerabilidades`, `Treinar_Rede_Neural`, `Sincronizar_Bancos`.

---

### `get_farm_snapshot()` *(Sprint 4)*

Coleta estado atual do sistema e retorna `dict` completo para o monitor.

```python
{
    "farm_state": {
        "workers": {
            "total_registered": int,       # len(WORKERS_ATIVOS)
            "workers_utilization": int,    # tarefas em execução agora
            "workers_alive": int,          # == total_registered
            "workers_idle": int,           # workers_alive - workers_utilization
            "workers_borrowed": int,       # len(LENT_WORKERS)
            "workers_received": int,       # len(BORROWED_WORKERS)
            "workers_failed": 0,
            "workers_home": int,           # total_registered - borrowed_in
            "workers_available_capacity": int,  # max(0, CAPACITY - tasks_pending)
            "borrowed_workers": [          # [{direction, peer_uuid}]
                {"direction": "out", "peer_uuid": "<master_id>"},  # LENT
                {"direction": "in",  "peer_uuid": "<original_addr>"},  # BORROWED
            ],
        },
        "tasks": {
            "tasks_pending": int,
            "tasks_running": int,
            "tasks_completed": int,
            "tasks_failed": int,
            "oldest_task_age_s": int,      # segundos desde o despacho mais antigo
        },
    },
    "config_thresholds": {
        "max_task": int,         # SATURATION_THRESHOLD
        "warn_cpu_percent": 85,
        "warn_memory_percent": 85,
        "release_task": int,     # RELEASE_THRESHOLD
    },
    "neighbors": [
        {
            "server_uuid": str,
            "status": "available",
            "last_heartbeat": "<ISO8601Z>",
        }
    ],
}
```

---

## Funções Auxiliares

### `log_estado_workers()`

Loga contagens de workers (locais / emprestados saída / emprestados entrada / total) a cada mudança de estado. Chamada sempre com `_lock` já adquirido.

### `validar_campos_obrigatorios(msg, campos_obrigatorios, contexto)`

```python
def validar_campos_obrigatorios(msg: dict, campos_obrigatorios: list[str], contexto: str) -> bool
```

Verifica se todos os strings em `campos_obrigatorios` são chaves do dict `msg`. Se não, loga `ERROR` com a lista de campos ausentes e retorna `False`. Retorna `True` se válido.

### `parse_mensagem(msg_str)`

```python
def parse_mensagem(msg_str: str) -> dict | None
```

Deserializa JSON. Retorna `None` se:
- JSON inválido
- Resultado não é `dict`
- Campo `type` presente mas não está em `TIPOS_MENSAGEM_VALIDOS`

Normaliza o valor de `type` para lowercase.

### `gerar_request_id()`

```python
def gerar_request_id() -> str
```

Retorna `str(uuid.uuid4())`. Usado em todas as mensagens P2P para correlação de logs.
