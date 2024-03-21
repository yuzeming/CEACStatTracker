import datetime
import json
import os
import uuid
from typing import List, Optional
from flask import Flask, request, flash, abort, make_response, jsonify
from flask.templating import render_template
from werkzeug.utils import redirect
from sqlalchemy import Integer, Select, String, create_engine, ForeignKey, DateTime
from sqlalchemy.orm import relationship, Session, DeclarativeBase, mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import func

import time
import requests
from location_list import LocationDict, LocationList
from .wechat import wechat_get_qr_code_url, check_wx_signature, xmltodict, wechat_push_msg

app = Flask(__name__)
app.secret_key = 'os.environ.get("SECRET_KEY")'
DB_URL = "sqlite:////tmp/ceac.sqlite"
if os.environ.get("POSTGRES_USER"):
    DB_URL = f"postgresql://{os.environ.get("POSTGRES_USER")}:{os.environ.get("POSTGRES_PASSWORD")}@{os.environ.get("POSTGRES_HOST")}:{os.environ.get("POSTGRES_PORT")}/{os.environ.get("POSTGRES_DB")}" 
db = create_engine(DB_URL)
db_session = Session(db)

HOST = os.environ.get("HOST", "https://track.moyu.ac.cn/detail/")
REMOTE_URL = os.environ.get("REMOTE_URL")

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
    status_date :Mapped[datetime.date] = mapped_column(DateTime)
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
    last_status : Optional[Mapped[str]] = mapped_column()
    passport_number :Mapped[Optional[str]] = mapped_column()
    surname :Mapped[Optional[str]] = mapped_column()

    push_channel :Mapped[Optional[str]] = mapped_column()
    qr_code_url :Mapped[Optional[str]] = mapped_column()
    qr_code_expire :Mapped[Optional[datetime.datetime]] = mapped_column()
    expire_date :Mapped[Optional[datetime.date]] = mapped_column()
    interview_date :Mapped[Optional[datetime.date]] = mapped_column()

    record_list :Mapped[List["Record"]] = relationship(cascade="all, delete-orphan", order_by="desc(Record.status_date)", foreign_keys="Record.case_id")

    @property
    def last_update(self):
        return self.record_list[0] if self.record_list else None

    def updateRecord(self, result, push_msg=True):
        status, _, status_date, message = result
        self.last_check = datetime.datetime.now()
        db_session.commit()
        status_date = parse_date(status_date)
        if self.last_update != None and \
            self.last_update.status_date == status_date and \
            self.last_update.status == status and \
            self.last_update.message == message:
            # no update needed
            return
        new_record = Record(case_id=self.id, status_date=status_date, status=status, message=message)
        db_session.add(new_record)
        self.last_status = status_date
        db_session.commit()
        db_session.refresh(new_record)
        if status == "Issued":
            self.expire_date = None
            self.passport_number = None
            self.surname = None
        db_session.commit()
        if self.push_channel and push_msg:
            self.push_msg()

    def renew(self, days=EXTENT_DAYS):
        if self.last_status == "Issued":
            return
        self.expire_date = (datetime.datetime.today() + datetime.timedelta(days=days)).date()

    def push_msg(self, first=None, remark=None):
        first = first or "你的签证状态有更新"
        keyword1 = self.case_no
        keyword2 = self.last_update.status
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


def divide_chunks(l, n):
    for i in range(0, len(l), n): 
        yield l[i:i + n]


@app.cli.command('sync')
def crontab_task():
    import time, random
    while True:
        try:
            print("Start sync at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
            last_check_expire = datetime.datetime.now() - datetime.timedelta(hours=4)
            stmt = Select(Case).where(Case.expire_date >= datetime.datetime.today(), Case.last_check <= last_check_expire, Case.passport_number != None)
            case_list : List[Case] = db_session.scalars(stmt).all()
            for chunk in divide_chunks(case_list, 10):
                req_data = [(case.location, case.case_no, case.passport_number, case.surname) for case in chunk]
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

@app.route("/init_db")
def init_db():
    if request.form.get("pwd") == os.environ.get("POSTGRES_PASSWORD"):
        Base.metadata.create_all(db)
        return "OK"
    else:
        return "Need Pwd"

@app.route("/import_case")
def import_case():
    if request.form.get("pwd") != os.environ.get("POSTGRES_PASSWORD"):
        return "Need Pwd"
    data = json.loads(request.body)
    c = data["case"]
    case_no = c["case_no"]
    stmt = Select(Case).where(Case.case_no == case_no).exists()
    if db_session.scalars(stmt):
        return "Case no exists"
    case = Case(
        case_no = case_no,
        location = c["location"],
        
    )
    
    

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
    case.updateRecord(result)
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
            db_session.delete(case)
            db_session.commit()
            flash("Completely deleted this case, See you.", category="success")
            return redirect("/")
        if act == "renew":
            flash(f"Expire +{EXTENT_DAYS} days", category="success")
            case.renew()
        if act == "refresh" and case.passport_number is not None:
            result = query_ceac_state_safe(case.location,case.case_no,case.passport_number, case.surname)
            if isinstance(result,str):
                flash(result, category="danger")
            else:
                case.updateRecord(result)
        interview_date = request.form.get("interview_date",None)
        if interview_date:
            case.interview_date = datetime.datetime.strptime(interview_date,"%Y-%m-%d")
        db_session.commit()
    if case.passport_number is None and case.last_update.status != "Issued":
        flash("Please register again and complete the passport number and surname. You don't need to delete this old case.", category="warning")
    return render_template("detail.html", case=case, record_list=case.record_list, location_str=LocationDict[case.location])


# STAT_RESULT_CACHE = None
# STAT_RESULT_CACHE_TIME = None
# STAT_RESULT_CACHE_MAX_AGE = 60 # 60min

# @app.route("/stat.js")
# def stat_result():
#     global STAT_RESULT_CACHE, STAT_RESULT_CACHE_TIME
#     if STAT_RESULT_CACHE is None or datetime.datetime.now() - STAT_RESULT_CACHE_TIME > datetime.timedelta(minutes=STAT_RESULT_CACHE_MAX_AGE):
#         this_week = datetime.datetime.today() - datetime.timedelta(days=datetime.datetime.today().weekday())
#         date_range = this_week - datetime.timedelta(days=52*7)
#         pipeline = [
#             {   "$match": { "interview_date":{"$gte": date_range} } },
#             {   "$lookup": { 
#                     "from": "record",
#                     "localField":"last_update",
#                     "foreignField":"_id",
#                     "as":"last_update"
#                 }
#             },{
#                 "$group": {
#                     "_id":{ 
#                         "date": { "$dateToString": { "format": "%Y-%m-%d", "date": "$interview_date"} },
#                         "status":"$last_update.status"
#                     },
#                     "count": {"$sum": 1}
#                 }
#             }
#         ]
#         stmt = Select(Case).where
#         tmp = {}
#         for line in result:
#             date = datetime.datetime.strptime(line["_id"]["date"],"%Y-%m-%d")
#             date -= datetime.timedelta(days=date.weekday())
#             date = date.strftime("%m-%d")
#             status = line["_id"]["status"][0]
#             count = int(line["count"])
#             if status not in tmp:
#                 tmp[status] = {}
#             if date not in tmp[status]:
#                 tmp[status][date] = 0
#             tmp[status][date] += count
        
#         labels = [(this_week - datetime.timedelta(days=i*7)).strftime("%m-%d") for i in range(52)]
#         STAT_RESULT_CACHE_TIME = datetime.datetime.now()
#         result = {
#             "_labels_":labels,
#             "_update_time_":  STAT_RESULT_CACHE_TIME.strftime("%Y-%m-%d %H:%M")
#         }
#         for s in tmp:
#             result[s] =[tmp[s].get(i,0) for i in labels]
#         STAT_RESULT_CACHE = "STAT_RESULT = " + json.dumps(result) + ";"
        
#     response = make_response(STAT_RESULT_CACHE)
#     response.headers['Cache-Control'] = f'max-age={STAT_RESULT_CACHE_MAX_AGE}'
#     response.headers['Content-Type'] = 'application/javascript'
#     return response


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
        case_list = [f"{case.case_no}[{case.last_update.status}]" for case in Case.objects(push_channel=req["FromUserName"])]
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
