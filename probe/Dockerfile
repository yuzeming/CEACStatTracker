FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic-dev curl

# Copy requirements.txt
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install the specified packages
RUN pip install -r requirements.txt

# Copy function code
COPY app.py ${LAMBDA_TASK_ROOT}
COPY captcha.onnx ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "app.handler" ]