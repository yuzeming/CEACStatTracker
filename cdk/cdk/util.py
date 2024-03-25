import string
from typing import Dict, Optional

from aws_cdk import (
    aws_certificatemanager as acm,
    aws_cloudfront as cloudfront,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_route53 as r53,
    aws_s3 as s3,
)

PROJECT_NAME = "CEACStatTracker"

CDK_DEFAULT_ACCOUNT = "619809850642"


# copy from homework
DB_SPECIAL_CHARS_EXCLUDE: str = (
    string.printable.replace(string.ascii_letters, "")
    .replace(string.digits, "")
    .replace(string.whitespace, " ")
    .replace("_", "")
)

# copy from homework
DB_SECRET_MAPPING: Dict[str, str] = {
    "POSTGRES_HOST": "host",
    "POSTGRES_PORT": "port",
    "POSTGRES_USER": "username",
    "POSTGRES_PASSWORD": "password",
    "POSTGRES_DB": "dbname",
}

class Props:
    network_vpc: ec2.IVpc
    network_backend_certificate: acm.ICertificate
    network_hosted_zone: r53.IHostedZone
    aurora_db: rds.ServerlessCluster