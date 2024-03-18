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

PROJECT_NAME = "CEACStatTracker"

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

class CdkStack(Stack):

    hosted_zone: r53.IHostedZone
    network_vpc: ec2.Vpc

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


        self.hosted_zone = r53.HostedZone(
            self,
            f"{PROJECT_NAME}-hosted-zone",
            zone_name="bettyyw.infracourse.cloud",
        )

        self.backend_certificate = acm.Certificate(
            self,
            f"{PROJECT_NAME}-backend-certificate",
            # Domain name: SUNETID.infracourse.cloud
            domain_name = "ceac.bettyyw.infracourse.cloud",
            # Validation via DNS from the provisioned Hosted Zone (props.network_hosted_zone)
            validation=acm.CertificateValidation.from_dns(
                self.hosted_zone
            ),
        )

        # Vpc
        self.network_vpc = ec2.Vpc(
            self,
            "vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            availability_zones=["us-west-2a", "us-west-2b"],
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", cidr_mask=24, subnet_type=ec2.SubnetType.PUBLIC
                ),
                ec2.SubnetConfiguration(
                    name="private_egress", cidr_mask=24, subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                ec2.SubnetConfiguration(
                    name="private_isolated",
                    cidr_mask=24,
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                ),
            ],
        )

        cluster = ecs.Cluster(
            self, f"{PROJECT_NAME}-cluster", vpc=self.network_vpc
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

        # RDS
        self.aurora_db = rds.ServerlessCluster(
            self,
            f"{PROJECT_NAME}-aurora-serverless",
            # Postgres engine version 13.10
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_13_10
            ),
            # Hosted in the VPC you created earlier, in the private, isolated (no egress) subnets
            vpc=self.network_vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            default_database_name=f"{PROJECT_NAME}",
            # Database credentials generated for you within Secrets Manager, with username admin
            # Exclude special characters from the credentials (conveniently, this string is defined for you as settings.DB_SPECIAL_CHARS_EXCLUDE)
            credentials=rds.Credentials.from_generated_secret(
                username="adminuser1",
                exclude_characters=DB_SPECIAL_CHARS_EXCLUDE,
            ),
        )

        # probe
        self.probe_lambda = lambda_.Function(
            self, f"{PROJECT_NAME}-probe-lambda",
            runtime=lambda_.Runtime.FROM_IMAGE,
            handler=lambda_.Handler.FROM_IMAGE,
            code=lambda_.EcrImageCode.from_asset_image("../probe"),
            timeout=Duration.seconds(300),
            architecture=lambda_.Architecture.ARM_64,
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
            secretts[key] = ecs.Secret.from_secrets_manager(self.aurora_db.secret, field=val)
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
                cpu_architecture = ecs.CpuArchitecture.ARM64,
            ),
        )

        self.aurora_db.grant_data_api_access(self.fargate_task_definition.task_role)

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
        )

        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            f"{PROJECT_NAME}-fargate-service",
            cluster=cluster,
            task_definition = self.fargate_task_definition,
            domain_name = "ceac.bettyyw.infracourse.cloud",
            domain_zone = self.hosted_zone,
            certificate = self.backend_certificate,
            redirect_http = True,
        )