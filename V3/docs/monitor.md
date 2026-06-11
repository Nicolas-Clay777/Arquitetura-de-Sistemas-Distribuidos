# Monitor — Referência Técnica (Sprint 4)

**Arquivo:** `src/monitor.py` | **Sprint:** 04

## Visão Geral

O Monitor é uma **thread daemon** (`Sprint4-Monitor`) iniciada pelo Master durante o startup. A cada `MONITOR_INTERVAL` (10 segundos), coleta métricas do sistema e do estado da farm, monta um payload JSON padronizado e o envia ao servidor supervisor externo via TLS/TCP — **fire-and-forget** (sem aguardar resposta).

## Configuração

| Constante | Valor | Descrição |
|---|---|---|
| `TCP_SOCKET_HOST` | `nuted-ia.dev` | Hostname do servidor supervisor |
| `TCP_SOCKET_PORT` | `443` | Porta TLS |
| `TCP_SOCKET_TLS` | `True` | Habilitar TLS |
| `TCP_SOCKET_SNI` | `nuted-ia.dev` | SNI para handshake TLS |
| `MONITOR_INTERVAL` | `10` | Intervalo de envio em segundos |

## Funções

### `start_monitor(server_uuid, get_farm_snapshot)`

Ponto de entrada. Cria e inicia a thread daemon `Sprint4-Monitor`. Retorna o objeto `Thread`.

```python
def start_monitor(server_uuid: str, get_farm_snapshot: callable) -> threading.Thread
```

**Parâmetros:**
- `server_uuid` (str): UUID do master que iniciou o monitor (ex: `"Master_Local"`)
- `get_farm_snapshot` (callable → dict): função sem argumentos que retorna o estado atual da farm (ver `master.get_farm_snapshot()`)

---

### `_monitor_loop(server_uuid, get_farm_snapshot)`

Loop infinito interno da thread. Sequência por iteração:

```
get_farm_snapshot()
  ↓
build_payload(server_uuid, snapshot)
  ↓
send_to_supervisor(payload)
  ↓
sleep(MONITOR_INTERVAL)
```

Qualquer exceção dentro do loop é capturada e logada como `ERROR` — o loop continua.

---

### `build_payload(server_uuid, farm_snapshot)`

Monta o payload JSON de acordo com a especificação Sprint 4.

```python
def build_payload(server_uuid: str, farm_snapshot: dict) -> dict
```

**Retorna:**

```json
{
  "server_uuid": "Master_Local",
  "hostname": "Master_Local.farm.local",
  "role": "master",
  "task": "performance_report",
  "timestamp": "2026-06-10T12:00:00Z",
  "message_id": "<uuid4>",
  "payload_version": "sprint4-monitor",
  "performance": {
    "system": {
      "uptime_seconds": 3600,
      "load_average_1m": 0.42,
      "load_average_5m": 0.35,
      "cpu": {
        "usage_percent": 12.5,
        "count_logical": 8,
        "count_physical": 4
      },
      "memory": {
        "total_mb": 16384,
        "available_mb": 8192,
        "percent_used": 50.0,
        "memory_used": 8192
      },
      "disk": {
        "total_gb": 512.0,
        "free_gb": 256.0,
        "percent_used": 50.0
      }
    },
    "farm_state": { ... },
    "config_thresholds": { ... },
    "neighbors": [ ... ]
  }
}
```

O campo `"timestamp"` usa UTC em formato ISO 8601 (`%Y-%m-%dT%H:%M:%SZ`). O `"message_id"` é um UUID4 gerado a cada envio.

---

### `_get_system_metrics()`

Coleta métricas reais do sistema via `psutil`. Se `psutil` não estiver instalado, retorna zeros sem lançar exceção.

```python
def _get_system_metrics() -> dict
```

**Detalhes de plataforma:**
- **Windows:** caminho de disco = `C:\`
- **Linux/macOS:** caminho de disco = `/`
- **Windows:** `psutil.getloadavg()` pode não existir; nesse caso retorna `(0.0, 0.0, 0.0)`

**Instalação:**
```bash
pip install psutil
```

---

### `send_to_supervisor(payload)`

Envia o payload ao supervisor via TLS sobre TCP.

```python
def send_to_supervisor(payload: dict) -> None
```

**Sequência:**
1. Cria contexto TLS com `ssl.create_default_context()` (valida certificado)
2. Abre `socket.create_connection((TCP_SOCKET_HOST, TCP_SOCKET_PORT), timeout=10)`
3. Encapsula com `context.wrap_socket(..., server_hostname=TCP_SOCKET_SNI)`
4. Serializa payload como UTF-8 e chama `tls_sock.sendall(data)`
5. **Não faz `recv`** — fire-and-forget conforme especificação

Falhas (timeout, erro de rede, certificado inválido) são capturadas e logadas como `WARNING`. O loop de monitoramento continua normalmente após falhas.

## Integração com o Master

O master chama `start_monitor` durante `start_master()`:

```python
# Em master.py — start_master()
start_monitor(SERVER_UUID, get_farm_snapshot)
```

O monitor usa `get_farm_snapshot` como callback para ler o estado da farm de forma thread-safe (a função já usa os locks internos do master).

## Log de Atividade

| Evento | Nível | Mensagem |
|---|---|---|
| Monitor iniciado | `INFO` | `[Monitor] Sprint 4 — Monitor iniciado. Enviando a cada 10s para nuted-ia.dev:443 (TLS)` |
| Payload enviado com sucesso | `INFO` | `[Monitor] Payload enviado ao supervisor (...) — message_id=<uuid>` |
| Falha no envio | `WARNING` | `[Monitor] Falha ao enviar payload ao supervisor: <erro>` |
| `psutil` ausente | `WARNING` | `[Monitor] psutil nao encontrado — metricas de sistema indisponiveis.` |
| Erro no loop | `ERROR` | `[Monitor] Erro no loop de monitoramento: <erro>` |
