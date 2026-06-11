# Worker Node — Referência Técnica

**Arquivo:** `src/worker.py` | **Sprints:** 01, 02, 03

## Visão Geral

O Worker é um nó executor de tarefas que se conecta a um Master via TCP. Suporta redirecionamento dinâmico (empréstimo P2P): ao receber `command_redirect`, migra para outro master temporariamente; ao receber `command_release`, retorna ao master de origem.

## Constantes

| Constante | Valor padrão / Env var | Descrição |
|---|---|---|
| `HOST` | `P2P_HOST` / `10.62.217.11` | IP do master inicial |
| `PORT` | `P2P_PORT` / `5000` | Porta do master |
| `HEARTBEAT_INTERVAL` | `P2P_HEARTBEAT_INTERVAL` / `5` | Segundos entre heartbeats |
| `SERVER_UUID` | `P2P_SERVER_UUID` / `Master_Local` | UUID do master ao qual se conecta |
| `WORKER_UUID` | `P2P_WORKER_UUID` / `Worker_Local` | Identificador único deste worker |
| `DELIMITER` | `\n` | Separador de mensagens JSON |

## Estado Global

| Variável | Tipo | Descrição |
|---|---|---|
| `current_master_addr` | `tuple[str, int]` | Endereço do master atual; atualizado a cada `command_redirect` ou `command_release` |

## Funções

### `start_worker()`

Ponto de entrada. Inicialização:

1. Registra `host_atual = HOST`, `porta_atual = PORT`
2. Salva `master_original = f"{HOST}:{PORT}"` (imutável durante a sessão)
3. Seta `is_borrowed = False`
4. Inicia thread daemon `heartbeat_loop`

**Loop principal de conexão:**

```
LOOP:
  1. Conectar TCP a (host_atual, porta_atual) com timeout 5s
  │
  2. Se is_borrowed == True:
  │    Enviar register_temporary_worker {worker_id, original_master_address}
  │
  3. Enviar ALIVE {WORKER, WORKER_UUID [, SERVER_UUID se is_borrowed]}
  │
  4. Aguardar resposta (até receber DELIMITER):
  │
  ├─ command_redirect:
  │    host_atual, porta_atual ← new_master_address
  │    current_master_addr ← (host_atual, porta_atual)
  │    is_borrowed ← True
  │    → continue (reconectar ao novo master)
  │
  ├─ command_release:
  │    host_atual, porta_atual ← HOST, PORT
  │    current_master_addr ← (HOST, PORT)
  │    is_borrowed ← False
  │    → continue (reconectar ao master original)
  │
  ├─ TASK: QUERY:
  │    sleep(random.randint(1, 3))
  │    status = "NOK" if random.random() < 0.1 else "OK"
  │    Enviar STATUS {STATUS, TASK: "QUERY", WORKER_UUID}
  │    Aguardar ACK (lê até DELIMITER)
  │    → loop (conexão fecha, reconectar)
  │
  └─ TASK: NO_TASK:
       sleep(HEARTBEAT_INTERVAL)
       → loop (reconectar)

  Em ConnectionRefusedError / ConnectionResetError / OSError / timeout:
  ├─ is_borrowed == True:
  │    host_atual, porta_atual ← HOST, PORT
  │    current_master_addr ← (HOST, PORT)
  │    is_borrowed ← False
  │    sleep(2) → loop
  └─ is_borrowed == False:
       sleep(5) → loop
```

Encerramento via `KeyboardInterrupt`: loga `OFFLINE` e chama `os._exit(0)`.

---

### `heartbeat_loop()`

Thread daemon independente. A cada `HEARTBEAT_INTERVAL` segundos:

1. Abre nova conexão TCP ao `current_master_addr` com timeout 5s
2. Envia `{SERVER_UUID, TASK: "HEARTBEAT"}`
3. Lê resposta e verifica `RESPONSE == "ALIVE"`
4. Exceções são capturadas e logadas como `WARNING` — **não interrompem o worker**

> **Importante:** O heartbeat usa `current_master_addr`, que é o endereço atual do master (incluindo após redirecionamento). Thread separada não interfere no loop principal de tarefas.

## Simulação de Falha

```python
status = "NOK" if random.random() < 0.1 else "OK"
```

~10% de chance de reportar falha em cada tarefa processada. O master contabiliza ambos (`_tasks_completed` e `_tasks_failed`).
