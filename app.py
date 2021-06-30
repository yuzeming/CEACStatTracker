import datetime
import logging
from typing import List
from flask import Flask, request, flash, abort, has_request_context
from flask.templating import render_template
from flask.wrappers import Response
from flask_mongoengine import MongoEngine
from flask_crontab import Crontab
from mongoengine.queryset.base import CASCADE
from requests.sessions import default_hooks
from werkzeug.utils import redirect
from .location_list import LocationDict, LocationList
from .Wechat import get_qr_code_url, config as wx_config, check_wx_signature, xmltodict, wechat_msg_push
from .CEACStatTracker import get_data,ERR_CAPTCHA, query_ceac_state, query_ceac_state_safe

app = Flask(__name__)
app.secret_key = "eawfopawjfoawe"
app.config['MONGODB_SETTINGS'] = {
    'host': 'mongodb://localhost/CEACStateTracker',
}


HOST = "https://track.yuzm.me/detail/"

db = MongoEngine(app)
crontab = Crontab(app)

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
    expire_date = db.DateField(null=True)

    def updateRecord(self,result):
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
        if self.push_channel:
            self.push_msg()

    def renew(self, days=14):
        if self.last_update and self.last_update.status == "Issued":
            return
        #if not self.qr_code_url or datetime.datetime.utcnow()-self.expire_date > datetime.timedelta(days=1):
        self.expire_date = (datetime.datetime.today() + datetime.timedelta(days=days)).date()
        self.qr_code_url = get_qr_code_url(str(self.id))
        self.save()

    def push_msg(self, msg=None):
        if msg is None:
            msg = "Welcome, Update of your case will be pushed here."
            if self.last_update:
                msg = "Case No: {}\nState: {}\nLast Update: {}".format(self.case_no, self.last_update.status, self.last_update.status_date.strftime("%x"))
        wechat_msg_push(self.push_channel, content=msg, msg_url=HOST+str(self.id))

    @staticmethod
    def bind(case_id, wx_userid):
        case = Case.objects(id=case_id).first()
        if not case:
            return 
        case.push_channel = wx_userid
        case.save()
        case.push_msg()

class Record(db.Document):
    case = db.ReferenceField(Case, reverse_delete_rule=CASCADE)
    status_date = db.DateField()
    status = db.StringField()
    message = db.StringField()

@crontab.job(hour="14", minute="32")
def crontab_task():
    case_list : List[Case] = Case.objects(expire_date__gte=datetime.datetime.today())
    soup = None
    for case in case_list:
        try:
            for _ in range(10):
                data = get_data(soup)
                result, soup = query_ceac_state_safe(case.location, case.case_no, data)
                if result != ERR_CAPTCHA:
                    break
        except:
            soup = None
            continue
        if isinstance(result, tuple):
            case.updateRecord(result)
    
@app.route("/task-aaa1222")
def crontab_task_debug():
    crontab_task()
    return "ok"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        case_no = request.form.get("case_no",None)
        location = request.form.get("location",None)
        if not case_no:
            flash("Invaild case no")
            return render_template("index.html", case_no=case_no, location=location, LocationList=LocationList)
        if Case.objects(case_no=case_no).count() == 1:
            case = Case.objects(case_no=case_no).first()
            return redirect("detail/"+str(case.id))
        if not location or location not in LocationDict.keys() :
            flash("Invaild location")
            return render_template("index.html", case_no=case_no, location=location, LocationList=LocationList)
        result = query_ceac_state_safe(location,case_no)
        if isinstance(result,str):
            flash(result)
            return render_template("index.html", case_no=case_no, location=location, LocationList=LocationList)
        case = Case(case_no=case_no,location=location, created_date=parse_date(result[1]))
        case.save()
        case.updateRecord(result)
        case.renew()
        flash("Created a new case for you.")
        return redirect("detail/"+str(case.id))
    return render_template("index.html", LocationList=LocationList)


@app.route("/detail/<case_id>", methods=["GET", "POST"])
def detail_page(case_id):
    case = Case.objects.get_or_404(id=case_id)
    if request.method == "POST":
        act = request.form.get("act",None)
        if act == "delete":
            case.delete()
            flash("Completely deleted this case, See you.")
            return redirect("/")
        if act == "renew":
            flash("Expire +7 days")
            case.renew()
        if act == "refresh":
            result = query_ceac_state_safe(case.location,case.case_no)
            if isinstance(result,str):
                flash(result)
            else:
                case.updateRecord(result)
    record_list = Record.objects(case=case).order_by('-seem')
    return render_template("detail.html", case=case, record_list=record_list, location_str = LocationDict[case.location])

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
    if req["MsgType"] == "event" and req["Event"] == "subscribe" and "EventKey" in req:
        EventKey = req["EventKey"][8:]  #qrscene_
    if req["MsgType"] == "event" and req["Event"] == "SCAN":
        EventKey = req["EventKey"]  #qrscene_

    if EventKey:
        Case.bind(EventKey, req["FromUserName"])

    return ""

if __name__ == '__main__':
    app.run()