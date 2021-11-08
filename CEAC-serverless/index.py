from typing import Dict, List
import requests
import hashlib
import time
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
import time
import json

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


def pred(img_content):
    img = np.asarray( Image.open(BytesIO(img_content)) ,dtype=np.float32) / 255.0
    img = np.expand_dims(np.transpose(img,(2,0,1)), axis=0)
    ort_sess = ort.InferenceSession('captcha.onnx')
    outputs = ort_sess.run(None, {'input': img})
    x = outputs[0]
    t = np.argmax( np.transpose(x,(1,0,2)), -1)
    pred = decode(t[0])
    return pred

ERR_CAPTCHA = "The code entered does not match the code displayed on the page."
ERR_NOCASE = "Your search did not return any data."
ERR_INVCODE = "Invalid Application ID or Case Number."

URL = "https://ceac.state.gov/CEACStatTracker/Status.aspx?App=NIV"

s = requests.Session()
s.headers["User-Agent"]="Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:88.0) Gecko/20100101 Firefox/88.0"


def read_hidden_input(soup: BeautifulSoup):
    ret = {}
    input_list = soup.find_all("input", attrs={ "type":"hidden"})
    for x in input_list:
        ret[x.attrs["name"]] = x.attrs["value"]
    return ret

def get_post_data(soup=None):
    if soup is None:
        html = s.get(URL).text
        soup = BeautifulSoup(html, features="html.parser")
    data = read_hidden_input(soup)
    CaptchaImageUrl = soup.find(id="c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage").attrs["src"]
    img_resp = s.get(urljoin(URL,CaptchaImageUrl))
    data["ctl00$ContentPlaceHolder1$Captcha"]=pred(img_resp.content)
    data["ctl00_ToolkitScriptManager1_HiddenField"]=";;AjaxControlToolkit, Version=3.5.51116.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:en-US:2a06c7e2-728e-4b15-83d6-9b269fb7261e:de1feab2:f2c8e708:8613aea7:f9cec9bc:3202a5a2:a67c2700:720a52bf:589eaa30:ab09e3fe:87104b7c:be6fb298"
    data["ctl00$ContentPlaceHolder1$Visa_Application_Type"]="NIV"
    data["__EVENTTARGET"]="ctl00$ContentPlaceHolder1$btnSubmit"
    data["ctl00$ToolkitScriptManager1"]="ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$btnSubmit"
    data["LBD_BackWorkaround_c_status_ctl00_contentplaceholder1_defaultcaptcha"]="1"
    data["__EVENTARGUMENT"]=""
    data["__LASTFOCUS"]=""
    return data

def query_ceac_state(loc, case_no, data=None):
    if data is None:
        data = get_post_data()
    data["ctl00$ContentPlaceHolder1$Location_Dropdown"]=loc
    data["ctl00$ContentPlaceHolder1$Visa_Case_Number"]=case_no

    resp = s.post(URL,data)
    soup = BeautifulSoup(resp.text, features="html.parser")

    error_text = soup.find(id="ctl00_ContentPlaceHolder1_ValidationSummary1").text.strip()
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


def query_ceac_state_safe(loc, case_no, soup=None):
    for _ in range(5):
        try:
            data = get_post_data(soup)
            result, soup = query_ceac_state(loc, case_no, data)
            logger.info("Info!,%s-%s: %s",loc, case_no, result)
        except Exception as e:
            logger.error("Error!,%s-%s: %s",loc, case_no, e)
            return str(e), None
        if result != ERR_CAPTCHA:
            break
    return result, soup


def main_handler(event, context):
    req = json.loads(event.body)
    ret = {}
    for loc, case_no in req:
        result, soup = query_ceac_state_safe(loc, case_no, soup)
        ret[case_no] = result
    return json.dumps(ret)

if __name__ == "__main__":
    req = [("BEJ","AA00A38G49"), ("SHG","AA00899Z9W"),("SGP","AA009ZAT9R"),("SGP","AA009YRTFV") ]
    soup = None
    for loc, case_no in req:
        result, soup = query_ceac_state_safe(loc, case_no, soup)
        print(result)

