import datetime
import logging
from typing import List
from flask import Flask, request, flash, abort
from flask.templating import render_template
from flask_mongoengine import MongoEngine
from flask_crontab import Crontab
from mongoengine.queryset.base import CASCADE
from werkzeug.utils import redirect
from .location_list import LocationDict, LocationList
from .CEACStatTracker import query_ceac_state
from .Wechat import get_qr_code_url, config as wx_config, check_wx_signature, xmltodict, wechat_msg_push

app = Flask(__name__)
app.secret_key = "eawfopawjfoawe"
app.config['MONGODB_SETTINGS'] = {
    'host': 'mongodb://localhost/CEACStateTracker',
}

HOST = "track.yuzm.me/detail/"

db = MongoEngine(app)
crontab = Crontab(app)

def parse_date(date_string):
    return datetime.datetime.strptime(date_string,"%d-%b-%Y")

class Case(db.Document):
    case_no = db.StringField(max_length=20, unique=True)
    location = db.StringField(max_length=5, choice=LocationList)
    last_update = db.ReferenceField("Record")
    created_date = db.DateField(format)

    push_channel = db.StringField(max_length=50)
    qr_code_url = db.StringField(max_length=100)
    expire_date = db.DateTimeField()

    def updateRecord(self,result):
        status, _, status_date = result
        status_date = parse_date(status_date)
        if self.last_update != None and self.last_update.status_date == status_date and self.last_update.status == status:
            # no update needed
            return
        new_record = Record(case=self, status_date=status_date, status=status)
        new_record.save()
        self.last_update = new_record
        if status == "Issued":
            # mark as expired now
            self.expire_date = datetime.datetime.utcnow()
        self.save()
        if self.push_channel:
            self.push_msg()

    def renew(self, days=7):
        if self.last_update and self.last_update.status == "Issued":
            return
        #if not self.qr_code_url or datetime.datetime.utcnow()-self.expire_date > datetime.timedelta(days=1):
        self.qr_code_url = get_qr_code_url(str(self.id))
        self.expire_date = datetime.datetime.utcnow() + datetime.timedelta(days=days)
        self.save()

    def push_msg(self, msg=None):
        if msg is None:
            msg = "Welcome, Update of your case will be pushed here."
            if self.last_update:
                msg = "State: {}\nLast update:{}".format(self.last_update.status, self.last_update.status_date.strftime("%x"))
        wechat_msg_push(self.push_channel, content=msg, url=HOST+str(self.id))

    @staticmethod
    def bind(case_id, wx_userid):
        case = Case.objects(id=case_id).first()
        if case:
            case.push_channel = wx_userid
            case.save()
            case.push_msg()

class Record(db.Document):
    case = db.ReferenceField(Case, reverse_delete_rule=CASCADE)
    status_date = db.DateField()
    status = db.StringField()


@crontab.job(hour="2,8,14,20", minute="32")
def crontab_task():
    logging.basicConfig(filename='crontab_task.log', level=logging.INFO)
    l = logging.getLogger("crontab_task")

    case_list : List[Case] = Case.objects(expire_date__gte=datetime.datetime.utcnow())
    
    l.info("Task start %d", case_list.count())

    soup = None
    for case in case_list:
        try:
            result, soup = query_ceac_state(case.location, case.case_no, soup)
        except:
            l.error("Error %s-%s",case.location, case.case_no, exc_info=True)
            soup = None
            continue
        if isinstance(result, str):
            l.warn("Warn %s-%s: %s",case.location, case.case_no, result)
        else:
            l.info("Succ %s-%s: %s",case.location, case.case_no, result)
            case.updateRecord(result)
    

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        case_no = request.form.get("case_no",None)
        location = request.form.get("location",None)
        if not case_no:
            flash("invaild case no")
            return redirect("/")
        if Case.objects(case_no=case_no).count() == 1:
            case = Case.objects(case_no=case_no).first()
            return redirect("detail/"+str(case.id))
        if not location or location not in LocationDict.keys() :
            flash("invaild location")
            return redirect("/")
        result, _ = query_ceac_state(location,case_no)
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