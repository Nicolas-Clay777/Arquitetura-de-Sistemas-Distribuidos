# Arquitetura do Sistema P2P

## Visão Geral

O sistema implementa uma **farm de workers distribuída** onde múltiplos nós Master se conectam em uma topologia P2P pré-configurada. Cada Master mantém sua própria fila de tarefas e pool de workers locais. Quando a fila satura, o Master solicita workers emprestados aos vizinhos; quando a carga normaliza, os workers são devolvidos.

## Componentes

```
┌─────────────────────────────────────────────────────────┐
│                    NODO MASTER                          │
│  ┌──────────────┐  ┌────────────┐  ┌────────────────┐  │
│  │ TCP Server   │  │ monitor_   │  │ gerador_       │  │
│  │ :8000        │  │ carga()    │  │ tarefas()      │  │
│  │ (handle_     │  │ thread     │  │ thread         │  │
│  │  client)     │  │            │  │                │  │
│  └──────┬───────┘  └─────┬──────┘  └───────┬────────┘  │
│         │                │                 │            │
│  ┌──────▼───────────────▼─────────────────▼────────┐   │
│  │          ESTADO COMPARTILHADO (thread-safe)      │   │
│  │  WORKERS_ATIVOS | LENT_WORKERS | BORROWED_WORKERS│   │
│  │  PENDING_WORKER_COMMANDS | FILA_TAREFAS          │   │
│  └──────────────────────────────────────────────────┘   │
│                         │                               │
│  ┌──────────────────────▼──────────────────────────┐   │
│  │            Sprint4-Monitor Thread               │   │
│  │  _monitor_loop() → build_payload() →            │   │
│  │  send_to_supervisor() [TLS/TCP nuted-ia.dev:443] │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
          │ TCP P2P                    │ TCP P2P
          ▼                            ▼
┌─────────────────┐          ┌─────────────────┐
│  MASTER VIZINHO │◄────────►│  MASTER VIZINHO │
│  10.62.217.208  │          │  10.62.217.39   │
└─────────────────┘          └─────────────────┘

┌──────────────────────────────────────┐
│            WORKER NODE               │
│  ┌─────────────┐  ┌───────────────┐  │
│  │ start_worker│  │ heartbeat_    │  │
│  │ main loop   │  │ loop() thread │  │
│  └──────┬──────┘  └───────────────┘  │
│         │ TCP ALIVE / TASK / STATUS  │
│         ▼                            │
│    current_master_addr               │
│    (muda por command_redirect)       │
└──────────────────────────────────────┘
```

## Fluxo de Histerese (Balanceamento Dinâmico)

```
carga da fila > SATURATION_THRESHOLD (10)?
  └─ SIM → solicitar_ajuda_vizinhos()
           └─ Para cada vizinho: envia request_help
              ├─ Vizinho responde accepted → workers redirecionados
              └─ Vizinho responde rejected → tenta próximo vizinho

carga da fila < RELEASE_THRESHOLD (4)?
  └─ SIM + tem BORROWED_WORKERS?
           ├─ Enviar command_release para cada worker emprestado
           └─ Enviar notify_worker_returned para master original
```

## Ciclo de Vida de um Worker Emprestado

```
[Master A satura] ──request_help──► [Master B]
                                         │
                              Master B responde accepted
                              Master B enfileira command_redirect
                                         │
[Worker X envia ALIVE] ◄── Master A entrega command_redirect
         │
Worker X migra → conecta em Master B
Worker X envia register_temporary_worker
Master B registra Worker X em BORROWED_WORKERS
Worker X executa tarefas para Master B
         │
[Master A normaliza]
Master A enfileira command_release para Worker X
Master B entrega command_release no próximo ALIVE do Worker X
         │
Worker X retorna ao Master A
Master B envia notify_worker_returned ao Master A
Master A remove Worker X de LENT_WORKERS
```

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `P2P_HOST` | `10.62.217.11` | IP do nó na rede |
| `P2P_PORT` | `8000` (master) / `5000` (worker) | Porta de escuta/conexão |
| `P2P_HEARTBEAT_INTERVAL` | `5` | Segundos entre heartbeats |
| `P2P_SERVER_UUID` | `Master_Local` | Identificador único do Master |
| `P2P_WORKER_UUID` | `Worker_Local` | Identificador único do Worker |
| `P2P_NEIGHBORS` | lista estática | JSON array de vizinhos |
| `P2P_NUM_TASKS` | `30` | Número de tarefas iniciais na fila |
| `P2P_EMPTY_TASKS` | `false` | Iniciar com fila vazia |
| `P2P_DISABLE_GENERATOR` | `false` | Desabilitar gerador automático de tarefas |
