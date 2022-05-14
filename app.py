import datetime
import json
from typing import List
from flask import Flask, request,flash, abort, make_response
from flask.templating import render_template
from flask_mongoengine import MongoEngine
from flask_crontab import Crontab
from mongoengine.queryset.base import CASCADE
from werkzeug.utils import redirect

from .tracker_remote import query_ceac_state_remote, query_ceac_state_safe
from .location_list import LocationDict, LocationList
from .wechat import get_qr_code_url, config as wx_config, check_wx_signature, xmltodict, wechat_msg_push


app = Flask(__name__)
app.secret_key = "eawfopawjfoawe"
app.config['MONGODB_SETTINGS'] = {
    'host': 'mongodb://localhost/CEACStateTracker',
    'connect': False,
}

HOST = "https://track.moyu.ac.cn/detail/"

db = MongoEngine(app)
crontab = Crontab(app)

EXTENT_DAYS = 120
STAT_RESULT_CACHE = None
STAT_RESULT_CACHE_TIME = None

def parse_date(date_string):
    return datetime.datetime.strptime(date_string,"%d-%b-%Y").date()

class Case(db.Document):
    case_no = db.StringField(max_length=20, unique=True)
    location = db.StringField(max_length=5, choice=LocationList)
    last_update = db.ReferenceField("Record")
    created_date = db.DateField(format)
    last_seem = db.DateTimeField(default=datetime.datetime.now)

    push_channel = db.StringField(max_length=50)
    qr_code_url = db.StringField(max_length=100)
    qr_code_expire = db.DateTimeField(null=True)
    expire_date = db.DateField(null=True)
    interview_date = db.DateField(null=True)

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

class Record(db.Document):
    case = db.ReferenceField(Case, reverse_delete_rule=CASCADE)
    status_date = db.DateField()
    status = db.StringField()
    message = db.StringField()

# @crontab.job(hour="*", minute="32")
# def crontab_task():
#     last_seem_expire = datetime.datetime.now() - datetime.timedelta(hours=3)
#     case_list : List[Case] = Case.objects(expire_date__gte=datetime.datetime.today(), last_seem__lte=last_seem_expire)
#     soup = None
#     for case in case_list:
#         result, soup = query_ceac_state_safe(case.location, case.case_no, soup)
#         if isinstance(result, tuple):
#             case.updateRecord(result)

def divide_chunks(l, n):
    for i in range(0, len(l), n): 
        yield l[i:i + n]
  
@crontab.job(hour="*", minute="32")
def crontab_task_remote():
    last_seem_expire = datetime.datetime.now() - datetime.timedelta(hours=6)
    case_list : List[Case] = Case.objects(expire_date__gte=datetime.datetime.today(), last_seem__lte=last_seem_expire)
    for chunk in divide_chunks(case_list,50):
        req_data = [(case.location, case.case_no) for case in chunk]
        result_dict = query_ceac_state_remote(req_data)
        for case in chunk:
            result = result_dict[case.case_no]
            if isinstance(result, list):
                case.updateRecord(result)

@app.route("/task")
def crontab_task_debug():
    if not app.debug:
        return "disabled"
    crontab_task_remote()
    return "ok"


@app.route("/import", methods=["GET", "POST"])
def import_case():
    if not app.debug:
        return "disabled"
    error_list = []
    if request.method == "POST":
        req = request.form.get("lst")
        for line in req.splitlines():
            case_no, location = line.split()[:2]
            if not location or location not in LocationDict.keys() :
                error_list.append(line+"\t># No Location")
                continue
            
            if Case.objects(case_no=case_no).count() == 1:
                case = Case.objects(case_no=case_no).first()
            else:
                case = Case(case_no=case_no, location=location, created_date=parse_date(result[1]))
            result = query_ceac_state_safe(location,case_no)
            if isinstance(result,str):
                error_list.append(line+"\t># "+result)
                continue
            case.save()
            case.updateRecord(result, push_msg=False)
            case.renew()
        flash("ok",category="success")
    return render_template("import.html", lst = "\n".join(error_list))


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        case_no = request.form.get("case_no",None)
        location = request.form.get("location",None)
        if not case_no:
            flash("Invaild case no", category="danger")
            return render_template("index.html", case_no=case_no, location=location, LocationList=LocationList)
        if Case.objects(case_no=case_no).count() == 1:
            case = Case.objects(case_no=case_no).first()
            return redirect("detail/"+str(case.id))
        if not location or location not in LocationDict.keys() :
            flash("Invaild location", category="danger")
            return render_template("index.html", case_no=case_no, location=location, LocationList=LocationList)
        result = query_ceac_state_safe(location,case_no)
        if isinstance(result,str):
            flash(result, category="danger")
            return render_template("index.html", case_no=case_no, location=location, LocationList=LocationList)
        case = Case(case_no=case_no,location=location, created_date=parse_date(result[1]))
        case.save()
        case.updateRecord(result)
        case.renew()
        flash("Created a new case for you.", category="success")
        return redirect("detail/"+str(case.id))
    return render_template("index.html", LocationList=LocationList)


@app.route("/detail/<case_id>", methods=["GET", "POST"])
def detail_page(case_id):
    case = Case.objects.get_or_404(id=case_id) # type: Case
    if request.method == "POST":
        act = request.form.get("act",None)
        if act == "delete":
            case.delete()
            flash("Completely deleted this case, See you.", category="success")
            return redirect("/")
        if act == "renew":
            flash(f"Expire +{EXTENT_DAYS} days", category="success")
            case.renew()
        if act == "refresh":
            result = query_ceac_state_safe(case.location,case.case_no)
            if isinstance(result,str):
                flash(result, category="danger")
            else:
                case.updateRecord(result)
        interview_date = request.form.get("interview_date",None)
        if interview_date:
            case.interview_date = datetime.datetime.strptime(interview_date,"%Y-%m-%d")
        case.save()
    record_list = Record.objects(case=case).order_by('-status_date')
    return render_template("detail.html", case=case, record_list=record_list, location_str = LocationDict[case.location])

@app.route("/stat.js")
def stat_result():
    global STAT_RESULT_CACHE, STAT_RESULT_CACHE_TIME
    if STAT_RESULT_CACHE is None or datetime.datetime.now() - STAT_RESULT_CACHE_TIME > datetime.timedelta(minutes=5):
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
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
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

    req = xmltodict(request.data)
    EventKey = ""
    if req["MsgType"] == "event" and req["Event"] == "subscribe" and "EventKey" in req and req["EventKey"]:
        EventKey = req["EventKey"][8:]  #qrscene_
    if req["MsgType"] == "event" and req["Event"] == "SCAN":
        EventKey = req["EventKey"]

    if EventKey:
        Case.bind(EventKey, req["FromUserName"])

    return ""

if __name__ == '__main__':
    app.run()
