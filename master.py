import socket
import threading
import json
import queue

HOST = '127.0.0.1'
PORT = 5000
SERVER_UUID = "Master_7"

# Fila de tarefas (Queue) gerida pelo Master
task_queue = queue.Queue()

# Adicionamos algumas tarefas simuladas (Cenários de Teste CT01 e CT02)
task_queue.put({"TASK": "QUERY", "USER": "Rafael"})
task_queue.put({"TASK": "QUERY", "USER": "Nicolas"})

def handle_worker(conn, addr):
    print(f"[NOVA LIGAÇÃO] Worker conectado de {addr}")
    buffer = ""
    
    with conn:
        while True:
            try:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break 
                
                buffer += data
                
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        process_message(line, conn)
                        
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                break
                
    print(f"[DESCONECTADO] Worker {addr} desconectou-se.")

def process_message(message_str, conn):
    try:
        msg = json.loads(message_str)
        
        # 1. Fluxo de Apresentação e Pedido de Tarefa
        if msg.get("WORKER") == "ALIVE":
            worker_uuid = msg.get("WORKER_UUID", "Desconhecido")
            server_uuid = msg.get("SERVER_UUID")
            print(f"[PEDIDO] Worker {worker_uuid} pediu trabalho.")
            
            if server_uuid and server_uuid != SERVER_UUID:
                print(f"[PEDIDO EMPRESTADO] Worker {worker_uuid} (pertence ao {server_uuid}) pediu trabalho.")
            else:
                print(f"[PEDIDO LOCAL] Worker {worker_uuid} pediu trabalho.")
            
            # Verifica se há tarefas na fila
            if not task_queue.empty():
                task = task_queue.get()
                resp_str = json.dumps(task) + "\n"
                conn.sendall(resp_str.encode('utf-8'))
                print(f"[TAREFA] Enviada {task} para {worker_uuid}")
            else:
                # Fila Vazia (Payload 2.3)
                response = {"TASK": "NO_TASK"}
                resp_str = json.dumps(response) + "\n"
                conn.sendall(resp_str.encode('utf-8'))
                print(f"[FILA VAZIA] NO_TASK enviado para {worker_uuid}")
                
        # 2. Fluxo de Reporte de Status (OK / NOK)
        elif "STATUS" in msg and msg.get("STATUS") in ["OK", "NOK"]:
            worker_uuid = msg.get("WORKER_UUID", "Desconhecido")
            status = msg.get("STATUS")
            task_type = msg.get("TASK")
            print(f"[RESULTADO] Worker {worker_uuid} concluiu a tarefa {task_type} com Status: {status}")
            
            # 3. Confirmação Final (ACK)
            ack_response = {
                "STATUS": "ACK",
                "WORKER_UUID": worker_uuid
            }
            ack_str = json.dumps(ack_response) + "\n"
            conn.sendall(ack_str.encode('utf-8'))
            print(f"[ACK] Confirmação enviada para {worker_uuid}\n")
            
    except json.JSONDecodeError:
        print("[ERRO] Falha ao descodificar JSON.")

def start_master():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[MASTER INICIADO] À escuta na porta {PORT}...")
    print(f"Fila inicial tem {task_queue.qsize()} tarefas.")
    print(f"{'-'*40}")
    
    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=handle_worker, args=(conn, addr))
        thread.start()

if __name__ == "__main__":
    start_master()