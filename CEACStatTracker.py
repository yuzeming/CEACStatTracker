from typing import Dict, List
import requests
import hashlib
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pprint import pprint
import logging

import predict

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

def get_data(soup=None):
    if soup is None:
        html = s.get(URL).text
        soup = BeautifulSoup(html, features="html.parser")
    data = read_hidden_input(soup)
    CaptchaImageUrl = soup.find(id="c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage").attrs["src"]
    img_resp = s.get(urljoin(URL,CaptchaImageUrl))
    data["ctl00$ContentPlaceHolder1$Captcha"]=predict.pred(img_resp.content)
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
        data = get_data()
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


def query_ceac_state_safe(loc, case_no):
    soup = None
    for _ in range(10):
        data = get_data(soup)
        result, soup = query_ceac_state(loc, case_no, data)
        if result != ERR_CAPTCHA:
            break
    return result

if __name__ == "__main__":
    req = [("BEJ","AA00A38G49"), ("SHG","AA00899Z9W"),("SGP","AA009ZAT9R"),("SGP","AA009YRTFV") ]
    soup = None
    for loc, case_no in req:
        for _ in range(10):
            data = get_data(soup)
            result, soup = query_ceac_state(loc, case_no, data)
            if result != ERR_CAPTCHA:
                break
        print(result)

