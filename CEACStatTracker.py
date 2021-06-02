from typing import Dict, List
import requests
import hashlib
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pprint import pprint
import json
import logging

l = logging.getLogger(__name__)

DEFAULT_PRED_TYPE = 30600 #6位数字英文

FATEA_PRED_URL  = "http://pred.fateadm.com"
URL = "https://ceac.state.gov/CEACStatTracker/Status.aspx?App=NIV"

PD_ID = "124045"
PD_KEY = "PQWOAWn57Qc7rEyddEV+jWYRQ5yc6lxc"
App_ID = "324045"
App_Key = "7EI9zYymvxlFtiFeR2FkyUb0dWvkEApg"



s = requests.Session()
s.headers["User-Agent"]="Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:88.0) Gecko/20100101 Firefox/88.0"

def CalcSign(timestamp, pd_id, passwd):
    return hashlib.md5((pd_id + timestamp + hashlib.md5((timestamp + passwd).encode()).hexdigest()).encode()).hexdigest()

def Predict(img_data, pd_id=PD_ID, passwd=PD_KEY, pred_type=DEFAULT_PRED_TYPE):
    tm = str( int(time.time()))
    param = {
        "user_id": pd_id,
        "app_id": App_ID,
        "timestamp": tm,
        "sign": CalcSign(tm, pd_id, passwd),
        "asign": CalcSign(tm, App_ID, App_Key),
        "predict_type": pred_type,
        "up_type": "mt"
    }

    url = urljoin(FATEA_PRED_URL, "/api/capreg")
    rsp = s.post(url, data=param,files= {
        'img_data':('img_data.jpg',img_data)
    })
    rsp_json = rsp.json()
    if rsp_json["RetCode"] == '0':
        l.info("predict succ ret: %s request_id: %s pred: %s err: %s", rsp_json["RetCode"], rsp_json["RequestId"], rsp_json["RspData"], rsp_json["ErrMsg"])
    else:
        l.error("predict failed ret: %s err: %s", rsp_json["RetCode"], rsp_json["ErrMsg"])
        if rsp_json["RetCode"] == '4003':
            raise "cust_val <= 0 lack of money, please charge immediately"
    return json.loads(rsp_json["RspData"])["result"]

    # open("cap.jpg","wb").write(img_data)
    # return input("Captcha:")

def read_hidden_input(soup: BeautifulSoup):
    ret = {}
    input_list = soup.find_all("input", attrs={ "type":"hidden"})
    for x in input_list:
        ret[x.attrs["name"]] = x.attrs["value"]
    return ret

def query_ceac_state(loc, case_no, prev_soup = None):
    if prev_soup is None:
        html = s.get(URL).text
        soup = BeautifulSoup(html, features="html.parser")
    else:
        soup = prev_soup

    data = read_hidden_input(soup)
    CaptchaImageUrl = soup.find(id="c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage").attrs["src"]
    img_resp = s.get(urljoin(URL,CaptchaImageUrl))
    data["ctl00_ToolkitScriptManager1_HiddenField"]=";;AjaxControlToolkit, Version=3.5.51116.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:en-US:2a06c7e2-728e-4b15-83d6-9b269fb7261e:de1feab2:f2c8e708:8613aea7:f9cec9bc:3202a5a2:a67c2700:720a52bf:589eaa30:ab09e3fe:87104b7c:be6fb298"
    data["ctl00$ContentPlaceHolder1$Visa_Application_Type"]="NIV"
    data["ctl00$ContentPlaceHolder1$Location_Dropdown"]=loc
    data["ctl00$ContentPlaceHolder1$Visa_Case_Number"]=case_no
    data["ctl00$ContentPlaceHolder1$Captcha"]=Predict(img_resp.content)
    data["__EVENTTARGET"]="ctl00$ContentPlaceHolder1$btnSubmit"
    data["ctl00$ToolkitScriptManager1"]="ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$btnSubmit"
    data["LBD_BackWorkaround_c_status_ctl00_contentplaceholder1_defaultcaptcha"]="1"
    data["__EVENTARGUMENT"]=""
    data["__LASTFOCUS"]=""
    resp = s.post(URL,data)
    soup = BeautifulSoup(resp.text, features="html.parser")
    error_text = soup.find(id="ctl00_ContentPlaceHolder1_lblError").text
    if error_text:
        return error_text, None
    status = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatus").text
    caseno = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblCaseNo").text
    SubmitDate = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblSubmitDate").text
    StatusDate = soup.find(id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatusDate").text
    assert caseno == case_no    
    return (status,SubmitDate,StatusDate), soup

if __name__ == "__main__":
    rst = query_ceac_state([
        ("BEJ","AA00A38G49"),
    #    ("SHG","AA00899Z9W"),
        
        ])
    pprint(rst)
