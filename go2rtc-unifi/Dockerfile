FROM alpine:3
RUN apk add --no-cache python3 ffmpeg ca-certificates tzdata
COPY server.py /server.py
CMD ["python3", "-u", "/server.py"]
