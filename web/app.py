import datetime
import json
import os
from typing import List
from flask import Flask, request,flash, abort, make_response, jsonify
from flask.templating import render_template
import mongoengine

from mongoengine.queryset.base import CASCADE
from werkzeug.utils import redirect
import time
import requests
from .location_list import LocationDict, LocationList
from .wechat import get_qr_code_url, config as wx_config, check_wx_signature, xmltodict, wechat_msg_push


app = Flask(__name__)
app.secret_key = "os.urandom(24)"
HOST = "https://track.moyu.ac.cn/detail/"

db = mongoengine.connect("CEACStateTracker")

public_key_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "public.pem")
PUBLIC_KEY = open(public_key_path).read()

EXTENT_DAYS = 120
STAT_RESULT_CACHE = None
STAT_RESULT_CACHE_TIME = None
STAT_RESULT_CACHE_MAX_AGE = 300

def parse_date(date_string):
    return datetime.datetime.strptime(date_string,"%d-%b-%Y").date()


URL = os.environ.get("REMOTE_URL") or "http://127.0.0.1:9000"

def query_ceac_state_safe(loc, case_no, info):
    retry = 0
    req = None
    while retry < 5:
        try:
            req = requests.post(URL, json=[[loc,case_no,info]], timeout=30)
            if req.status_code == 200:
                break
        except Exception as e:
            pass
        retry += 1
        time.sleep(1)
    if req is None:
        return "Server Error"
    return req.json()[case_no]


def query_ceac_state_batch(req_data):
    req = requests.post(URL, json=req_data, timeout=180)
    ret = req.json()
    return ret


class Case(mongoengine.Document):
    case_no = mongoengine.StringField(max_length=20, unique=True)
    location = mongoengine.StringField(max_length=5, choice=LocationList)
    last_update = mongoengine.ReferenceField("Record")
    created_date = mongoengine.DateField(default=datetime.datetime.now)
    last_seem = mongoengine.DateTimeField()
    info = mongoengine.StringField(max_length=1000) # to store the encrypted personal info

    push_channel = mongoengine.StringField(max_length=50)
    qr_code_url = mongoengine.StringField(max_length=100)
    qr_code_expire = mongoengine.DateTimeField(null=True)
    expire_date = mongoengine.DateField(null=True)
    interview_date = mongoengine.DateField(null=True)

    def updateRecord(self, result, push_msg=True):
        self.last_seem = datetime.datetime.now()
        self.save()

        status, _, status_date, message = result
        status_date = parse_date(status_date)
        if self.last_update != None and \
            self.last_update.status_date == status_date and \
            self.last_update.status == status and \
            self.last_update.message == message:
            # no update needed
            return
        new_record = Record(case=self, status_date=status_date, status=status, message=message)
        new_record.save()
        self.last_update = new_record
        if status == "Issued":
            # mark as expired now
            self.expire_date = None
            # delete the encrypted personal info
            self.info = None
        self.save()
        if self.push_channel and push_msg:
            self.push_msg()

    def renew(self, days=EXTENT_DAYS):
        if self.last_update and self.last_update.status == "Issued":
            return
        self.expire_date = (datetime.datetime.today() + datetime.timedelta(days=days)).date()
        self.save()

    def push_msg(self, first=None, remark=None):
        first = first or "你的签证状态有更新"
        keyword1 = self.case_no
        keyword2 = self.last_update.status
        remark = self.last_update.message
        wechat_msg_push(self.push_channel, msg_url=HOST+str(self.id),
            first=first, keyword1=keyword1, keyword2=keyword2, remark=remark)

    def get_qr_code_url(self):
        if self.qr_code_expire is None or datetime.datetime.now() > self.qr_code_expire:
            self.qr_code_url = get_qr_code_url(str(self.id))
            self.qr_code_expire = datetime.datetime.now() + datetime.timedelta(seconds=2592000)
            self.save()
        return self.qr_code_url
            
    @staticmethod
    def bind(case_id, wx_userid):
        case = Case.objects(id=case_id).first()
        if not case:
            return 
        case.push_channel = wx_userid
        case.save()
        case.push_msg(first="签证状态的更新会推送到这里")

class Record(mongoengine.Document):
    case = mongoengine.ReferenceField(Case, reverse_delete_rule=CASCADE)
    status_date = mongoengine.DateField()
    status = mongoengine.StringField()
    message = mongoengine.StringField()

def divide_chunks(l, n):
    for i in range(0, len(l), n): 
        yield l[i:i + n]


@app.cli.command('sync')
def crontab_task():
    import time, random
    while True:
        try:
            print("Start sync at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
            last_seem_expire = datetime.datetime.now() - datetime.timedelta(hours=4)
            case_list : List[Case] = Case.objects(expire_date__gte=datetime.datetime.today(), last_seem__lte=last_seem_expire, info__ne=None)
            for chunk in divide_chunks(case_list, 10):
                req_data = [(case.location, case.case_no, case.info) for case in chunk]
                print("Querying", [case.case_no for case in chunk])
                result_dict = query_ceac_state_batch(req_data)
                for case in chunk:
                    result = result_dict[case.case_no]
                    print("Updating", case.case_no, result)
                    if isinstance(result, list):
                        case.updateRecord(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
        time.sleep(60* random.randint(10,20))

@app.route("/", methods=["GET", "POST"])
def index():
    case_no = ""
    if request.method == "POST":
        case_no = request.form.get("case_no",None)
        if case_no and Case.objects(case_no=case_no).count() == 1:
            case = Case.objects(case_no=case_no).first()
            return redirect("detail/"+str(case.id))
        else:
            flash("No such case, register first?", category="danger")
    return render_template("index.html",case_no=case_no, LocationList=LocationList, PUBLIC_KEY=PUBLIC_KEY)


@app.route("/register", methods=["POST"])
def register():
    case_no = request.json.get("case_no",None)
    location = request.json.get("location",None)
    info = request.json.get("info",None)
    if not case_no:
        return jsonify({"status":"error", "error":"Invaild case no"})
    if Case.objects(case_no=case_no, info__ne= None).count() == 1:
        case = Case.objects(case_no=case_no).first()
        return jsonify({"status":"success", "case_id":str(case.id),})
    if not location or location not in LocationDict.keys() :
        return jsonify({"status":"error", "error":"Invaild location"})
    result = query_ceac_state_safe(location, case_no, info)
    if isinstance(result,str):
        return jsonify({"status":"error", "error":result})
    if Case.objects(case_no=case_no).count() == 1: # update the old case add info
        case = Case.objects(case_no=case_no).first()
        case.location = location
        case.info = info
    else:
        case = Case(case_no=case_no,location=location, created_date=parse_date(result[1]), info=info)
    case.save()
    case.updateRecord(result)
    case.renew()
    return jsonify({"status":"success", "case_id":str(case.id)})

@app.route("/detail/<case_id>", methods=["GET", "POST"])
def detail_page(case_id):
    case = Case.objects(id=case_id).first() # type: Case
    if case is None:
        return abort(404)
    if request.method == "POST":
        act = request.form.get("act",None)
        if act == "delete":
            case.delete()
            flash("Completely deleted this case, See you.", category="success")
            return redirect("/")
        if act == "renew":
            flash(f"Expire +{EXTENT_DAYS} days", category="success")
            case.renew()
        if act == "refresh" and case.info is not None:
            result = query_ceac_state_safe(case.location,case.case_no,case.info)
            if isinstance(result,str):
                flash(result, category="danger")
            else:
                case.updateRecord(result)
        interview_date = request.form.get("interview_date",None)
        if interview_date:
            case.interview_date = datetime.datetime.strptime(interview_date,"%Y-%m-%d")
        case.save()
    record_list = Record.objects(case=case).order_by('-status_date')
    if case.info is None and case.last_update.status != "Issued":
        flash("Please register again and complete the passport number and surname. You don't need to delete this old case.", category="warning")
    return render_template("detail.html", case=case, record_list=record_list, location_str=LocationDict[case.location])

@app.route("/stat.js")
def stat_result():
    global STAT_RESULT_CACHE, STAT_RESULT_CACHE_TIME
    if STAT_RESULT_CACHE is None or datetime.datetime.now() - STAT_RESULT_CACHE_TIME > datetime.timedelta(seconds=STAT_RESULT_CACHE_MAX_AGE):
        this_week = datetime.datetime.today() - datetime.timedelta(days=datetime.datetime.today().weekday())
        date_range = this_week - datetime.timedelta(days=52*7)
        pipeline = [
            {   "$match": { "interview_date":{"$gte": date_range} } },
            {   "$lookup": { 
                    "from": "record",
                    "localField":"last_update",
                    "foreignField":"_id",
                    "as":"last_update"
                }
            },{
                "$group": {
                    "_id":{ 
                        "date": { "$dateToString": { "format": "%Y-%m-%d", "date": "$interview_date"} },
                        "status":"$last_update.status"
                    },
                    "count": {"$sum": 1}
                }
            }
        ]
        result = Case.objects().aggregate(pipeline)
        tmp = {}
        for line in result:
            date = datetime.datetime.strptime(line["_id"]["date"],"%Y-%m-%d")
            date -= datetime.timedelta(days=date.weekday())
            date = date.strftime("%m-%d")
            status = line["_id"]["status"][0]
            count = int(line["count"])
            if status not in tmp:
                tmp[status] = {}
            if date not in tmp[status]:
                tmp[status][date] = 0
            tmp[status][date] += count
        
        labels = [(this_week - datetime.timedelta(days=i*7)).strftime("%m-%d") for i in range(52)]
        STAT_RESULT_CACHE_TIME = datetime.datetime.now()
        result = {
            "_labels_":labels,
            "_update_time_":  STAT_RESULT_CACHE_TIME.strftime("%Y-%m-%d %H:%M")
        }
        for s in tmp:
            result[s] =[tmp[s].get(i,0) for i in labels]
        STAT_RESULT_CACHE = "STAT_RESULT = " + json.dumps(result) + ";"
    response = make_response(STAT_RESULT_CACHE)
    response.headers['Cache-Control'] = f'max-age={STAT_RESULT_CACHE_MAX_AGE}'
    response.headers['Content-Type'] = 'application/javascript'
    return response


@app.route('/endpoint', methods=["GET","POST"])
def wechat_point():
    if not check_wx_signature(
        request.args.get("signature"), 
        request.args.get("timestamp"), 
        request.args.get("nonce"),
        wx_config["serverToken"]):
        return abort(500)
    if request.method == "GET":
        return request.args.get("echostr")

    msg = ""
    req = xmltodict(request.data)
    EventKey = ""
    if req["MsgType"] == "event" and req["Event"] == "subscribe" and "EventKey" in req and req["EventKey"]:
        EventKey = req["EventKey"][8:]  #qrscene_
    if req["MsgType"] == "event" and req["Event"] == "SCAN":
        EventKey = req["EventKey"]

    if EventKey:
        Case.bind(EventKey, req["FromUserName"])

    if req["MsgType"] == "text":
        case_list = [case.case_no for case in Case.objects(push_channel=req["FromUserName"])]
        case_list_str = "\n".join(case_list)
        msg = f"""\
<xml>
  <ToUserName><![CDATA[{req["FromUserName"]}]]></ToUserName>
  <FromUserName><![CDATA[{req["ToUserName"]}]]></FromUserName>
  <CreateTime>{ int(time.time()) }</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[绑定到这个微信号的推送：(共{len(case_list)}个)\n){ case_list_str }]]></Content>
</xml>
"""
        if req["Content"] == "test":
            wechat_msg_push(req["FromUserName"], 
                            keyword1="测试推送", keyword2="测试推送", 
                            remark="测试推送", first="测试推送", msg_url="https://track.moyu.ac.cn/")

    return msg

if __name__ == '__main__':
    app.run()
