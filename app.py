import datetime
from flask import Flask, request, flash, abort
from flask.templating import render_template
from flask_mongoengine import MongoEngine
from flask_mongoengine.wtf import model_form
from mongoengine.fields import *
from mongoengine import Document
from mongoengine.queryset.base import CASCADE
from mongoengine.queryset.transform import update
from werkzeug.utils import redirect
from wtforms import Form, SelectField, TextField
from wtforms.fields.core import Label
from .location_list import LocationDict, LocationList
from .CEACStatTracker import query_ceac_state
from .Wechat import get_qr_ticket, config, check_wx_signature, xmltodict

app = Flask(__name__)
app.secret_key = "eawfopawjfoawe"
app.config['MONGODB_SETTINGS'] = {
    'host': 'mongodb://localhost/CEACStateTracker',
}

db = MongoEngine(app)

def PushToUser():
    pass

def parse_date(date_string):
    return datetime.datetime.strptime(date_string,"%d-%b-%Y")

class Case(db.Document):
    case_no = db.StringField(max_length=20, unique=True)
    location = db.StringField(max_length=5, choice=LocationList)
    last_update = db.ReferenceField("Record")
    created_date = db.DateField(format)

    push_channel = db.StringField(max_length=50)
    qr_ticket = db.StringField(max_length=100)
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
            PushToUser(self.push_channel, self.case_no, status, status_date)

    def renew(self, days=7):
        if self.last_update and self.last_update.status == "Issued":
            return
        #if not self.qr_ticket or datetime.datetime.utcnow()-self.expire_date > datetime.timedelta(days=1):
        self.qr_ticket = get_qr_ticket(str(self.id))
        self.expire_date = datetime.datetime.utcnow() + datetime.timedelta(days=days)
        self.save()

    @staticmethod
    def bind(case_id,wx_userid):
        case = Case.objects(id=case_id).first()
        if case:
            case.push_channel = wx_userid
            case.save()
            case.push_msg()

class Record(db.Document):
    case = db.ReferenceField(Case, reverse_delete_rule=CASCADE)
    status_date = db.DateField()
    status = db.StringField()


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
        result = query_ceac_state([(location,case_no)])[case_no]
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

    

@app.route("/endpoint", methods=["GET"])
def wechat_point():
    if not check_wx_signature(
        request.args.get("signature"), 
        request.args.get("timestamp"), 
        request.args.get("nonce"),
        config["serverToken"]):
        return abort(500)
    return request.args.get("echostr")


@app.route('/endpoint/', methods=["POST"])
def wechat_point_post():
    if not check_wx_signature(
        request.args.get("signature"), 
        request.args.get("timestamp"), 
        request.args.get("nonce"),
        config["serverToken"]):
        return abort(500)
    req = xmltodict(request.data)
    EventKey = ""
    if req["MsgType"] == "event" and req["Event"] == "subscribe" and "EventKey" in req:
        EventKey = req["EventKey"][8:]  #qrscene_
    if req["MsgType"] == "event" and req["Event"] == "SCAN":
        EventKey = req["EventKey"]  #qrscene_

    Case.bindWX(EventKey, req["FromUserName"])

    return ""