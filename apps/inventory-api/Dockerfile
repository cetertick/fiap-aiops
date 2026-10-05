# inventory-api - multi-stage build, small final image, non-root user
FROM golang:1.22-alpine AS build

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY main.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/inventory-api .

FROM alpine:3.20

RUN addgroup -g 10001 appgroup && adduser -D -u 10001 -G appgroup appuser

COPY --from=build /out/inventory-api /usr/local/bin/inventory-api

USER appuser

EXPOSE 8002

CMD ["/usr/local/bin/inventory-api"]
