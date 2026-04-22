import socket
import time
import json

HOST = '127.0.0.1'
PORT = 5000
SERVER_UUID = "Master_7"

HEARTBEAT_INTERVAL = 30 

def start_worker():
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                buffer = ""
                
                while True:
                    payload = {
                        "SERVER_UUID": SERVER_UUID,
                        "TASK": "HEARTBEAT"
                    }
                    msg_str = json.dumps(payload) + "\n"
                    s.sendall(msg_str.encode('utf-8'))
                    
                    data = s.recv(1024).decode('utf-8')
                    if not data:
                        raise ConnectionResetError 
                        
                    buffer += data
                    
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line.strip():
                            resp = json.loads(line)
                            if resp.get("RESPONSE") == "ALIVE":
                                print("Status: ALIVE")
                                
                    time.sleep(HEARTBEAT_INTERVAL)
                    
        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError):
            print("Status: OFFLINE - Tentando Reconectar")
            time.sleep(10)

if __name__ == "__main__":
    start_worker()