from aws_cdk import (
    Stack,
    aws_route53 as r53,
)
from constructs import Construct
from .util import PROJECT_NAME, Props

class DnsStack(Stack):
    hosted_zone: r53.IHostedZone

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.hosted_zone = r53.HostedZone(
            self,
            f"{PROJECT_NAME}-hosted-zone",
            zone_name="moyu.ac.cn",
        )