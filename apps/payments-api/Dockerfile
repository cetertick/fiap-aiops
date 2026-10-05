# payments-api - multi-stage build, small final image, non-root user
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json .
RUN npm install --omit=dev --no-audit --no-fund

FROM node:20-alpine

WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY package.json .
COPY server.js .

USER node

EXPOSE 8001

CMD ["node", "server.js"]
