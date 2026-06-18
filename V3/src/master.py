#!/usr/bin/env python3
"""
=======================================================================
  MASTER NODE — Sistema P2P com Balanceamento de Carga Dinâmico
  Arquivo consolidado (master)
  Sprints 01, 02, 03 e 04
=======================================================================
"""

import os
import sys
import json
import uuid
import time
import socket
import random
import logging
import threading
from datetime import datetime, timezone

from monitor import start_monitor

# =====================================================================
# CONFIGURAÇÕES 
# =====================================================================
MEU_IP_NA_REDE = '127.0.0.1'
MINHA_PORTA = 8000

# Para se conectar ao PC do seu amigo, tire o # e coloque o IP dele:
MEUS_VIZINHOS_FIXOS = [
    {"id": "Master_Amigo", "host": "10.62.217.208", "port": 8000},
    {"id": "Master_Amigo2", "host": "10.62.217.39", "port": 8000},

]

HOST = os.environ.get("P2P_HOST", MEU_IP_NA_REDE)
PORT = int(os.environ.get("P2P_PORT", MINHA_PORTA))
DELIMITER = '\n'
HEARTBEAT_INTERVAL = int(os.environ.get("P2P_HEARTBEAT_INTERVAL", 5))

SERVER_UUID = os.environ.get("P2P_SERVER_UUID", "master_7.A.local")
WORKER_UUID = os.environ.get("P2P_WORKER_UUID", "worker_7.A.local")

CAPACITY = 10
SATURATION_THRESHOLD = 10
RELEASE_THRESHOLD = 4
NEGOTIATION_TIMEOUT = 5
TIMEOUT_NEGOCIACAO = NEGOTIATION_TIMEOUT
LOAD_CHECK_INTERVAL = 3

# Parse NEIGHBORS
neighbors_env = os.environ.get("P2P_NEIGHBORS")
if neighbors_env:
    try:
        NEIGHBORS = json.loads(neighbors_env)
    except Exception:
        NEIGHBORS = MEUS_VIZINHOS_FIXOS
else:
    NEIGHBORS = MEUS_VIZINHOS_FIXOS

MASTERS_VIZINHOS = [(n["host"], n["port"]) for n in NEIGHBORS]

# Logging com timestamps
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("p2p")

# =====================================================================
# PROCESSADOR DE MENSAGENS 
# =====================================================================
if os.environ.get("P2P_EMPTY_TASKS") == "true":
    FILA_TAREFAS = []
else:
    num_tasks = int(os.environ.get("P2P_NUM_TASKS", 30))
    FILA_TAREFAS = ([
        "Compilar_Kernel", "Processar_Pagamentos", "Otimizar_Rotas",
        "Analisar_Vulnerabilidades", "Treinar_Rede_Neural", "Sincronizar_Bancos"
    ] * 5)[:num_tasks]

_tarefas_concluidas_avisado = False

fila_lock = threading.Lock()


def gerar_request_id():
    return str(uuid.uuid4())


TIPOS_MENSAGEM_VALIDOS = {
    "request_help", "response_accepted", "response_rejected",
    "command_redirect", "register_temporary_worker", "command_release",
    "notify_worker_returned"
}

CAMPOS_OBRIGATORIOS = {
    "request_help": ["master_id", "current_load", "capacity", "workers_needed"],
    "response_accepted": ["workers_offered", "worker_details"],
    "response_rejected": ["reason"],
    "command_redirect": ["new_master_address"],
    "register_temporary_worker": ["worker_id", "original_master_address"],
    "command_release": ["original_master_address"],
    "notify_worker_returned": ["worker_id"],
}


def validar_campos_obrigatorios(msg, campos_obrigatorios, contexto=""):
    """Verifica se todos os campos obrigatorios estao presentes.
    Retorna True se valido, False se invalido (com log)."""
    faltando = [c for c in campos_obrigatorios if c not in msg]
    if faltando:
        logger.error(
            f"[PARSING] Campos obrigatorios ausentes em {contexto}: {faltando}. "
            f"Mensagem ignorada."
        )
        return False
    return True


def parse_mensagem(msg_str):
    try:
        msg = json.loads(msg_str)
        if not isinstance(msg, dict):
            return None
        if "type" in msg:
            tipo = str(msg["type"]).lower()
            msg["type"] = tipo
            if tipo not in TIPOS_MENSAGEM_VALIDOS:
                logger.warning(f"[LOG] Tipo de mensagem desconhecido ignorado: {tipo}")
                return None
        return msg
    except json.JSONDecodeError:
        logger.error("[LOG] Erro ao decodificar JSON da mensagem.")
        return None
    except Exception as e:
        logger.error(f"[LOG] Erro inesperado ao processar mensagem: {e}")
        return None


def processar_requisicao_worker(msg, worker_id, is_borrowed=False):
    global _tarefas_concluidas_avisado, _tasks_completed, _tasks_failed
    response = {}
    if msg.get("TASK") == "HEARTBEAT":
        response = {
            "SERVER_UUID": SERVER_UUID,
            "TASK": "HEARTBEAT",
            "RESPONSE": "ALIVE"
        }
        logger.info(f"[Master] Heartbeat recebido -> Respondendo ALIVE")
    elif msg.get("WORKER") == "ALIVE":
        with fila_lock:
            if FILA_TAREFAS:
                tarefa = FILA_TAREFAS.pop(0)
                response = {"TASK": "QUERY", "USER": tarefa}
                if is_borrowed:
                    logger.info(f"[Master] Enviando '{tarefa}' para Worker EMPRESTADO {worker_id}")
                else:
                    logger.info(f"[Master] Enviando '{tarefa}' para Worker LOCAL {worker_id}")
                # Sprint 4: registrar despacho de tarefa
                with _monitor_lock:
                    _task_dispatch_times[worker_id] = time.time()
            else:
                if not _tarefas_concluidas_avisado:
                    logger.info(f"[Master] Todas as tarefas foram concluidas!")
                    _tarefas_concluidas_avisado = True
                response = {"TASK": "NO_TASK"}
    elif msg.get("STATUS") in ["OK", "NOK"]:
        status = msg.get("STATUS")
        if is_borrowed:
            logger.info(f"[Master] Worker EMPRESTADO {worker_id} reportou {status}")
        else:
            logger.info(f"[Master] Worker LOCAL {worker_id} reportou {status}")
        response = {"STATUS": "ACK", "WORKER_UUID": worker_id}
        # Sprint 4: contabilizar conclusão/falha
        with _monitor_lock:
            if status == "OK":
                _tasks_completed += 1
            else:
                _tasks_failed += 1
            _task_dispatch_times.pop(worker_id, None)
    return response


# =====================================================================
# MASTER — ESTADO E LÓGICA PRINCIPAL
# =====================================================================

# State tracking (thread-safe)
WORKERS_ATIVOS = {}            # maps worker_id -> addr (connection client address)
LENT_WORKERS = {}              # maps worker_id -> borrower_master_id
BORROWED_WORKERS = {}          # maps worker_id -> original_master_address
PENDING_WORKER_COMMANDS = {}   # maps worker_id -> pending command dict

BORROWED_WORKER_TASKS = {}     # tracks tasks executed per borrowed worker

_lock = threading.Lock()

# =====================================================================
# SPRINT 4 — Contadores de monitoramento (não alteram lógica existente)
# =====================================================================
_tasks_completed = 0
_tasks_failed = 0
_task_dispatch_times = {}      # worker_id -> timestamp de quando recebeu tarefa
_monitor_lock = threading.Lock()


def log_estado_workers():
    """Exibe contadores de workers a cada mudanca de estado."""
    locais = [w for w in WORKERS_ATIVOS if w not in BORROWED_WORKERS and w not in LENT_WORKERS]
    logger.info(
        f"[ESTADO] Workers Locais: {len(locais)} | "
        f"Emprestados (de nos): {len(LENT_WORKERS)} | "
        f"Emprestados (para nos): {len(BORROWED_WORKERS)} | "
        f"Total Ativos: {len(WORKERS_ATIVOS)}"
    )


def handle_client(conn, addr):
    with conn:
        try:
            data = ""
            while True:
                chunk = conn.recv(1024).decode()
                if not chunk:
                    break
                data += chunk

                if DELIMITER in data:
                    keep_open = False
                    mensagens = data.split(DELIMITER)
                    for msg_str in mensagens[:-1]:
                        msg = parse_mensagem(msg_str)
                        if not msg:
                            continue

                        # 1. request_help message handling (neighbor requests workers from us)
                        if msg.get("type") == "request_help":
                            payload = msg.get("payload", {})
                            if not validar_campos_obrigatorios(payload, CAMPOS_OBRIGATORIOS["request_help"], "request_help"):
                                continue
                            master_solicitante_id = payload['master_id']
                            workers_needed = payload.get('workers_needed', 1)
                            request_id = msg.get("request_id")

                            logger.info(f"[P2P][RECV] type=request_help | request_id={request_id} | De {master_solicitante_id} (precisa de {workers_needed} workers)")

                            with _lock:
                                # Determine available local workers (not lent, not borrowed)
                                workers_disponiveis = [
                                    wid for wid in WORKERS_ATIVOS
                                    if wid not in LENT_WORKERS and wid not in BORROWED_WORKERS
                                ]
                                with fila_lock:
                                    carga_local = len(FILA_TAREFAS)

                                # Hysteresis logic for rejection
                                if carga_local >= SATURATION_THRESHOLD:
                                    reason = "high_load"
                                elif not workers_disponiveis:
                                    reason = "no_workers_available"
                                else:
                                    reason = None

                                if reason:
                                    resposta = {
                                        "type": "response_rejected",
                                        "request_id": request_id,
                                        "payload": {"reason": reason}
                                    }
                                    logger.info(f"[P2P][SEND] type=response_rejected | request_id={request_id} | Recusamos o pedido de {master_solicitante_id}. Motivo: {reason}")
                                    conn.sendall((json.dumps(resposta) + DELIMITER).encode())
                                else:
                                    # Lend workers
                                    workers_a_emprestar = workers_disponiveis[:min(workers_needed, len(workers_disponiveis))]

                                    # Lookup master address in NEIGHBORS
                                    master_solicitante_address = None
                                    for neighbor in NEIGHBORS:
                                        if neighbor.get("id") == master_solicitante_id:
                                            master_solicitante_address = f"{neighbor['host']}:{neighbor['port']}"
                                            break
                                    if not master_solicitante_address:
                                        master_solicitante_address = f"{addr[0]}:{PORT}"

                                    resposta = {
                                        "type": "response_accepted",
                                        "request_id": request_id,
                                        "payload": {
                                            "workers_offered": len(workers_a_emprestar),
                                            "worker_details": [{"id": wid, "address": f"{HOST}:{PORT}"} for wid in workers_a_emprestar]
                                        }
                                    }
                                    logger.info(f"[P2P][SEND] type=response_accepted | request_id={request_id} | Emprestando {workers_a_emprestar}")
                                    conn.sendall((json.dumps(resposta) + DELIMITER).encode())

                                    # Queue redirect commands
                                    for wid in workers_a_emprestar:
                                        LENT_WORKERS[wid] = master_solicitante_id
                                        req_id_redir = gerar_request_id()
                                        PENDING_WORKER_COMMANDS[wid] = {
                                            "type": "command_redirect",
                                            "request_id": req_id_redir,
                                            "payload": {"new_master_address": master_solicitante_address}
                                        }
                                        logger.info(f"[P2P][SEND] type=command_redirect | request_id={req_id_redir} | Enfileirado para Worker {wid}")
                                    log_estado_workers()
                            continue

                        # 2. register_temporary_worker message handling
                        if msg.get("type") == "register_temporary_worker":
                            payload = msg.get("payload", {})
                            if not validar_campos_obrigatorios(payload, CAMPOS_OBRIGATORIOS["register_temporary_worker"], "register_temporary_worker"):
                                continue
                            worker_id_temp = payload['worker_id']
                            master_origem = payload['original_master_address']
                            with _lock:
                                BORROWED_WORKERS[worker_id_temp] = master_origem
                                WORKERS_ATIVOS[worker_id_temp] = addr
                                log_estado_workers()
                            logger.info(f"[P2P][RECV] type=register_temporary_worker | request_id={msg.get('request_id')} | Worker emprestado registrado: {worker_id_temp} (origem: {master_origem})")
                            keep_open = True
                            continue

                        # 3. notify_worker_returned message handling
                        if msg.get("type") == "notify_worker_returned":
                            payload = msg.get("payload", {})
                            if not validar_campos_obrigatorios(payload, CAMPOS_OBRIGATORIOS["notify_worker_returned"], "notify_worker_returned"):
                                continue
                            worker_devolvido = payload['worker_id']
                            with _lock:
                                LENT_WORKERS.pop(worker_devolvido, None)
                                log_estado_workers()
                            logger.info(f"[P2P][RECV] type=notify_worker_returned | request_id={msg.get('request_id')} | Worker {worker_devolvido} devolvido pelo vizinho e reintegrado à farm.")
                            continue

                        # 4. Standard worker handling
                        # Validate worker messages
                        if "WORKER" in msg:
                            if not validar_campos_obrigatorios(msg, ["WORKER", "WORKER_UUID"], "worker_alive"):
                                continue
                        elif "STATUS" in msg:
                            if not validar_campos_obrigatorios(msg, ["STATUS", "TASK", "WORKER_UUID"], "worker_status"):
                                continue

                        worker_id = msg.get("WORKER_UUID", "Desconhecido")
                        with _lock:
                            WORKERS_ATIVOS[worker_id] = addr
                            if msg.get("WORKER") == "ALIVE" and worker_id not in BORROWED_WORKERS and worker_id not in LENT_WORKERS:
                                log_estado_workers()

                        if msg.get("SERVER_UUID"):
                            logger.info(f"[Master] Worker EMPRESTADO {worker_id} (origem: {msg['SERVER_UUID']}) se reportou.")

                        # If worker sends ALIVE, check if there is a pending command
                        if msg.get("WORKER") == "ALIVE":
                            command = None
                            with _lock:
                                if worker_id in PENDING_WORKER_COMMANDS:
                                    command = PENDING_WORKER_COMMANDS.pop(worker_id)
                            if command:
                                logger.info(f"[Master] Enviando comando pendente ({command['type']}) para Worker {worker_id}")
                                conn.sendall((json.dumps(command) + DELIMITER).encode())
                                continue

                        is_borrowed = worker_id in BORROWED_WORKERS
                        if is_borrowed and msg.get("WORKER") == "ALIVE":
                            BORROWED_WORKER_TASKS[worker_id] = BORROWED_WORKER_TASKS.get(worker_id, 0) + 1
                        resposta = processar_requisicao_worker(msg, worker_id, is_borrowed=is_borrowed)
                        if resposta:
                            conn.sendall((json.dumps(resposta) + DELIMITER).encode())
                            if resposta.get("TASK") == "QUERY":
                                keep_open = True
                            else:
                                keep_open = False

                    data = mensagens[-1]
                    if not keep_open:
                        break
        except Exception as e:
            logger.error(f"[Master] Erro no handler do cliente {addr}: {e}")


def enviar_notify_worker_returned(original_master_address, worker_id):
    try:
        host, port = original_master_address.split(":")
        port = int(port)
        logger.info(f"[P2P][SEND] type=notify_worker_returned | Conectando a original Master {original_master_address} para notificar retorno de {worker_id}...")
        with socket.create_connection((host, port), timeout=NEGOTIATION_TIMEOUT) as s:
            notif = {
                "type": "notify_worker_returned",
                "request_id": gerar_request_id(),
                "payload": {"worker_id": worker_id}
            }
            s.sendall((json.dumps(notif) + DELIMITER).encode())
            logger.info(f"[P2P][SEND] type=notify_worker_returned | request_id={notif['request_id']} | Enviado com sucesso para {worker_id}")
    except Exception as e:
        logger.error(f"[P2P] Falha ao enviar notify_worker_returned para {original_master_address}: {e}")


def solicitar_ajuda_vizinhos(workers_needed):
    for neighbor in NEIGHBORS:
        if workers_needed <= 0:
            break
        try:
            logger.info(f"[P2P] Tentando conectar ao Master Vizinho {neighbor['id']} ({neighbor['host']}:{neighbor['port']})...")
            with socket.create_connection((neighbor["host"], neighbor["port"]), timeout=NEGOTIATION_TIMEOUT) as s:
                pedido = {
                    "type": "request_help",
                    "request_id": gerar_request_id(),
                    "payload": {
                        "master_id": SERVER_UUID,
                        "current_load": len(FILA_TAREFAS),
                        "capacity": CAPACITY,
                        "workers_needed": workers_needed
                    }
                }
                s.sendall((json.dumps(pedido) + DELIMITER).encode())
                logger.info(f"[P2P][SEND] type=request_help | request_id={pedido['request_id']} | Para {neighbor['id']}")

                # Receive response
                data = ""
                while DELIMITER not in data:
                    chunk = s.recv(1024).decode()
                    if not chunk:
                        break
                    data += chunk

                if data:
                    resposta = parse_mensagem(data.split(DELIMITER)[0])
                    if resposta and resposta.get("type") == "response_accepted":
                        offered = resposta["payload"].get("workers_offered", 0)
                        details = resposta["payload"].get("worker_details", [])
                        logger.info(f"[P2P][RECV] type=response_accepted | request_id={resposta.get('request_id')} | Ofereceu {offered} workers. Detalhes: {details}")
                        with _lock:
                            for worker in details:
                                wid = worker["id"]
                                BORROWED_WORKERS[wid] = f"{neighbor['host']}:{neighbor['port']}"
                            log_estado_workers()
                        workers_needed -= offered
                    elif resposta and resposta.get("type") == "response_rejected":
                        logger.info(f"[P2P][RECV] type=response_rejected | request_id={resposta.get('request_id')} | Vizinho recusou. Motivo: {resposta.get('payload', {}).get('reason')}")
        except Exception as e:
            logger.error(f"[P2P] Falha ao contatar vizinho {neighbor['id']}: Timeout/Offline")


def monitor_carga():
    while True:
        time.sleep(LOAD_CHECK_INTERVAL)

        with _lock:
            stale = [wid for wid in PENDING_WORKER_COMMANDS if wid not in WORKERS_ATIVOS]
            for wid in stale:
                logger.warning(f"[Master] Limpando comando pendente para Worker inativo: {wid}")
                PENDING_WORKER_COMMANDS.pop(wid)

        with fila_lock:
            carga = len(FILA_TAREFAS)

        if carga > SATURATION_THRESHOLD:
            logger.info(f"[ALERTA] Saturação Crítica ({carga} tarefas)!")
            with _lock:
                with fila_lock:
                    workers_needed = len(FILA_TAREFAS) - SATURATION_THRESHOLD
            if workers_needed > 0:
                solicitar_ajuda_vizinhos(workers_needed)

        elif carga < RELEASE_THRESHOLD:
            with _lock:
                borrowed_list = list(BORROWED_WORKERS.items())

            if borrowed_list:
                logger.info(f"[P2P] Carga normalizada ({carga} tarefas). Devolvendo workers...")
                for wid, original_master in borrowed_list:
                    logger.info(
                        f"[LIFECYCLE] Worker {wid}: emprestimo -> registro -> "
                        f"{BORROWED_WORKER_TASKS.get(wid, 0)} tarefas executadas -> devolucao"
                    )
                    BORROWED_WORKER_TASKS.pop(wid, None)
                    with _lock:
                        # Queue command_release for worker
                        req_id_rel = gerar_request_id()
                        PENDING_WORKER_COMMANDS[wid] = {
                            "type": "command_release",
                            "request_id": req_id_rel,
                            "payload": {"original_master_address": original_master}
                        }
                        logger.info(f"[P2P][SEND] type=command_release | request_id={req_id_rel} | Enfileirado para Worker {wid}")
                        BORROWED_WORKERS.pop(wid, None)
                        log_estado_workers()
                    # Notify lender
                    enviar_notify_worker_returned(original_master, wid)


def gerador_tarefas():
    if os.environ.get("P2P_DISABLE_GENERATOR") == "true":
        logger.info("[Gerador] Desabilitado via variável de ambiente.")
        return
    tarefas_exemplos = [
        "Compilar_Kernel", "Processar_Pagamentos", "Otimizar_Rotas",
        "Analisar_Vulnerabilidades", "Treinar_Rede_Neural", "Sincronizar_Bancos"
    ]
    # Wait initially before injecting tasks
    time.sleep(5)
    while True:
        time.sleep(8)
        with _lock:
            with fila_lock:
                # Only generate tasks if we are below saturation to avoid infinite task accumulation
                if len(FILA_TAREFAS) < 15:
                    novas = [random.choice(tarefas_exemplos) for _ in range(random.randint(1, 3))]
                    FILA_TAREFAS.extend(novas)
                    logger.info(f"[Gerador] Injetadas {len(novas)} novas tarefas. Fila total: {len(FILA_TAREFAS)}")


# =====================================================================
# SPRINT 4 — Snapshot do estado da farm para o monitor
# =====================================================================
def get_farm_snapshot():
    """Retorna snapshot do estado atual da farm para envio ao supervisor."""
    with _lock:
        total_registered = len(WORKERS_ATIVOS)
        borrowed_out = len(LENT_WORKERS)
        borrowed_in = len(BORROWED_WORKERS)
        workers_alive = total_registered

        # Lista de workers emprestados (entrada e saída)
        borrowed_workers_list = []
        for wid, peer in LENT_WORKERS.items():
            borrowed_workers_list.append({"direction": "out", "peer_uuid": peer})
        for wid, peer in BORROWED_WORKERS.items():
            borrowed_workers_list.append({"direction": "in", "peer_uuid": peer})

        # Estado dos vizinhos
        neighbors_list = []
        for n in NEIGHBORS:
            neighbors_list.append({
                "server_uuid": n["id"],
                "status": "available",
                "last_heartbeat": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    with fila_lock:
        tasks_pending = len(FILA_TAREFAS)

    with _monitor_lock:
        tasks_completed = _tasks_completed
        tasks_failed = _tasks_failed
        tasks_running = len(_task_dispatch_times)
        workers_utilization = tasks_running

        # Idade da tarefa mais antiga em execução
        if _task_dispatch_times:
            oldest = min(_task_dispatch_times.values())
            oldest_task_age_s = int(time.time() - oldest)
        else:
            oldest_task_age_s = 0

    workers_idle = max(0, workers_alive - workers_utilization)
    workers_home = max(0, total_registered - borrowed_in)

    return {
        "farm_state": {
            "workers": {
                "total_registered": total_registered,
                "workers_utilization": workers_utilization,
                "workers_alive": workers_alive,
                "workers_idle": workers_idle,
                "workers_borrowed": borrowed_out,
                "workers_received": borrowed_in,
                "workers_failed": 0,
                "workers_home": workers_home,
                "workers_available_capacity": max(0, CAPACITY - tasks_pending),
                "borrowed_workers": borrowed_workers_list,
            },
            "tasks": {
                "tasks_pending": tasks_pending,
                "tasks_running": tasks_running,
                "tasks_completed": tasks_completed,
                "tasks_failed": tasks_failed,
                "oldest_task_age_s": oldest_task_age_s,
            },
        },
        "config_thresholds": {
            "max_task": SATURATION_THRESHOLD,
            "warn_cpu_percent": 85,
            "warn_memory_percent": 85,
            "release_task": RELEASE_THRESHOLD,
        },
        "neighbors": neighbors_list,
    }


def start_master():
    threading.Thread(target=monitor_carga, daemon=True).start()
    threading.Thread(target=gerador_tarefas, daemon=True).start()
    # Sprint 4: iniciar monitoramento para o supervisor
    start_monitor(SERVER_UUID, get_farm_snapshot)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', PORT))
        s.listen()
        
        s.settimeout(1.0) 
        
        logger.info(f"=== Master Server na porta {PORT} (Limite: {SATURATION_THRESHOLD}) ===")
        logger.info(f"[Master] OK - ONLINE | Aguardando conexões em 0.0.0.0:{PORT}")
        logger.info(f"[Master] Pressione Ctrl+C para encerrar.")
        try:
            while True:
                try:
                    conn, addr = s.accept()
                    threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    # Ignora o timeout e volta para o loop, permitindo checar o KeyboardInterrupt
                    pass
        except KeyboardInterrupt:
            logger.info(f"[Master] Encerrando servidor...")
            logger.info(f"[Master] OFFLINE.")
            os._exit(0)  # Força a saída


if __name__ == "__main__":
    start_master()