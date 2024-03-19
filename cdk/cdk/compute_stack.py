from aws_cdk import (
    Duration,
    Stack,
    aws_lambda as lambda_,
    aws_apigateway as apigw_,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
    aws_route53 as r53,
    aws_rds as rds,
    aws_ecs as ecs,
    aws_logs as logs,
    aws_ecs_patterns as ecs_patterns,
    aws_certificatemanager as acm,
)
from constructs import Construct
import os, string
from typing import Dict

from .util import PROJECT_NAME, DB_SPECIAL_CHARS_EXCLUDE, DB_SECRET_MAPPING, Props


class ComputeStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, props: Props, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cluster = ecs.Cluster(
            self, f"{PROJECT_NAME}-cluster", vpc=props.network_vpc
        )

        # # Secret
        # self.wechat_appid = secretsmanager.Secret(
        #     self,
        #     f"{PROJECT_NAME}-wechat-appid",
        #     description="Wechat AppID",
        # )

        # self.wechat_secret = secretsmanager.Secret(
        #     self,
        #     f"{PROJECT_NAME}-wechat-secret",
        #     description="Wechat Secret",
        # )

        # self.wechat_token = secretsmanager.Secret(
        #     self,
        #     f"{PROJECT_NAME}-wechat-token",
        #     description="Wechat Token",
        # )

        # probe
        self.probe_lambda = lambda_.Function(
            self, f"{PROJECT_NAME}-probe-lambda",
            runtime=lambda_.Runtime.FROM_IMAGE,
            handler=lambda_.Handler.FROM_IMAGE,
            code=lambda_.EcrImageCode.from_asset_image("../probe"),
            timeout=Duration.seconds(300),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
        )

        self.apigw = apigw_.LambdaRestApi(
            self,
            f"{PROJECT_NAME}-probe-apigw",
            handler=self.probe_lambda,
        )

        # Web Fargate 
        secretts = {}
        for key in DB_SECRET_MAPPING:
            val = DB_SECRET_MAPPING[key]
            secretts[key] = ecs.Secret.from_secrets_manager(props.aurora_db.secret, field=val)
        # secretts["appId"] = ecs.Secret.from_secrets_manager(self.wechat_appid)
        # secretts["appSecret"] = ecs.Secret.from_secrets_manager(self.wechat_secret)
        # secretts["serverToken"] = ecs.Secret.from_secrets_manager(self.wechat_token)


        self.fargate_task_definition = ecs.FargateTaskDefinition(
            self,
            f"{PROJECT_NAME}-fargate-task-definition",
            memory_limit_mib = 2048,
            cpu = 512,
            runtime_platform = ecs.RuntimePlatform(
                operating_system_family = ecs.OperatingSystemFamily.LINUX,
                cpu_architecture = ecs.CpuArchitecture.X86_64,
            ),
        )

        props.aurora_db.grant_data_api_access(self.fargate_task_definition.task_role)

        self.fargate_task_definition.add_container(
            f"{PROJECT_NAME}-app-container",
            container_name=f"{PROJECT_NAME}-app-container",
            logging=ecs.AwsLogDriver(
                stream_prefix = f"{PROJECT_NAME}-fargate",
                log_retention = logs.RetentionDays.ONE_WEEK,
            ),
            image = ecs.ContainerImage.from_asset("../web"),
            port_mappings = [ecs.PortMapping(container_port=80)],
            environment = {
                "PRODUCTION": "true",
                "DEBUG": "false",
                "REMOTE_URL": self.apigw.url,
            },
            secrets = secretts,
            health_check = ecs.HealthCheck(
                command = ["curl -f http://localhost/health/ || exit 1"],
            ),
        )

        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            f"{PROJECT_NAME}-fargate-service",
            cluster=cluster,
            task_definition = self.fargate_task_definition,
            domain_name = "ceac.bettyyw.infracourse.cloud",
            domain_zone = props.network_hosted_zone,
            certificate = props.network_backend_certificate,
            redirect_http = True,
        )

        fargate_service.service.connections.allow_to(
            props.aurora_db, ec2.Port.tcp(5432), "DB access"
        )
