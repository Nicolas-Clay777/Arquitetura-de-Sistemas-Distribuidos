#!/usr/bin/env python3
"""
=======================================================================
  WORKER NODE — Sistema P2P com Balanceamento de Carga Dinâmico
  Arquivo consolidado (worker)
  Sprints 01, 02 e 03
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

# =====================================================================
# CONFIGURAÇÕES 
# =====================================================================
MEU_IP_NA_REDE = '10.62.217.11'
MINHA_PORTA = 5000

HOST = os.environ.get("P2P_HOST", MEU_IP_NA_REDE)
PORT = int(os.environ.get("P2P_PORT", MINHA_PORTA))
DELIMITER = '\n'
HEARTBEAT_INTERVAL = int(os.environ.get("P2P_HEARTBEAT_INTERVAL", 5))

SERVER_UUID = os.environ.get("P2P_SERVER_UUID", "Master_Local")
WORKER_UUID = os.environ.get("P2P_WORKER_UUID", "Worker_Local")

# Logging com timestamps
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("p2p")

# =====================================================================
# WORKER — LÓGICA PRINCIPAL
# =====================================================================

current_master_addr = (HOST, PORT)


def heartbeat_loop():
    """Thread separada que envia HEARTBEAT periodicamente para o Master atual."""
    global current_master_addr
    while True:
        try:
            host, port = current_master_addr
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((host, port))
                hb = {"SERVER_UUID": SERVER_UUID, "TASK": "HEARTBEAT"}
                s.sendall((json.dumps(hb) + DELIMITER).encode())

                data = ""
                while DELIMITER not in data:
                    chunk = s.recv(1024).decode()
                    if not chunk:
                        break
                    data += chunk

                if data:
                    try:
                        resp = json.loads(data.split(DELIMITER)[0])
                        if resp.get("RESPONSE") == "ALIVE":
                            logger.info(f"[Worker] Heartbeat OK - Master {resp.get('SERVER_UUID')} esta ALIVE")
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.warning(f"[Worker] Heartbeat falhou: {e}")

        time.sleep(HEARTBEAT_INTERVAL)


def start_worker():
    global current_master_addr
    host_atual = HOST
    porta_atual = PORT
    master_original = f"{HOST}:{PORT}"
    is_borrowed = False

    logger.info(f"[Worker] Iniciando Worker {WORKER_UUID}...")
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    logger.info(f"[Worker] Conectando ao Master em {HOST}:{PORT}")
    logger.info(f"[Worker] Pressione Ctrl+C para encerrar.")

    try:
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(5.0)
                    s.connect((host_atual, porta_atual))

                    if is_borrowed:
                        req_temp = {
                            "type": "register_temporary_worker",
                            "request_id": str(uuid.uuid4()),
                            "payload": {"worker_id": WORKER_UUID, "original_master_address": master_original}
                        }
                        s.sendall((json.dumps(req_temp) + DELIMITER).encode())

                    req = {"WORKER": "ALIVE", "WORKER_UUID": WORKER_UUID}
                    if is_borrowed:
                        req["SERVER_UUID"] = master_original

                    s.sendall((json.dumps(req) + DELIMITER).encode())

                    data = ""
                    while DELIMITER not in data:
                        chunk = s.recv(1024).decode()
                        if not chunk:
                            break
                        data += chunk

                    if data:
                        try:
                            resposta = json.loads(data.split(DELIMITER)[0])
                        except json.JSONDecodeError:
                            logger.error("[Worker] Erro ao decodificar resposta JSON do Master. Ignorando.")
                            continue

                        if not isinstance(resposta, dict):
                            logger.error("[Worker] Resposta inválida (não é um dicionário). Ignorando.")
                            continue

                        if resposta.get("type") == "command_redirect":
                            novo_endereco = resposta["payload"]["new_master_address"].split(":")
                            host_atual = novo_endereco[0]
                            porta_atual = int(novo_endereco[1]) if len(novo_endereco) > 1 else PORT
                            current_master_addr = (host_atual, porta_atual)
                            is_borrowed = True
                            logger.info(f"[Worker] Redirecionamento P2P recebido! Migrando para {host_atual}:{porta_atual}...")
                            continue

                        elif resposta.get("type") == "command_release":
                            host_atual = HOST
                            porta_atual = PORT
                            current_master_addr = (host_atual, porta_atual)
                            is_borrowed = False
                            logger.info("[Worker] Fim do empréstimo. Retornando ao Master original.")
                            continue

                        if resposta.get("TASK") == "QUERY":
                            logger.info(f"[Worker] Processando tarefa: {resposta.get('USER')}...")
                            time.sleep(random.randint(1, 3))
                            # Simular falha aleatoria (~10% chance)
                            status = "NOK" if random.random() < 0.1 else "OK"
                            ack_req = {"STATUS": status, "TASK": "QUERY", "WORKER_UUID": WORKER_UUID}
                            s.sendall((json.dumps(ack_req) + DELIMITER).encode())
                            logger.info(f"[Worker] Tarefa concluida com status: {status}")

                            # Wait for ACK response from Master
                            ack_data = ""
                            while DELIMITER not in ack_data:
                                chunk = s.recv(1024).decode()
                                if not chunk:
                                    break
                                ack_data += chunk
                        elif resposta.get("TASK") == "NO_TASK":
                            time.sleep(HEARTBEAT_INTERVAL)

            except (socket.timeout, ConnectionRefusedError, ConnectionResetError, OSError) as e:
                logger.warning(f"[Worker] Erro de conexao ({e}).")
                if is_borrowed:
                    logger.info(
                        f"[Worker] Master emprestador ({host_atual}:{porta_atual}) caiu! "
                        f"Retornando ao Master original ({HOST}:{PORT})..."
                    )
                    host_atual = HOST
                    porta_atual = PORT
                    current_master_addr = (host_atual, porta_atual)
                    is_borrowed = False
                    time.sleep(2)
                else:
                    logger.info(f"[Worker] Aguardando reconexao em 5s...")
                    time.sleep(5)

    except KeyboardInterrupt:
        logger.info(f"[Worker] Encerrando Worker {WORKER_UUID}...")
        logger.info(f"[Worker] OFFLINE.")
        os._exit(0)  # Força a saída


if __name__ == "__main__":
    start_worker()