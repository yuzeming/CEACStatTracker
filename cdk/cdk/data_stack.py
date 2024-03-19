from aws_cdk import (
    Duration,
    Stack,
    aws_cloudfront as cloudfront,
    aws_ec2 as ec2,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_rds as rds,
    aws_s3 as s3,
)

from constructs import Construct

from cdk.util import PROJECT_NAME, Props, DB_SPECIAL_CHARS_EXCLUDE


class DataStack(Stack):
    aurora_db: rds.ServerlessCluster
    s3_public_images: s3.Bucket
    s3_private_images: s3.Bucket
    cloudfront_public_images: cloudfront.Distribution
    cloudfront_private_images: cloudfront.Distribution

    def __init__(
        self, scope: Construct, construct_id: str, props: Props, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # FILLMEIN: Aurora Serverless Database
        self.aurora_db = rds.ServerlessCluster(
            self,
            f"{PROJECT_NAME}-aurora-serverless",
            # Postgres engine version 13.10
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_13_10
            ),
            # Hosted in the VPC you created earlier, in the private, isolated (no egress) subnets
            vpc=props.network_vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            # Database name yoctogram
            default_database_name="yoctogram",
            # Database credentials generated for you within Secrets Manager, with username yoctogram
            # Exclude special characters from the credentials (conveniently, this string is defined for you as settings.DB_SPECIAL_CHARS_EXCLUDE)
            credentials=rds.Credentials.from_generated_secret(
                username="user1",
                exclude_characters=DB_SPECIAL_CHARS_EXCLUDE,
            ),
            
        )
