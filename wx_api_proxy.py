# -*- coding: utf8 -*-
import json
import os

# pip install requests == 2.29.0 -t .\src\
import requests

WX_URL = os.environ.get("WX_URL") or "https://api.weixin.qq.com/cgi-bin/stable_token"
AppID = os.environ.get("APPID")
def main_handler(event, context):
    data = json.loads(event["body"])
    if "appid" not in data or "secret" not in data:
        return "need appid and secret"
    if AppID is not None and data["appid"] != AppID:
        return "appid not allowed"
    req = requests.post(WX_URL, json = data)
    return req.text
