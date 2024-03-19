#!/usr/bin/env python3
import os

import aws_cdk as cdk
from cdk.util import PROJECT_NAME

from cdk.cdk.compute_stack import ComputeStack
from cdk.cdk.dns_stack import DnsStack
from cdk.cdk.network_stack import NetworkStack
from cdk.cdk.data_stack import DataStack
from cdk.cdk.util import Props, PROJECT_NAME, CDK_DEFAULT_ACCOUNT



app = cdk.App()
#CdkStack(app, "CdkStack",
    # If you don't specify 'env', this stack will be environment-agnostic.
    # Account/Region-dependent features and context lookups will not work,
    # but a single synthesized template can be deployed anywhere.

    # Uncomment the next line to specialize this stack for the AWS Account
    # and Region that are implied by the current CLI configuration.

    #env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),

    # Uncomment the next line if you know exactly what Account and Region you
    # want to deploy the stack to. */

    #env=cdk.Environment(account='123456789012', region='us-east-1'),

    # For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html
 #   )


props = Props()
env = cdk.Environment(account=CDK_DEFAULT_ACCOUNT)

dns_stack = DnsStack(app, f"{PROJECT_NAME}-dns-stack", env=env)
props.network_hosted_zone = dns_stack.hosted_zone

network_stack = NetworkStack(
    app, f"{PROJECT_NAME}-network-stack", props, env=env
)
props.network_vpc = network_stack.vpc
props.network_backend_certificate = network_stack.backend_certificate

data_stack = DataStack(app, f"{PROJECT_NAME}-data-stack", props, env=env)
props.aurora_db = data_stack.aurora_db


compute_stack = ComputeStack(
    app, f"{PROJECT_NAME}-compute-stack", props, env=env
)

data_stack.add_dependency(network_stack)
compute_stack.add_dependency(data_stack)

app.synth()
