import socket
import time
import json
import random

HOST = '127.0.0.1'
PORT = 5000
WORKER_UUID = "W-123" # Identificador único deste Worker
SERVER_UUID = "Master_7"

CYCLE_INTERVAL = 5 

def start_worker():
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # Regra estrita: Timeout de 5 segundos
                s.settimeout(5.0) 
                s.connect((HOST, PORT))
                buffer = ""
                print(f"[LIGADO] Worker {WORKER_UUID} conectado ao Master.")
                
                while True:
                    # 1. Apresentação (Pedido de Tarefa)
                    payload = {
                        "WORKER": "ALIVE",
                        "WORKER_UUID": WORKER_UUID,
                        "SERVER_UUID": SERVER_UUID
                    }
                    s.sendall((json.dumps(payload) + "\n").encode('utf-8'))
                    
                    # Função auxiliar para garantir a leitura do buffer até ao delimitador \n
                    def read_json_line():
                        nonlocal buffer
                        while '\n' not in buffer:
                            data = s.recv(1024).decode('utf-8')
                            if not data:
                                raise ConnectionResetError
                            buffer += data
                        line, buffer = buffer.split('\n', 1)
                        return json.loads(line)

                    # 2. Lê a resposta do Master (A Tarefa)
                    resp = read_json_line()
                    
                    if resp.get("TASK") == "QUERY":
                        user = resp.get("USER", "Desconhecido")
                        print(f"[TRABALHANDO] A processar QUERY para o USER: '{user}'...")
                        
                        # Simula o processamento do Worker (calculo complexo/demorado)
                        time.sleep(random.uniform(1.0, 3.0)) 
                        
                        # 3. Reporte de Status (Sucesso)
                        status_payload = {
                            "STATUS": "OK",
                            "TASK": "QUERY",
                            "WORKER_UUID": WORKER_UUID
                        }
                        s.sendall((json.dumps(status_payload) + "\n").encode('utf-8'))
                        print("[STATUS] Tarefa concluída. OK enviado.")
                        
                        # 4. Aguarda a Confirmação Final (ACK)
                        ack_resp = read_json_line()
                        if ack_resp.get("STATUS") == "ACK":
                            print("[ACK RECEBIDO] Ciclo finalizado com sucesso.\n")
                            
                    elif resp.get("TASK") == "NO_TASK":
                        print("[FILA VAZIA] Nenhuma tarefa a ser processada de momento.\n")
                                
                    time.sleep(CYCLE_INTERVAL)
                    
        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError):
            print("Status: OFFLINE - A tentar reconectar...")
            time.sleep(5)
        except socket.timeout:
            print("Status: TIMEOUT - O Master demorou mais de 5s a responder. A reiniciar ciclo...")
            time.sleep(5)

if __name__ == "__main__":
    start_worker()