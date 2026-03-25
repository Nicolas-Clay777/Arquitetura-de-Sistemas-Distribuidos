import socket
import threading
import json

HOST = '127.0.0.1'
PORT = 5000
SERVER_UUID = "Master_A"

def handle_worker(conn, addr):
    print(f"Worker conectado de {addr}")
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
                        
            except ConnectionResetError:
                break
                
    print(f"[DESCONECTADO] Worker {addr} desconectou.")

def process_message(message_str, conn):
    try:
        msg = json.loads(message_str)
        
        if msg.get("TASK") == "HEARTBEAT":
            response = {
                "SERVER_UUID": SERVER_UUID,
                "TASK": "HEARTBEAT",
                "RESPONSE": "ALIVE"
            }
            resp_str = json.dumps(response) + "\n"
            
            conn.sendall(resp_str.encode('utf-8'))
            print(f"HEARTBEAT Recebido e respondido (ALIVE).")
            
    except json.JSONDecodeError:
        print("[ERRO] Falha ao decodificar JSON.")

