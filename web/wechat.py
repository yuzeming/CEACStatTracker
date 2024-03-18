from datetime import datetime, timedelta
import requests
from xml.etree import ElementTree
import os
import yaml
from hashlib import sha1

appID = os.environ.get("appID")
appSecret = os.environ.get("appSecret")
serverToken = os.environ.get("serverToken")
tempID = os.environ.get("tempID") or "ArFK9lrJ57rW4t4QQ6bqtdt8IFsLFZkLlPfrHI5hlCo"


def check_wx_signature(signature, timestamp, nonce, token = serverToken):
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
    url = "https://api.weixin.qq.com/cgi-bin/stable_token"
    ret = requests.post(url, json={"grant_type": "client_credential", "appid": appID, "secret":  appSecret}).json()
    if "errcode" in ret:
        raise Exception(ret["errmsg"])
    return ret["access_token"]

'''
ArFK9lrJ57rW4t4QQ6bqtdt8IFsLFZkLlPfrHI5hlCo

{{first.DATA}}
订单编号：{{keyword1.DATA}}
订单状态：{{keyword2.DATA}}
{{remark.DATA}}
'''

def wechat_push_msg(touser, tempID=tempID, msg_url="", **kwargs):
    url = "https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={ACCESS_TOKEN}".format(
        ACCESS_TOKEN=get_access_token())
    data = {}
    for k,v in kwargs.items():
        data[k] = {"value": v}
    post_json = {"touser": touser, "template_id": tempID, "data": data, "url": msg_url}
    requests.post(url=url, json=post_json)

def wechat_get_qr_code_url(scene_str):
    url = " https://api.weixin.qq.com/cgi-bin/qrcode/create?access_token={ACCESS_TOKEN}".format(
        ACCESS_TOKEN=get_access_token())
    post_json = {"expire_seconds": 2592000, "action_name": "QR_STR_SCENE", "action_info": {"scene": {"scene_str": scene_str}} }
    ret = requests.post(url=url, json=post_json).json()
    if "errcode" in ret:
        raise RuntimeError(ret["errmsg"])
    return ret["url"]

