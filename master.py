import socket
import threading
import json
import queue
import uuid
import logging
import time

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

HOST = '127.0.0.1'
PORT = 5000
SERVER_UUID = "Master_7"


task_queue = queue.Queue()


SATURATION_THRESHOLD = 0.8  
RELEASE_THRESHOLD = SATURATION_THRESHOLD * 0.6  
REQUEST_TIMEOUT = 5.0  
NEIGHBORS = [("127.0.0.1", 5001)]  

queue_lock = threading.Lock()
workers_lock = threading.Lock()
borrowed_lock = threading.Lock()


workers_map = {}          
borrowed_registry = {}    

local_workers = 0
borrowed_workers = 0


def log_m2m(request_id, mtype, info=''):
    logging.info(f"M2M {request_id} {mtype} {info}")


def send_request_help(neighbor, request_id, payload):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(REQUEST_TIMEOUT)
        s.connect(neighbor)
        msg = {"type": "request_help", "request_id": request_id, "payload": payload}
        s.sendall((json.dumps(msg) + "\n").encode('utf-8'))
        buffer = ""
        while '\n' not in buffer:
            data = s.recv(1024).decode('utf-8')
            if not data:
                break
            buffer += data
        if not buffer:
            return None
        line, _ = buffer.split('\n', 1)
        return json.loads(line)
    except socket.timeout:
        logging.info(f"request_help to {neighbor} timed out")
        return None
    except (ConnectionRefusedError, ConnectionResetError, OSError) as e:
        logging.info(f"request_help network error to {neighbor}: {e}")
        return None
    except Exception as e:
        logging.info(f"request_help error: {e}")
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass


def try_request_help():
    with queue_lock, workers_lock:
        qsize = task_queue.qsize()
        available_workers = len([w for w in workers_map.keys() if w not in borrowed_registry])
    current_load = qsize / max(1, available_workers)
    if current_load <= SATURATION_THRESHOLD:
        return

    request_id = str(uuid.uuid4())
    payload = {"from": SERVER_UUID, "target_host": HOST, "target_port": PORT, "target_server_uuid": SERVER_UUID}

    for neighbor in NEIGHBORS:
        resp = send_request_help(neighbor, request_id, payload)
        if resp is None:
            continue
        mtype = resp.get('type','').lower()
        log_m2m(request_id, mtype)
        if mtype == 'response_accepted':
            worker_uuid = resp.get('payload', {}).get('worker_uuid')
            logging.info(f"Request {request_id} accepted by {neighbor}, worker {worker_uuid}")
            lender_host, lender_port = neighbor
            with borrowed_lock:
                borrowed_registry[worker_uuid] = {'to': SERVER_UUID, 'host': lender_host, 'port': lender_port}
            break
        else:
            logging.info(f"Request {request_id} rejected by {neighbor}")


def release_borrowed_worker(worker_uuid, lender_info):
    try:
        with workers_lock:
            wconn = workers_map.get(worker_uuid)
        if not wconn:
            return
        
        request_id = str(uuid.uuid4())
        release_msg = {
            "type": "command_release",
            "request_id": request_id,
            "payload": {"return_host": lender_info.get('host', '127.0.0.1'), "return_port": lender_info.get('port', 5000)}
        }
        try:
            wconn.sendall((json.dumps(release_msg) + "\n").encode('utf-8'))
            logging.info(f"M2M {request_id} command_release to {worker_uuid}")
        except Exception as e:
            logging.info(f"Failed to send command_release: {e}")
        
        # Remove from borrowed registry
        with borrowed_lock:
            if worker_uuid in borrowed_registry:
                del borrowed_registry[worker_uuid]
        
        notify_id = str(uuid.uuid4())
        notify_msg = {
            "type": "notify_worker_returned",
            "request_id": notify_id,
            "payload": {"worker_uuid": worker_uuid}
        }
        lender_host = lender_info.get('host')
        lender_port = lender_info.get('port')
        if lender_host and lender_port:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(REQUEST_TIMEOUT)
                s.connect((lender_host, lender_port))
                s.sendall((json.dumps(notify_msg) + "\n").encode('utf-8'))
                s.close()
                logging.info(f"M2M {notify_id} notify_worker_returned sent to {lender_host}:{lender_port}")
            except socket.timeout:
                logging.info(f"Timeout notifying lender {lender_host}:{lender_port}")
            except (ConnectionRefusedError, ConnectionResetError, OSError) as e:
                logging.info(f"Failed to notify lender (network error): {e}")
            except Exception as e:
                logging.info(f"Failed to notify lender: {e}")
    except Exception as e:
        logging.info(f"release_borrowed_worker error: {e}")


def monitor_loop():
    while True:
        try:
            with queue_lock, workers_lock:
                qsize = task_queue.qsize()
                available_workers = [w for w in workers_map.keys() if w not in borrowed_registry]
                local_count = len(available_workers)
            
            current_load = qsize / max(1, local_count)
            
            if current_load > SATURATION_THRESHOLD:
                logging.info(f"Current load {current_load:.2f} > {SATURATION_THRESHOLD}, requesting help")
                try_request_help()
            
            if current_load < RELEASE_THRESHOLD and len(borrowed_registry) > 0:
                logging.info(f"Current load {current_load:.2f} < {RELEASE_THRESHOLD}, releasing borrowed workers")
                with borrowed_lock:
                    to_release = list(borrowed_registry.items())
                for worker_uuid, lender_info in to_release:
                    release_borrowed_worker(worker_uuid, lender_info)
            
            print(f"[CONTADOR] Local workers: {local_count} | Borrowed workers: {len(borrowed_registry)} | Load: {current_load:.2f}")
            time.sleep(2)
        except Exception as e:
            logging.info(f"monitor_loop error: {e}")
            time.sleep(2)


task_queue.put({"TASK": "QUERY", "USER": "Rafael"})
task_queue.put({"TASK": "QUERY", "USER": "Nicolas"})

monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

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
                logging.info(f"Worker {addr} connection closed")
                break
            except OSError as e:
                logging.info(f"Worker {addr} OSError: {e}")
                break
            except Exception as e:
                logging.info(f"Worker {addr} error: {e}")
                break
                
    print(f"[DESCONECTADO] Worker {addr} desconectou-se.")

def process_message(message_str, conn):
    try:
        msg = json.loads(message_str)

        if 'type' in msg:
            mtype = msg.get('type', '').lower()
            request_id = msg.get('request_id', '-')
            payload = msg.get('payload', {}) or {}
            logging.info(f"M2M {request_id} {mtype}")

            if mtype == 'request_help':
                with workers_lock:
                    available_workers = [w for w in workers_map.keys() if w not in borrowed_registry]
                if available_workers:
                    lend_uuid = available_workers[0]
                    lender_addr = conn.getpeername()  
                    with borrowed_lock:
                        borrowed_registry[lend_uuid] = {'to': payload.get('from', 'unknown'), 'host': lender_addr[0] if lender_addr else '127.0.0.1', 'port': lender_addr[1] if lender_addr else PORT}
                    resp = {"type": "response_accepted", "request_id": request_id, "payload": {"worker_uuid": lend_uuid}}
                    conn.sendall((json.dumps(resp) + "\n").encode('utf-8'))
                    logging.info(f"M2M {request_id} response_accepted (lent {lend_uuid})")
                    print(f"[CONTADOR] Local workers: {len([w for w in workers_map.keys() if w not in borrowed_registry])} | Borrowed workers (lending): {len(borrowed_registry)}")
                    with workers_lock:
                        wconn = workers_map.get(lend_uuid)
                    if wconn:
                        target_host = payload.get('target_host', '127.0.0.1')
                        target_port = payload.get('target_port', 5000)
                        redirect = {"type": "command_redirect", "request_id": request_id, "payload": {"reconnect_host": target_host, "reconnect_port": target_port, "target_server_uuid": payload.get('target_server_uuid')}}
                        try:
                            wconn.sendall((json.dumps(redirect) + "\n").encode('utf-8'))
                            logging.info(f"M2M {request_id} command_redirect sent to worker {lend_uuid}")
                        except Exception:
                            logging.info(f"Failed sending command_redirect to worker {lend_uuid}")
                else:
                    resp = {"type": "response_rejected", "request_id": request_id, "payload": {}}
                    conn.sendall((json.dumps(resp) + "\n").encode('utf-8'))
                    logging.info(f"M2M {request_id} response_rejected (no available workers)")
                return

            if mtype == 'register_temporary_worker':
                pdata = payload or {}
                worker_uuid = pdata.get('WORKER_UUID')
                origin = pdata.get('ORIGINAL_SERVER_UUID')
                if worker_uuid:
                    with workers_lock:
                        workers_map[worker_uuid] = conn
                    with borrowed_lock:
                        borrowed_registry[worker_uuid] = origin
                    logging.info(f"M2M {request_id} register_temporary_worker {worker_uuid} from {origin}")
                    print(f"[CONTADOR] Local workers: {len([w for w in workers_map.keys() if w not in borrowed_registry])} | Borrowed workers: {len(borrowed_registry)}")
                return

            if mtype in ('response_accepted', 'response_rejected'):
                logging.info(f"M2M {request_id} received {mtype}")
                return

            if mtype == 'notify_worker_returned':
                worker_uuid = payload.get('worker_uuid')
                if worker_uuid:
                    with borrowed_lock:
                        if worker_uuid in borrowed_registry:
                            del borrowed_registry[worker_uuid]
                    logging.info(f"M2M {request_id} notify_worker_returned {worker_uuid}")
                    print(f"[CONTADOR] Local workers: {len([w for w in workers_map.keys() if w not in borrowed_registry])} | Borrowed workers (lending): {len(borrowed_registry)}")
                return

        if msg.get("WORKER") == "ALIVE":
            worker_uuid = msg.get("WORKER_UUID", "Desconhecido")
            server_uuid = msg.get("SERVER_UUID")

            with workers_lock:
                if worker_uuid not in workers_map:
                    workers_map[worker_uuid] = conn
            if server_uuid and server_uuid != SERVER_UUID:
                print(f"[PEDIDO EMPRESTADO] Worker {worker_uuid} (pertence ao {server_uuid}) pediu trabalho.")
            else:
                print(f"[PEDIDO LOCAL] Worker {worker_uuid} pediu trabalho.")

            with queue_lock:
                if not task_queue.empty():
                    task = task_queue.get()
                else:
                    task = None

            if task:
                resp_str = json.dumps(task) + "\n"
                try:
                    conn.sendall(resp_str.encode('utf-8'))
                    print(f"[TAREFA] Enviada {task} para {worker_uuid}")
                except Exception:
                    print(f"[ERRO] Falha ao enviar tarefa para {worker_uuid}")
            else:
                response = {"TASK": "NO_TASK"}
                resp_str = json.dumps(response) + "\n"
                try:
                    conn.sendall(resp_str.encode('utf-8'))
                    print(f"[FILA VAZIA] NO_TASK enviado para {worker_uuid}")
                except Exception:
                    print(f"[ERRO] Falha ao enviar NO_TASK para {worker_uuid}")

        elif "STATUS" in msg and msg.get("STATUS") in ["OK", "NOK"]:
            worker_uuid = msg.get("WORKER_UUID", "Desconhecido")
            status = msg.get("STATUS")
            task_type = msg.get("TASK")
            print(f"[RESULTADO] Worker {worker_uuid} concluiu a tarefa {task_type} com Status: {status}")

            ack_response = {
                "STATUS": "ACK",
                "WORKER_UUID": worker_uuid
            }
            ack_str = json.dumps(ack_response) + "\n"
            try:
                conn.sendall(ack_str.encode('utf-8'))
                print(f"[ACK] Confirmação enviada para {worker_uuid}\n")
            except Exception:
                print(f"[ERRO] Falha ao enviar ACK para {worker_uuid}")

    except json.JSONDecodeError:
        print("[ERRO] Falha ao descodificar JSON.")

def start_master():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[MASTER INICIADO] À escuta na porta {PORT}...")
    print(f"Fila inicial tem {task_queue.qsize()} tarefas.")
    print(f"{'-'*40}")
    
    while True:
        try:
            conn, addr = server.accept()
            thread = threading.Thread(target=handle_worker, args=(conn, addr))
            thread.start()
        except KeyboardInterrupt:
            logging.info("Master shutting down")
            break
        except OSError as e:
            logging.info(f"Master socket error: {e}. Attempting recovery...")
            time.sleep(2)

if __name__ == "__main__":
    start_master()