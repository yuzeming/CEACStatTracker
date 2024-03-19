import datetime
import json
import os
import uuid
from typing import List, Optional
from flask import Flask, request, flash, abort, make_response, jsonify
from flask.templating import render_template
from werkzeug.utils import redirect
# from sqlalchemy import Integer, Select, String, create_engine, ForeignKey, DateTime
# from sqlalchemy.orm import relationship, Session, DeclarativeBase, mapped_column, Mapped
# from sqlalchemy.dialects.postgresql import UUID

app = Flask(__name__)

# DB_URL = f"postgresql://{os.environ.get("POSTGRES_USER")}:{os.environ.get("POSTGRES_PASSWORD")}@{os.environ.get("POSTGRES_HOST")}:{os.environ.get("POSTGRES_PORT")}/{os.environ.get("POSTGRES_DB")}" 
# db = create_engine(DB_URL)
# db_session = Session(db)

@app.route("/health")
def init_db():
    return "OK"


@app.route("/")
def index():
    return "Index"


if __name__ == '__main__':
    app.run()
