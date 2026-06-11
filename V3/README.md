# Arquitetura de Sistemas Distribuídos — Sistema P2P

**Grupo 7** | Nicolas Clay, João Victor Aires e Rafael Gouveia

Sistema de farm distribuída com balanceamento de carga dinâmico via protocolo P2P.
Workers são emprestados entre nós Master conforme thresholds de saturação/liberação.

## Pré-requisitos

- Python 3.9+
- `psutil` (opcional — para métricas de CPU/memória/disco no Monitor):

```bash
pip install psutil
```

## Executando

**Master:**
```bash
P2P_SERVER_UUID=Master_01 P2P_HOST=<seu_ip> python src/master.py
```

**Worker:**
```bash
P2P_WORKER_UUID=Worker_01 P2P_HOST=<ip_do_master> P2P_PORT=8000 python src/worker.py
```

## Documentação Completa

→ [docs/README.md](docs/README.md)

## Estrutura do Projeto

```
V3/
├── src/
│   ├── master.py    # Nó coordenador (Sprints 01–04)
│   ├── worker.py    # Nó executor de tarefas (Sprints 01–03)
│   └── monitor.py   # Agente de telemetria TLS (Sprint 04)
└── docs/
    ├── README.md        # Índice da documentação
    ├── architecture.md  # Diagrama e fluxos do sistema
    ├── protocol.md      # Especificação do protocolo de mensagens
    ├── master.md        # Referência técnica do Master
    ├── worker.md        # Referência técnica do Worker
    └── monitor.md       # Referência técnica do Monitor
```