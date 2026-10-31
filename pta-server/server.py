#!/usr/bin/env python3
"""
Servidor do PTA (Protocolo de Transferência de Arquivos).
"""

import os
import socket
import sys
import threading
from datetime import datetime

HOST = ""            
DEFAULT_PORT = 11550
BUFFER_SIZE = 4096


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.txt")
FILES_DIR = os.path.join(BASE_DIR, "files")


def log(addr, msg):
    print(f"[{datetime.now():%H:%M:%S}] {addr[0]}:{addr[1]} {msg}", flush=True)


def load_users():
    """Lê a lista de usuários válidos (um por linha). Comparação sensível a maiúsculas."""
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def list_files():
    """Arquivos regulares disponíveis em pta-server/files, em ordem alfabética."""
    return sorted(
        name for name in os.listdir(FILES_DIR)
        if not name.startswith(".") and os.path.isfile(os.path.join(FILES_DIR, name))
    )


def parse_request(raw):
    """
    Interpreta 'SEQ COMANDO [ARGS...]'.
    Retorna (seq, comando, args, valido). Se o formato for inválido, valido=False,
    mas seq é preenchido quando possível para que o NOK possa ecoá-lo.
    """
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return "0", None, [], False

    parts = text.split()
    if not parts:
        return "0", None, [], False

    seq = parts[0]
    if len(parts) < 2 or not seq.isdigit():
        return seq, None, [], False

    return seq, parts[1], parts[2:], True


def send_reply(conn, addr, seq, reply, payload=b""):
    """Envia 'SEQ REPLY' (+ payload binário opcional) de uma só vez com sendall."""
    header = f"{seq} {reply}"
    conn.sendall(header.encode("ascii") + payload)
    log(addr, f"-> {header}" + (f" (+{len(payload)} bytes)" if payload else ""))


def close_gracefully(conn):
    """
    Encerra a conexão sem perder a última resposta: envia FIN (shutdown) e
    descarta o que ainda chegar antes de fechar. Fechar com dados não lidos no
    buffer faria o SO mandar RST, e o cliente poderia não receber o NOK/OK.
    """
    try:
        conn.shutdown(socket.SHUT_WR)
        conn.settimeout(1.0)
        while conn.recv(BUFFER_SIZE):
            pass
    except OSError:
        pass
    finally:
        conn.close()


def handle_list(conn, addr, seq):
    try:
        names = list_files()
    except OSError:
        send_reply(conn, addr, seq, "NOK")
        return
   
    send_reply(conn, addr, seq, f"ARQS {len(names)} {','.join(names)}")


def handle_pega(conn, addr, seq, args):
    
    name = args[0]
    try:
        available = list_files()
    except OSError:
        send_reply(conn, addr, seq, "NOK")
        return

    
    if name not in available:
        send_reply(conn, addr, seq, "NOK")
        return

    try:
        with open(os.path.join(FILES_DIR, name), "rb") as f:
            data = f.read()
    except OSError:
        send_reply(conn, addr, seq, "NOK")
        return

    
    send_reply(conn, addr, seq, f"ARQ {len(data)} ", payload=data)


def handle_client(conn, addr):
    conn.settimeout(None)  
    log(addr, "conectou")
    authenticated = False  

    try:
        while True:
            raw = conn.recv(BUFFER_SIZE)
            if not raw:  
                break

            seq, cmd, args, valid = parse_request(raw)
            log(addr, f"<- {raw!r}")

           
            if not authenticated:
                if valid and cmd == "CUMP" and len(args) == 1 and args[0] in load_users():
                    send_reply(conn, addr, seq, "OK")
                    authenticated = True
                    continue
                send_reply(conn, addr, seq, "NOK")
                break  


            if valid and cmd == "LIST" and not args:
                handle_list(conn, addr, seq)
            elif valid and cmd == "PEGA" and args:
                handle_pega(conn, addr, seq, args)
            elif valid and cmd == "TERM" and not args:
                send_reply(conn, addr, seq, "OK")
                break
            else:
                send_reply(conn, addr, seq, "NOK")

    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        log(addr, "conexão interrompida pelo cliente")
    finally:
        close_gracefully(conn)
        log(addr, "desconectou")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, port))
        server.listen()
        server.settimeout(1.0)
        print(f"Servidor PTA ouvindo na porta {port} (Ctrl+C para encerrar)", flush=True)

        try:
            while True:
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            print("\nServidor encerrado.")


if __name__ == "__main__":
    main()