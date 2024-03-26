from aws_cdk import (
    Stack,
    aws_certificatemanager as acm,
    aws_ec2 as ec2,
    aws_route53 as r53,
)
from constructs import Construct

from cdk.util import PROJECT_NAME, Props


class NetworkStack(Stack):
    backend_certificate: acm.ICertificate
    vpc: ec2.IVpc

    def __init__(
        self, scope: Construct, construct_id: str, props: Props, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # FILLMEIN: VPC
        self.vpc = ec2.Vpc(
            self,
            f"{PROJECT_NAME}-vpc",
            region = "us-west-2",
            # Two availability zones: us-west-2a and us-west-2b
            availability_zones=["us-west-2a", "us-west-2b"],
            # The VPC’s IP address space should be 10.0.0.0/16
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            # Three subnets, each within a CIDR /24, of the following types:
            # Public
            # Private with outbound (egress) internet access via a NAT gateway
            # Private and isolated (no egress internet access)
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

        # FILLMEIN: TLS certificate for backend
        self.backend_certificate = acm.Certificate(
            self,
            f"{PROJECT_NAME}-backend-certificate",
            # Domain name: SUNETID.infracourse.cloud
            domain_name = "ceac.bettyyw.infracourse.cloud",
            # Validation via DNS from the provisioned Hosted Zone (props.network_hosted_zone)
            validation=acm.CertificateValidation.from_dns(
                props.network_hosted_zone
            ),
        )
