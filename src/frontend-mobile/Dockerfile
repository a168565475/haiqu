FROM public.ecr.aws/docker/library/node:24-alpine
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm exec --yes --package=pnpm@10.27.0 -- pnpm install --frozen-lockfile --ignore-scripts
COPY . .
EXPOSE 8082
CMD ["npm", "exec", "--yes", "--package=pnpm@10.27.0", "--", "pnpm", "dev", "--host", "0.0.0.0"]
