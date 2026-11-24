FROM golang:1.26-alpine AS build
RUN apk add --no-cache git
ARG PR_SHA=3074051850c02a30abc0b98bb21f7d5e8b0e60e7
WORKDIR /src
RUN git init -q . \
 && git remote add origin https://github.com/AlexxIT/go2rtc \
 && git fetch --depth 1 origin pull/2340/head \
 && test "$(git rev-parse FETCH_HEAD)" = "$PR_SHA" \
 && git checkout -q FETCH_HEAD
RUN CGO_ENABLED=0 go build -ldflags "-s -w" -trimpath -o /go2rtc .

FROM alpine:3
RUN apk add --no-cache ffmpeg jq ca-certificates tzdata
COPY --from=build /go2rtc /usr/local/bin/go2rtc
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
