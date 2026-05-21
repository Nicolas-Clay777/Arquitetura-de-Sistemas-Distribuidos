import socket
import time
import json
import random
import uuid
import logging

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

HOST = '127.0.0.1'
PORT = 5000
WORKER_UUID = "W-123" 
SERVER_UUID = "Master_7"
ORIGINAL_SERVER_UUID = SERVER_UUID

CYCLE_INTERVAL = 5 

def start_worker():
    global HOST, PORT, SERVER_UUID
    backoff = 5
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0) 
                s.connect((HOST, PORT))
                buffer = ""
                print(f"[LIGADO] Worker {WORKER_UUID} conectado ao Master.")
                # Reset backoff after successful connection
                backoff = 5
                try:
                    if SERVER_UUID != ORIGINAL_SERVER_UUID:
                        reg = {"type": "register_temporary_worker", "request_id": str(uuid.uuid4()), "payload": {"WORKER_UUID": WORKER_UUID, "SERVER_UUID": SERVER_UUID, "ORIGINAL_SERVER_UUID": ORIGINAL_SERVER_UUID}}
                        s.sendall((json.dumps(reg) + "\n").encode('utf-8'))
                        logging.info(f"Sent register_temporary_worker for {WORKER_UUID} to {SERVER_UUID}")
                except Exception:
                    pass
                
                while True:
                    payload = {
                        "WORKER": "ALIVE",
                        "WORKER_UUID": WORKER_UUID,
                        "SERVER_UUID": SERVER_UUID
                    }
                    s.sendall((json.dumps(payload) + "\n").encode('utf-8'))
                    
                    def read_json_line():
                        nonlocal buffer
                        while '\n' not in buffer:
                            data = s.recv(1024).decode('utf-8')
                            if not data:
                                raise ConnectionResetError
                            buffer += data
                        line, buffer = buffer.split('\n', 1)
                        return json.loads(line)

                    resp = read_json_line()
                    
                    if 'type' in resp:
                        mtype = resp.get('type','').lower()
                        if mtype == 'command_redirect':
                            payload = resp.get('payload',{}) or {}
                            target_host = payload.get('reconnect_host', HOST)
                            target_port = payload.get('reconnect_port', PORT)
                            target_server_uuid = payload.get('target_server_uuid')
                            print(f"[REDIRECT] Recebido command_redirect para {target_host}:{target_port}")
                            if target_server_uuid:
                                SERVER_UUID = target_server_uuid
                            raise ConnectionResetError
                        elif mtype == 'command_release':
                            payload = resp.get('payload',{}) or {}
                            return_host = payload.get('return_host', None)
                            return_port = payload.get('return_port', None)
                            print(f"[RELEASE] Recebido command_release. Retornando ao lender {return_host}:{return_port}")
                            if return_host and return_port:
                                HOST = return_host
                                PORT = return_port
                            SERVER_UUID = ORIGINAL_SERVER_UUID
                            raise ConnectionResetError

                    if resp.get("TASK") == "QUERY":
                        user = resp.get("USER", "Desconhecido")
                        print(f"[TRABALHANDO] A processar QUERY para o USER: '{user}'...")
                        
                        time.sleep(random.uniform(1.0, 3.0)) 
                        
                        status_payload = {
                            "STATUS": "OK",
                            "TASK": "QUERY",
                            "WORKER_UUID": WORKER_UUID
                        }
                        s.sendall((json.dumps(status_payload) + "\n").encode('utf-8'))
                        print("[STATUS] Tarefa concluída. OK enviado.")
                        
                        ack_resp = read_json_line()
                        if ack_resp.get("STATUS") == "ACK":
                            print("[ACK RECEBIDO] Ciclo finalizado com sucesso.\n")
                            
                    elif resp.get("TASK") == "NO_TASK":
                        print("[FILA VAZIA] Nenhuma tarefa a ser processada de momento.\n")
                                
                    time.sleep(CYCLE_INTERVAL)
                    
        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError, OSError) as e:
            logging.info(f"Status: OFFLINE - Erro de rede: {e}")
            try:
                backoff = min(backoff * 2, 60)
            except Exception:
                backoff = 5
            print(f"Status: OFFLINE - A tentar reconectar em {backoff}s...")
            time.sleep(backoff)
        except socket.timeout:
            print("Status: TIMEOUT - O Master demorou mais de 5s a responder. A reiniciar ciclo...")
            time.sleep(5)

if __name__ == "__main__":
    start_worker()