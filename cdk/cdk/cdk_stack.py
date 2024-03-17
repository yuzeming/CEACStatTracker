from aws_cdk import (
    # Duration,
    Stack,
    aws_lambda as lambda_,
    aws_apigateway as apigw_,
    aws_ec2 as ec2,
)
from constructs import Construct
import os


class CdkStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC
        vpc = ec2.Vpc(
            self,
            "Ingress",
            cidr="10.1.0.0/16",
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private-Subnet", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                )
            ],
        )

        ecr_image = lambda_.EcrImageCode.from_asset_image(
                directory = os.path.join(os.getcwd(), "lambda-image")
        )

        probe_lambda = lambda_.Function(
            self, "ProbeLambda",
            runtime=lambda_.Runtime.FROM_IMAGE,
            handler=lambda_.Handler.FROM_IMAGE,
            image=lambda_.EcrImageCode.from_asset_image(
                directory = os.path.join(os.getcwd(), "probe")
            )
        )