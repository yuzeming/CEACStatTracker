from collections import defaultdict
import datetime
import json
import os
import uuid
from typing import List, Optional
from flask import Flask, request, flash, abort, make_response, jsonify
from flask.templating import render_template
from werkzeug.utils import redirect
from sqlalchemy import Integer, Select, String, create_engine, ForeignKey, Date, delete
from sqlalchemy.orm import relationship, Session, DeclarativeBase, mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import func

import time
import requests
from .location_list import LocationDict, LocationList
from .wechat import wechat_get_qr_code_url, check_wx_signature, xmltodict, wechat_push_msg

app = Flask(__name__)
app.secret_key = 'os.environ.get("SECRET_KEY")'
#DB_URL = "sqlite:////tmp/ceac.sqlite"
DB_URL = "sqlite:///ceac.sqlite"

if os.environ.get("POSTGRES_USER"):
    DB_URL = f'postgresql://{os.environ.get("POSTGRES_USER")}:{os.environ.get("POSTGRES_PASSWORD")}@{os.environ.get("POSTGRES_HOST")}:{os.environ.get("POSTGRES_PORT")}/{os.environ.get("POSTGRES_DB")}' 
db = create_engine(DB_URL, echo=app.debug)
db_session = Session(db)

HOST = os.environ.get("HOST") or "https://track.moyu.ac.cn/detail/"
REMOTE_URL = os.environ.get("REMOTE_URL") or "http://127.0.0.1:8000"

EXTENT_DAYS = 120

def parse_date(date_string):
    return datetime.datetime.strptime(date_string,"%d-%b-%Y").date()

def query_ceac_state_safe(loc, case_no, passport_number, surname):
    retry = 0
    req = None
    while retry < 5:
        try:
            req = requests.post(REMOTE_URL, json=[[loc, case_no, passport_number, surname]], timeout=30)
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
    req = requests.post(REMOTE_URL, json=req_data, timeout=180)
    ret = req.json()
    return ret

class Base(DeclarativeBase):
    pass

class Record(Base):
    __tablename__ = "record"
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, index=True, default=uuid.uuid4
    )
    case_id:Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("case.id"))
    status_date :Mapped[datetime.date] = mapped_column(Date)
    status :Mapped[str] = mapped_column()
    message :Mapped[str] = mapped_column()

class Case(Base):
    __tablename__ = "case"
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, index=True, default=uuid.uuid4
    )
    case_no :Mapped[str]  = mapped_column(unique=True, index=True)
    location :Mapped[str] = mapped_column(String(3))
    created_date :Mapped[datetime.date] = mapped_column(default=datetime.datetime.now)
    last_check :Mapped[datetime.datetime] = mapped_column()
    last_status : Mapped[Optional[str]] = mapped_column()
    passport_number :Mapped[Optional[str]] = mapped_column()
    surname :Mapped[Optional[str]] = mapped_column()

    push_channel :Mapped[Optional[str]] = mapped_column()
    qr_code_url :Mapped[Optional[str]] = mapped_column()
    qr_code_expire :Mapped[Optional[datetime.datetime]] = mapped_column()
    expire_date :Mapped[Optional[datetime.date]] = mapped_column()
    interview_date :Mapped[Optional[datetime.date]] = mapped_column()
    interview_week :Mapped[Optional[int]] = mapped_column() # for stat group by week

    record_list :Mapped[List["Record"]] = relationship(cascade="all, delete-orphan", order_by="desc(Record.status_date)", foreign_keys="Record.case_id")

    @property
    def marked_case_no(self):
        return self.case_no[:3] + "****" + self.case_no[-3:]

    @property
    def last_update(self):
        return self.record_list[0] if self.record_list else None

    @staticmethod
    def updateRecord(case_no, result, push_msg=True):
        stmt = Select(Case).where(Case.case_no == case_no)
        case_: Case = db_session.scalars(stmt).first()
        status, _, status_date, message = result
        case_.last_check = datetime.datetime.now()
        db_session.commit()
        status_date = parse_date(status_date)
        if case_.last_update != None and \
            case_.last_update.status_date == status_date and \
            case_.last_update.status == status and \
            case_.last_update.message == message:
            # no update needed
            return
        new_record = Record(case_id=case_.id, status_date=status_date, status=status, message=message)
        db_session.add(new_record)
        case_.last_status = status_date
        db_session.commit()
        db_session.refresh(new_record)
        if status == "Issued":
            case_.expire_date = None
            case_.passport_number = None
            case_.surname = None
        db_session.commit()
        if case_.push_channel and push_msg:
            case_.push_msg()

    def renew(self, days=EXTENT_DAYS):
        if self.last_status == "Issued":
            return
        self.expire_date = (datetime.datetime.today() + datetime.timedelta(days=days)).date()

    def push_msg(self, first=None, remark=None):
        first = first or "你的签证状态有更新"
        keyword1 = self.marked_case_no
        keyword2 = self.last_status
        remark = self.last_update.message
        wechat_push_msg(self.push_channel, msg_url=HOST+str(self.id),
            first=first, keyword1=keyword1, keyword2=keyword2, remark=remark)

    def get_qr_code_url(self):
        if self.qr_code_expire is None or datetime.datetime.now() > self.qr_code_expire:
            self.qr_code_url = wechat_get_qr_code_url(str(self.id))
            self.qr_code_expire = datetime.datetime.now() + datetime.timedelta(seconds=2592000)
            db_session.commit()
        return self.qr_code_url
        
    @staticmethod
    def bind(case_id, wx_userid):
        uuid_case_id = uuid.UUID(case_id)
        stmt = Select(Case).where(Case.id == uuid_case_id)
        case: Case = db_session.scalars(stmt).first()
        if not case:
            return 
        case.push_channel = wx_userid
        db_session.commit()
        case.push_msg(first="签证状态的更新会推送到这里")


Base.metadata.create_all(db, checkfirst=True)


def divide_chunks(l, n):
    for i in range(0, len(l), n): 
        yield l[i:i + n]


@app.cli.command('sync', help="Sync all case status")
def crontab_task():
    print("Start sync at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    last_check_expire = datetime.datetime.now() - datetime.timedelta(hours=6)
    stmt = Select(Case.location, Case.case_no, Case.passport_number, Case.surname)\
        .where(Case.expire_date >= datetime.datetime.today(), Case.last_check <= last_check_expire, Case.passport_number != None)
    case_list = db_session.execute(stmt).all()
    for req_data in divide_chunks(case_list, 10):
        req_data = [tuple(i) for i in req_data]
        print("Querying", [case[1] for case in req_data])
        result_dict = query_ceac_state_batch(req_data)
        for case_no ,result in result_dict.items():
            print("Updating" ,case_no, result)
            if isinstance(result, list):
                Case.updateRecord(case_no,result)

@app.route("/import_case", methods=["GET","POST"])
def import_case():
    if request.method == "GET":
        return render_template("import_case.html")
    if os.environ.get("POSTGRES_PASSWORD") is not None and request.form.get("pwd") != os.environ.get("POSTGRES_PASSWORD"):
        return "Need Pwd"
    if "file" not in request.files:
        return "No file part"
    file = request.files["file"]
    case_list = json.load(file)
    if type(case_list) == dict:
        case_list = case_list.values()
    def generate():
        yield "<pre>"
        yield "importing...\n"
        for c in case_list:
            case_no = c["case_no"]
            stmt = Select(Case.id).where(Case.case_no == case_no)
            if db_session.scalars(stmt).first():
                yield f"{case_no}: Case_no exists\n"
                db_session.rollback()
                continue
            case = Case(
                case_no = case_no,
                location = c["location"],
                created_date = datetime.date.fromisoformat(c["created_date"]),
                passport_number = c["passport_number"],
                surname = c["surname"],
                last_check = datetime.datetime.fromisoformat(c["last_check"]),
                last_status = c["last_status"],
                push_channel = c["push_channel"],
            )
            if c["interview_date"]:
                case.interview_date = datetime.date.fromisoformat(c["interview_date"])
                case.interview_week = case.interview_date.isocalendar()[0]*100 + case.interview_date.isocalendar()[1]
            case.expire_date = datetime.date.today() + datetime.timedelta(days=120) if case.last_status != "Issued" else None
            db_session.add(case)
            db_session.commit()
            db_session.refresh(case)
            for r in c["record_list"]:
                record = Record(
                    case_id = case.id,
                    status_date = datetime.date.fromisoformat(r["status_date"]),
                    status = r["status"],
                    message = r["message"]
                )
                db_session.add(record)
            db_session.commit()
            yield f"{case_no}: OK\n"
            yield "</pre>"
    return generate()
    
    

@app.route("/health")
def health():
    return "OK"

@app.route("/", methods=["GET", "POST"])
def index():
    case_no = ""
    if request.method == "POST":
        case_no = request.form.get("case_no","")
        if case_no:
            stmt = Select(Case).where(Case.case_no == case_no)
            case = db_session.scalars(stmt).first()
            if case:
                return redirect("detail/"+str(case.id))
            else:
                flash("No such case, register first?", category="danger")
    return render_template("index.html",case_no=case_no, LocationList=LocationList)

@app.route("/register", methods=["POST"])
def register():
    case_no = request.json.get("case_no",None)
    location = request.json.get("location",None)
    passport_number = request.json.get("passport_number",None)
    surname = request.json.get("surname",None)
    if not case_no:
        return jsonify({"status":"error", "error":"Invaild case no"})
    if not location or location not in LocationDict.keys() :
        return jsonify({"status":"error", "error":"Invaild location"})
    result = query_ceac_state_safe(location, case_no, passport_number, surname)
    if isinstance(result,str):
        return jsonify({"status":"error", "error":result})
    stmt = Select(Case).where(Case.case_no == case_no)
    case = db_session.scalars(stmt).first()
    if case: # update the old case
        case.location = location
        case.passport_number = passport_number
        case.surname = surname
    else:
        case = Case(case_no=case_no,location=location, created_date=parse_date(result[1]), passport_number=passport_number, surname=surname)
        db_session.add(case)
    Case.updateRecord(case_no, result)
    case.renew()
    db_session.commit()
    return jsonify({"status":"success", "case_id":str(case.id)})

@app.route("/detail/<case_id>", methods=["GET", "POST"])
def detail_page(case_id):
    uuid_case_id = uuid.UUID(case_id)
    stmt = Select(Case).where(Case.id == uuid_case_id)
    case = db_session.scalars(stmt).first()
    if case is None:
        return abort(404)
    if request.method == "POST":
        act = request.form.get("act",None)
        if act == "delete":
            case_no = request.form.get("case_no",None)
            if case_no == case.case_no:
                db_session.delete(case)
                db_session.commit()
                flash("Completely deleted this case, See you.", category="success")
                return redirect("/")
            else:
                flash("Case no not match", category="danger")
        if act == "renew":
            flash(f"Expire +{EXTENT_DAYS} days", category="success")
            case.renew()
        if act == "refresh" and case.passport_number is not None:
            result = query_ceac_state_safe(case.location,case.case_no,case.passport_number, case.surname)
            if isinstance(result,str):
                return jsonify({"status":"error", "error":result})
            else:
                case.updateRecord(result)
                return jsonify({"status":"success", "title": result[0], "message": result[3]})
        interview_date = request.form.get("interview_date",None)
        if interview_date:
            case.interview_date = datetime.datetime.strptime(interview_date,"%Y-%m-%d")
            case.interview_week = case.interview_date.isocalendar()[0]*100 + case.interview_date.isocalendar()[1]
        db_session.commit()
    if case.passport_number is None and case.last_status != "Issued":
        flash("Please register again and complete the passport number and surname. You don't need to delete this old case.", category="warning")
    return render_template("detail.html", case=case, record_list=case.record_list, location_str=LocationDict[case.location])


STAT_RESULT_CACHE = None
STAT_RESULT_CACHE_TIME = None
STAT_RESULT_CACHE_MAX_AGE = 60 # 60min



@app.route("/stat.js")
def stat_result():
    global STAT_RESULT_CACHE, STAT_RESULT_CACHE_TIME
    if STAT_RESULT_CACHE is None or datetime.datetime.now() - STAT_RESULT_CACHE_TIME > datetime.timedelta(minutes=STAT_RESULT_CACHE_MAX_AGE):
        this_week = datetime.datetime.now() - datetime.timedelta(days=datetime.datetime.now().isoweekday()-1)
        date_range = datetime.datetime.now() - datetime.timedelta(weeks=52)
        week_range = date_range.isocalendar()[0]*100 + date_range.isocalendar()[1]
        stmt = Select(func.count(),Case.last_status, Case.interview_week) \
            .group_by(Case.last_status, Case.interview_week) \
            .filter(Case.interview_week != None) \
            .filter(Case.interview_week >= week_range)
        result = db_session.execute(stmt).all()
        stat_json = defaultdict(dict)
        labels = set()
        for count, status, week in result:
            week_str = datetime.date.fromisocalendar(week//100, week%100, 1).strftime("%m-%d")
            stat_json[status][week_str] = count
            labels.add(week_str)
        labels = [(this_week - datetime.timedelta(days=i*7)).strftime("%m-%d") for i in range(52)]
        stat_json = { k: [stat_json[k].get(l,0) for l in labels] for k in stat_json.keys()}
        
        STAT_RESULT_CACHE_TIME = datetime.datetime.now()
        stat_json["_labels_"] = labels
        stat_json["_update_time_"]=STAT_RESULT_CACHE_TIME.strftime("%Y-%m-%d %H:%M")
        STAT_RESULT_CACHE = "var STAT_RESULT = " + json.dumps(stat_json) + ";"
    response = make_response(STAT_RESULT_CACHE)
    response.headers['Cache-Control'] = f'max-age={STAT_RESULT_CACHE_MAX_AGE}'
    response.headers['Content-Type'] = 'application/javascript'
    return response


@app.route('/endpoint', methods=["GET","POST"])
def wechat_point():
    if not check_wx_signature(
        request.args.get("signature"), 
        request.args.get("timestamp"), 
        request.args.get("nonce")):
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
        case_list = [f"{case.marked_case_no}[{case.last_status}]" for case in Case.objects(push_channel=req["FromUserName"])]
        case_list_str = "\n".join(case_list)
        msg = f"""\
<xml>
  <ToUserName><![CDATA[{req["FromUserName"]}]]></ToUserName>
  <FromUserName><![CDATA[{req["ToUserName"]}]]></FromUserName>
  <CreateTime>{ int(time.time()) }</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[绑定到这个微信号的推送：(共{len(case_list)}个)\n{ case_list_str }]]></Content>
</xml>
"""
        if req["Content"] == "test":
            wechat_push_msg(req["FromUserName"], 
                            keyword1="测试推送", keyword2="测试推送", 
                            remark="测试推送", first="测试推送", msg_url=HOST)

    return msg

if __name__ == '__main__':
    app.run()
