FROM node:22-alpine

WORKDIR /app

# Pin to the version in package.json's packageManager field: an unpinned
# pnpm self-substitutes the pinned version as a native @pnpm/exe binary and
# refuses because it is not in pnpm-lock.yaml
RUN npm install -g pnpm@10.10.0

COPY package.json pnpm-lock.yaml* ./

RUN pnpm install --frozen-lockfile

COPY . .

RUN pnpm run build

RUN pnpm prune --prod

ENV NODE_ENV=production

EXPOSE 3000

CMD ["node", "build/index.js"]