# Sprint 3: Protocolo Master-to-Master de Pedido de Ajuda — Especificação de Design

**Data:** 2026-05-21  
**Estado:** Aprovado e Implementado

---

## 1. Resumo Executivo

A Sprint 3 estende o sistema distribuído (Sprints 1–2) com um **protocolo master-to-master de pedido de ajuda** para balanceamento de carga. Quando um Master fica saturado (>80% de carga), ele solicita Workers de Masters vizinhos. Os doadores redirecionam temporariamente Workers para o tomador; os tomadores devolvem os Workers quando a carga normaliza (<48%, histerese).

---

## 2. Declaração do Problema

**Estado Atual (Sprints 1–2):**
- Master recebe tarefas numa fila
- Workers conectam-se, pedem tarefas, processam e reportam status
- Não existe comunicação entre Masters
- Um único Master pode virar gargalo quando sobrecarregado

**Novo Requisito (Sprint 3):**
- Masters detectam saturação (fila cresce, número limitado de workers locais)
- Solicitam ajuda a Masters vizinhos
- Emprestam Workers temporariamente sem interromper o Master original
- Liberam Workers emprestados quando a carga estabiliza

---

## 3. Visão de Arquitetura

### 3.1 Papel Duplo do Master
Cada Master atua como:
1. **Servidor** (existente): escuta na porta por Workers + mensagens Master-to-Master
2. **Cliente** (novo): inicia conexões TCP com Masters vizinhos (lista NEIGHBORS)

### 3.2 Componentes-chave

#### Thread de Monitoramento (daemon)
- Amostra o tamanho da fila e os workers locais disponíveis a cada 2 segundos
- Calcula carga = queue_size / max(1, available_workers)
- **Se carga > 80%:** inicia `request_help` para NEIGHBORS (timeout 5s por vizinho)
- **Se carga < 48% E houver workers emprestados:** libera os emprestados

#### Estruturas Partilhadas (thread-safe)
```python
workers_map = {}         # WORKER_UUID → socket.connection
borrowed_registry = {}   # WORKER_UUID → {to, host, port}
queue_lock, workers_lock, borrowed_lock  # threading.Lock
```

#### Ciclo de Requisição/Resposta
- **request_id:** UUID v4 por pedido, reutilizado na resposta
- **type:** em minúsculas (ex.: `request_help`, `response_accepted`)
- **valores de controlo:** UPPERCASE (ALIVE, ACK, OK, NOK)
- **logging:** todas as mensagens M2M logadas com timestamp + request_id + type

---

## 4. Fluxos de Mensagens

### 4.1 Pedido de Ajuda (Master A → Master B)

Formato (exemplo):
```json
{
  "type": "request_help",
  "request_id": "uuid-v4",
  "payload": {
    "from": "Master_7",
    "target_host": "127.0.0.1",
    "target_port": 5000,
    "target_server_uuid": "Master_7"
  }
}
```

**Timeout:** 5 segundos na conexão; se expirar, tenta o próximo vizinho.

---

### 4.2 Resposta Aceita (Master B → Master A)

Formato (exemplo):
```json
{
  "type": "response_accepted",
  "request_id": "<mesmo UUID>",
  "payload": { "worker_uuid": "W-123" }
}
```

**Efeito:** Master B registra W-123 em `borrowed_registry` com informação do tomador.

---

### 4.3 Resposta Rejeitada (Master B → Master A)

Formato (exemplo):
```json
{ "type": "response_rejected", "request_id": "<mesmo UUID>", "payload": {} }
```

---

### 4.4 Redirecionamento de Comando (Master B → Worker)

Após aceitar, Master B envia:
```json
{
  "type": "command_redirect",
  "request_id": "<mesmo UUID>",
  "payload": {
    "reconnect_host": "127.0.0.1",
    "reconnect_port": 5001,
    "target_server_uuid": "Master_8"
  }
}
```

**Ação do Worker:**
- Desconecta do Master B
- Atualiza SERVER_UUID para o novo Master
- Reconnecta ao host:port alvo
- Envia `register_temporary_worker` ao reconectar

---

### 4.5 Registro Temporário (Worker → Master Tomador)

Formato (exemplo):
```json
{
  "type": "register_temporary_worker",
  "request_id": "uuid-v4",
  "payload": {
    "WORKER_UUID": "W-123",
    "SERVER_UUID": "Master_8",
    "ORIGINAL_SERVER_UUID": "Master_7"
  }
}
```

**Ação do Master Tomador:**
- Registra W-123 em `workers_map`
- Regista em `borrowed_registry` a origem (Original Master)
- Loga e atualiza contador visível

---

### 4.6 Liberação de Worker (Master Tomador → Worker)

Formato (exemplo):
```json
{ "type": "command_release", "request_id": "uuid-v4", "payload": { "return_host": "127.0.0.1", "return_port": 5000 } }
```

**Ação do Worker:**
- Desconecta do tomador
- Restaura SERVER_UUID para ORIGINAL
- Reconnecta ao Master de origem

---

### 4.7 Notificar Retorno (Master Tomador → Master Doador)

Após liberação, o tomador envia:
```json
{ "type": "notify_worker_returned", "request_id": "uuid-v4", "payload": { "worker_uuid": "W-123" } }
```

**Ação do Doador:**
- Remove W-123 do `borrowed_registry`
- Loga e atualiza contador

---

## 5. Threading & Concorrência

- Locks: `queue_lock`, `workers_lock`, `borrowed_lock` protegem acessos concorrentes
- Monitor executa como daemon e mantém locks por curto período
- Cada Worker é atendido por uma thread separada

---

## 6. Robustez & Tratamento de Erros

- Campos JSON desconhecidos: ignorados silenciosamente
- Campos obrigatórios ausentes: logados e ignorados; sistema não deve cair
- Timeouts por vizinho: 5s; em timeout, tenta próximo vizinho
- Falhas na notificação não quebram o fluxo principal

---

## 7. Thresholds & Histerese

- Saturação: 80% (0.8) → aciona pedido de ajuda
- Liberação: 48% (0.6 × 0.8) → aciona retorno de workers
- Intervalo do monitor: 2s
- Timeout de requisição: 5s

Histerese evita ping-pong entre Masters.

---

## 8. Logging & Observabilidade

Formato M2M: `%(asctime)s M2M <request_id> <type> [info]`
Exemplo de contador impresso:
```
[CONTADOR] Local workers: 1 | Borrowed workers: 1 | Load: 2.50
```

---

## 9. Integração com Sprints 1–2

- Protocolo Worker (ALIVE, WORKER_UUID, SERVER_UUID) permanece igual
- Lógica de filas e ACK/STATUS não foi alterada
- Mensagens M2M detectadas pela presença do campo `type`

---

## 10. Configuração & Deploy

Parâmetros por Master (exemplo):
```python
HOST = '127.0.0.1'
PORT = 5000
SERVER_UUID = 'Master_7'
NEIGHBORS = [('127.0.0.1', 5001)]
```

---

## 11. Cenários de Teste

1. Empréstimo simples — Master A solicita, Master B aceita, Worker redirecionado e registrado
2. Liberação após normalização — Master A envia command_release e Worker retorna
3. Timeout & retry — se vizinho não responder em 5s, tenta próximo

---

## 12. Melhorias Futuras (Fora do Escopo)

- Seleção round-robin de vizinhos
- Afinidade de workers
- Empréstimos múltiplos por pedido
- Telemetria/metrics export

---

**Fim da Especificação**