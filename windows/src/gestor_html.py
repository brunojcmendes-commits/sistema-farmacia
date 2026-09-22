import os, sys, threading, http.server, socketserver, webbrowser
VERSAO_APP="1.4.0"
def base_dir():
    if getattr(sys,"frozen",False): return getattr(sys,"_MEIPASS",os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
WEB=os.path.join(base_dir(),"web")
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**k): super().__init__(*a,directory=WEB,**k)
    def log_message(self,*a): pass
def main():
    with socketserver.TCPServer(("127.0.0.1",0),Handler) as srv:
        port=srv.server_address[1]
        threading.Timer(.6,lambda:webbrowser.open(f"http://127.0.0.1:{port}/index.html")).start()
        srv.serve_forever()
if __name__=="__main__": main()
