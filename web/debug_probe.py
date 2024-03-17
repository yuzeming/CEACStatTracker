from http.server import SimpleHTTPRequestHandler
import socketserver
import json
import datetime
import base64
import os
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

private_key = serialization.load_pem_private_key(
    os.environ["PRIVATE_KEY"].encode(),
    password=None,
)

def decrypt(ciphertext):
    #decrypt addition_info by RSA
    try:
        plaintext = private_key.decrypt(
            base64.b64decode(ciphertext),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        passport_number, surname = plaintext.decode().split(",")
        return passport_number, surname
    except Exception as e:
        return None, None

class DebugProbe(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Hello, world!')

    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        content_len = int(self.headers.get('Content-Length'))
        post_body = self.rfile.read(content_len)

        req = json.loads(post_body)
        ret = {}

        for loc, case_no, info in req:
            passport_number, surname = decrypt(info)
            ret[case_no] = (
                "DEBUG_INFO_"+str(datetime.datetime.now()) ,
                datetime.datetime.strftime(datetime.date(2024,1,1),"%d-%b-%Y"),
                datetime.datetime.strftime(datetime.date.today(),"%d-%b-%Y"),
                "DEBUG_%s_%s_%s_%s" %(loc,case_no,passport_number,surname)
            )
        
        self.wfile.write(json.dumps(ret).encode())


def main():
    PORT = 8000
    with socketserver.TCPServer(("", PORT), DebugProbe) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()

if __name__ == "__main__":
    main()