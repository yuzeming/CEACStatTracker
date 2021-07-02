from datetime import datetime, timedelta
import requests
from xml.etree import ElementTree
import os
import yaml
from hashlib import sha1

config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.yaml")
if os.path.exists(config_path):
    config = yaml.safe_load(open("config.yaml"))

def check_wx_signature(signature, timestamp, nonce, token):
    if not signature or not timestamp or not nonce or not token:
        return False
    if datetime.timestamp(datetime.now()) - float(timestamp) > 30:
        return False
    args = [token, timestamp, nonce]
    args.sort()
    m = sha1(("".join(args)).encode()).hexdigest()
    if m != signature:
        return False
    return True

def xmltodict(xml_string):
    root = ElementTree.fromstring(xml_string)
    ret = [(child.tag, child.text) for child in root]
    return dict(ret)

def get_access_token():
    if config.get("accessToken","") and config["tokenExpires"] > datetime.now():
        return config["accessToken"]
    url = "https://api.weixin.qq.com/cgi-bin/token"
    ret = requests.get(url, {"grant_type": "client_credential", "appid": config["appID"], "secret":  config["appSecret"]}).json()
    if "errcode" in ret:
        raise ret["errmsg"]
    config["accessToken"] = ret["access_token"]
    config["tokenExpires"] = timedelta(seconds=ret["expires_in"]) + datetime.now()
    yaml.dump(config, open("config.yaml","w"))

    return config["accessToken"]

def wechat_msg_push(touser, tempID=config["tempID"], content="TEST", msg_url=""):
    url = "https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={ACCESS_TOKEN}".format(
        ACCESS_TOKEN=get_access_token())
    data = {"CONTENT": {"value": content}}
    post_json = {"touser": touser, "template_id": tempID, "data": data, "url": msg_url}
    requests.post(url=url, json=post_json)

def get_qr_code_url(scene_str):
    url = " https://api.weixin.qq.com/cgi-bin/qrcode/create?access_token={ACCESS_TOKEN}".format(
        ACCESS_TOKEN=get_access_token())
    post_json = {"expire_seconds": 2592000, "action_name": "QR_STR_SCENE", "action_info": {"scene": {"scene_str": scene_str}} }
    ret = requests.post(url=url, json=post_json).json()
    if "errcode" in ret:
        raise ret["errmsg"]
    return ret["url"]

