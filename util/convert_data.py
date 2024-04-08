from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
import base64
import os
import json
from datetime import datetime, date
import requests
from typing import List, TypedDict

private_key_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "private_key.pem")
private_key = serialization.load_pem_private_key(
    open(private_key_path, 'rb').read(),
    password=None,
)


def decrypt(info):
    plaintext = private_key.decrypt(
        base64.b64decode(info),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    passport_number, surname = plaintext.decode().split(",")
    return passport_number, surname


class Record(TypedDict):
    status_date : date
    status: str
    message: str


class Case(TypedDict, total=False):
    case_no: str
    location: str
    created_date: date
    passport_number: str
    surname: str
    last_check: datetime
    last_status: str
    interview_date: date
    push_channel: str
    record_list: List[Record]
    

sorted_case = { } # oid => Case

def read_case_json():
    data = json.load(open("CEACStateTracker.case.json"))
    
    for i in data:
        passport_number, surname = None, None
        if "info" in i:
            passport_number, surname = decrypt(i["info"])
        case = Case(
            case_no = i["case_no"],
            location = i["location"],
            created_date = datetime.fromisoformat(i["created_date"]["$date"]).date(),
            passport_number = passport_number,
            surname = surname,
            last_check = datetime.fromisoformat(i["last_seem"]["$date"]),
            #last_status = i["last_status"],
            interview_date = datetime.fromisoformat(i["interview_date"]["$date"]).date() if i["interview_date"] else None,
            push_channel = i["push_channel"] if "push_channel" in i else None,
            record_list = []
        )
        sorted_case[i["_id"]["$oid"]] = case
    
    data = json.load(open("CEACStateTracker.record.json"))
    for i in data:
        record = Record(
            status_date = datetime.fromisoformat(i["status_date"]["$date"]).date(),
            status = i["status"],
            message = i["message"]
        )
        tmp = sorted_case[i["case"]["$oid"]]
        tmp["record_list"].append(record)
        tmp["last_status"] = record["status"]
        
    json.dump(sorted_case, open("CEACStateTracker.sorted_case.json", "w"), default= lambda x: x.isoformat())


def submit_case_json():
    sorted_case = json.load(open("CEACStateTracker.sorted_case.json"))
    for k,v in sorted_case.items():
        req = requests.post("http://localhost:5000/import_case", json=v)
        print(k, v["case_no"], req.text)

if __name__ == "__main__":
    read_case_json()
    submit_case_json()