#!/usr/bin/env python3
"""
=======================================================================
  MONITOR — Sprint 4: Camada de Monitoramento do Cluster
  Envia relatórios de performance via TLS/TCP para o supervisor.
=======================================================================
"""

import ssl
import json
import time
import uuid
import os
import socket
import logging
import threading
import platform
from datetime import datetime, timezone

logger = logging.getLogger("p2p")

# =====================================================================
# CONFIGURAÇÕES DO SUPERVISOR
# =====================================================================
TCP_SOCKET_HOST = "nuted-ia.dev"
TCP_SOCKET_PORT = 443
TCP_SOCKET_TLS = True
TCP_SOCKET_SNI = "nuted-ia.dev"

MONITOR_INTERVAL = 10  # segundos


# =====================================================================
# COLETA DE MÉTRICAS DO SISTEMA
# =====================================================================
def _get_system_metrics():
    """Coleta métricas reais do sistema usando psutil."""
    try:
        import psutil

        uptime = int(time.time() - psutil.boot_time())

        # Windows não possui os.getloadavg; psutil.getloadavg pode não existir
        if hasattr(psutil, "getloadavg"):
            load = psutil.getloadavg()
        else:
            load = (0.0, 0.0, 0.0)

        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_logical = psutil.cpu_count(logical=True) or 1
        cpu_physical = psutil.cpu_count(logical=False) or 1

        mem = psutil.virtual_memory()

        # Disco: Windows usa 'C:\\', Linux usa '/'
        disk_path = "C:\\" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(disk_path)

        return {
            "uptime_seconds": uptime,
            "load_average_1m": round(load[0], 2),
            "load_average_5m": round(load[1], 2),
            "cpu": {
                "usage_percent": round(cpu_percent, 2),
                "count_logical": cpu_logical,
                "count_physical": cpu_physical,
            },
            "memory": {
                "total_mb": int(mem.total / (1024 * 1024)),
                "available_mb": int(mem.available / (1024 * 1024)),
                "percent_used": round(mem.percent, 2),
                "memory_used": int(mem.used / (1024 * 1024)),
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 1),
                "free_gb": round(disk.free / (1024**3), 1),
                "percent_used": round(disk.percent, 1),
            },
        }
    except ImportError:
        logger.warning("[Monitor] psutil nao encontrado — metricas de sistema indisponiveis.")
        cpu_count = os.cpu_count() or 1
        return {
            "uptime_seconds": 0,
            "load_average_1m": 0.0,
            "load_average_5m": 0.0,
            "cpu": {
                "usage_percent": 0.0,
                "count_logical": cpu_count,
                "count_physical": cpu_count,
            },
            "memory": {
                "total_mb": 0,
                "available_mb": 0,
                "percent_used": 0.0,
                "memory_used": 0,
            },
            "disk": {
                "total_gb": 0.0,
                "free_gb": 0.0,
                "percent_used": 0.0,
            },
        }


# =====================================================================
# MONTAGEM DO PAYLOAD
# =====================================================================
def build_payload(server_uuid, farm_snapshot):
    """Monta o payload JSON conforme especificação da Sprint 4."""
    system_metrics = _get_system_metrics()

    return {
        "server_uuid": server_uuid,
        "hostname": f"{server_uuid}.farm.local",
        "role": "master",
        "task": "performance_report",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "message_id": str(uuid.uuid4()),
        "payload_version": "sprint4-monitor",
        "performance": {
            "system": system_metrics,
            "farm_state": farm_snapshot["farm_state"],
            "config_thresholds": farm_snapshot["config_thresholds"],
            "neighbors": farm_snapshot["neighbors"],
        },
    }


# =====================================================================
# ENVIO VIA TLS/TCP (fire-and-forget)
# =====================================================================
def send_to_supervisor(payload):
    """Envia payload ao supervisor via TLS sobre TCP. Sem recv/resposta."""
    try:
        context = ssl.create_default_context()
        with socket.create_connection(
            (TCP_SOCKET_HOST, TCP_SOCKET_PORT), timeout=10
        ) as raw_sock:
            with context.wrap_socket(
                raw_sock, server_hostname=TCP_SOCKET_SNI
            ) as tls_sock:
                data = json.dumps(payload).encode("utf-8")
                tls_sock.sendall(data)
                # Não faz recv — fire-and-forget conforme especificação
        logger.info(
            f"[Monitor] Payload enviado ao supervisor "
            f"({TCP_SOCKET_HOST}:{TCP_SOCKET_PORT}) — "
            f"message_id={payload.get('message_id', '?')}"
        )
    except Exception as e:
        logger.warning(f"[Monitor] Falha ao enviar payload ao supervisor: {e}")


# =====================================================================
# LOOP PRINCIPAL DO MONITOR
# =====================================================================
def _monitor_loop(server_uuid, get_farm_snapshot):
    """Loop que roda em daemon thread, enviando métricas a cada MONITOR_INTERVAL."""
    logger.info(
        f"[Monitor] Sprint 4 — Monitor iniciado. "
        f"Enviando a cada {MONITOR_INTERVAL}s para {TCP_SOCKET_HOST}:{TCP_SOCKET_PORT} (TLS)"
    )
    while True:
        try:
            snapshot = get_farm_snapshot()
            payload = build_payload(server_uuid, snapshot)
            send_to_supervisor(payload)
        except Exception as e:
            logger.error(f"[Monitor] Erro no loop de monitoramento: {e}")
        time.sleep(MONITOR_INTERVAL)


def start_monitor(server_uuid, get_farm_snapshot):
    """Inicia a thread daemon de monitoramento. Retorna a thread."""
    t = threading.Thread(
        target=_monitor_loop,
        args=(server_uuid, get_farm_snapshot),
        daemon=True,
        name="Sprint4-Monitor",
    )
    t.start()
    return t
