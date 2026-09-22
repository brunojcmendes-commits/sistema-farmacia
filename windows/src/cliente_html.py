import os,sys,threading,http.server,socketserver,webbrowser
def root():
    if getattr(sys,"frozen",False): return getattr(sys,"_MEIPASS",os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
WEB=os.path.join(root(),"web-cliente")
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**k): super().__init__(*a,directory=WEB,**k)
    def log_message(self,*a): pass
def main():
    with socketserver.TCPServer(("127.0.0.1",0),H) as s:
        p=s.server_address[1]
        threading.Timer(.5,lambda:webbrowser.open(f"http://127.0.0.1:{p}/index.html")).start()
        s.serve_forever()
if __name__=="__main__": main()
