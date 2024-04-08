from typing import Dict, List
import requests
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pprint import pprint
import logging
import onnxruntime as ort
import numpy as np
from PIL import Image
import string
from io import BytesIO
import logging
import json
import base64
import time
import datetime
logger = logging.getLogger()

characters = '-' + string.digits + string.ascii_uppercase
width, height, n_len, n_classes = 200, 50, 6, len(characters)

def decode(sequence):
    a = ''.join([characters[x] for x in sequence])
    s = ''.join([x for j, x in enumerate(a[:-1]) if x != characters[0] and x != a[j+1]])
    if len(s) == 0:
        return ''
    if a[-1] != characters[0] and s[-1] != a[-1]:
        s += a[-1]
    return s

captcha_onnx = os.path.join(os.path.dirname(os.path.realpath(__file__)), "captcha.onnx")
ORT_SESS = ort.InferenceSession(captcha_onnx, providers=['CPUExecutionProvider'])

def pred(img_content):
    img = np.asarray( Image.open(BytesIO(img_content)) ,dtype=np.float32) / 255.0
    img = np.expand_dims(np.transpose(img,(2,0,1)), axis=0)
    outputs = ORT_SESS.run(None, {'input': img})
    x = outputs[0]
    t = np.argmax( np.transpose(x,(1,0,2)), -1)
    pred = decode(t[0])
    return pred

ERR_CAPTCHA = "The code entered does not match the code displayed on the page."

URL = "https://ceac.state.gov/CEACStatTracker/Status.aspx?App=NIV"

s = requests.Session()
s.headers["User-Agent"]="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
s.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
s.headers["Accept-Encoding"] = "gzip, deflate, br, zstd"
s.headers["Accept-Language"] = "en-US,en;q=0.9"
s.headers["sec-ch-ua"]= '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"'
s.headers["sec-ch-ua-mobile"] = "?0"
s.headers["sec-ch-ua-platform"] = "Windows"
s.headers["Sec-Fetch-Dest"] = "document"
s.headers["Sec-Fetch-Mode"] = "navigate"
s.headers["Sec-Fetch-Site"] = "none"
s.headers["Sec-Fetch-User"] = "?1"
s.headers["Upgrade-Insecure-Requests"] = "1"


def read_hidden_input(soup: BeautifulSoup):
    ret = {}
    input_list = soup.find_all("input", attrs={ "type":"hidden"})
    for x in input_list:
        ret[x.attrs["name"]] = x.attrs["value"]
    return ret

def get_post_data(soup=None):
    if soup is None:
        html = s.get(URL, timeout=10).text
        soup = BeautifulSoup(html, features="html.parser")
    data = read_hidden_input(soup)
    CaptchaImageUrl = soup.find(id="c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage").attrs["src"]
    img_resp = s.get(urljoin(URL,CaptchaImageUrl), timeout=10)
    data["ctl00$ContentPlaceHolder1$Captcha"]=pred(img_resp.content)
    data["ctl00_ToolkitScriptManager1_HiddenField"]=";;AjaxControlToolkit, Version=3.5.51116.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:en-US:2a06c7e2-728e-4b15-83d6-9b269fb7261e:de1feab2:f2c8e708:8613aea7:f9cec9bc:3202a5a2:a67c2700:720a52bf:589eaa30:ab09e3fe:87104b7c:be6fb298"
    data["ctl00$ContentPlaceHolder1$Visa_Application_Type"]="NIV"
    data["__EVENTTARGET"]="ctl00$ContentPlaceHolder1$btnSubmit"
    data["ctl00$ToolkitScriptManager1"]="ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$btnSubmit"
    data["LBD_BackWorkaround_c_status_ctl00_contentplaceholder1_defaultcaptcha"]="1"
    data["__EVENTARGUMENT"]=""
    data["__LASTFOCUS"]=""
    return data

def query_ceac_state(loc, case_no, passport_number, surname, data=None):
    if data is None:
        data = get_post_data()
    data["ctl00$ContentPlaceHolder1$Location_Dropdown"]=loc
    data["ctl00$ContentPlaceHolder1$Visa_Case_Number"]=case_no
    data["ctl00$ContentPlaceHolder1$Passport_Number"] = passport_number
    data["ctl00$ContentPlaceHolder1$Surname"] = surname

    resp = s.post(URL,data, timeout=10)
    soup = BeautifulSoup(resp.text, features="html.parser")

    error_tag = soup.find(id="ctl00_ContentPlaceHolder1_ValidationSummary1")
    if error_tag is None:
        # Request Rejected
        # Second captcha and just retry
        return ERR_CAPTCHA, None

    error_text = error_tag.text.strip()
    if error_text:
        return error_text, None

    error_text = soup.find(id="ctl00_ContentPlaceHolder1_lblError").text
    if error_text:
        return error_text, None
    status = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatus").text
    caseno = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblCaseNo").text
    SubmitDate = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblSubmitDate").text
    StatusDate = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatusDate").text
    Message = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblMessage").text
    assert caseno == case_no    
    return (status,SubmitDate,StatusDate,Message), soup


def query_ceac_state_safe(loc, case_no, passport_number, surname, soup=None):
    if case_no == "TEST":
        return (
                "DEBUG_INFO_"+str(datetime.datetime.now()) ,
                datetime.datetime.strftime(datetime.date(2024,1,1),"%d-%b-%Y"),
                datetime.datetime.strftime(datetime.date.today(),"%d-%b-%Y"),
                "DEBUG_%s_%s_%s_%s" %(loc,case_no,passport_number,surname)
        ), soup
    for _ in range(5):
        try:
            data = get_post_data(soup)
            result, soup = query_ceac_state(loc, case_no, passport_number, surname, data)
            logger.info("Info!,%s-%s: %s",loc, case_no, result)
        except Exception as e:
            logger.error("Error!,%s-%s:",loc, case_no, exc_info=e, stack_info=True) 
            return str(e), None
        if result != ERR_CAPTCHA:
            break
        else:
            time.sleep(1)
    return result, soup


def main_handler(req):
    logger.info("my ip is %s", s.get("http://httpbin.org/anything").text)
    ret = {}
    soup = None
    for loc, case_no, passport_number, surname in req:
        result, soup = query_ceac_state_safe(loc, case_no, passport_number, surname, soup)
        ret[case_no] = result
    return json.dumps(ret)


from http.server import HTTPServer, BaseHTTPRequestHandler

class RequestProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        playload_raw = self.rfile.read(int(self.headers["Content-Length"]))
        event = json.loads(playload_raw)
        ret = main_handler(event)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write( ret.encode() )
        self.wfile.flush()
        
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Hello, world")
        self.wfile.flush()


def run(server_class=HTTPServer, handler_class=RequestProxyHandler):
    server_address = ('', 9000)
    httpd = server_class(server_address, handler_class)
    httpd.serve_forever()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()