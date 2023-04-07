FROM python:3.11-alpine

RUN apk --no-cache add build-base libffi-dev

WORKDIR /app
COPY ./ /app/

RUN pip install -r requirements.txt
