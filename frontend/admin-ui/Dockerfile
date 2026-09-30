# stage1 as builder
FROM node:22-alpine AS builder
ARG version=0.0.0-dev
ARG VITE_API_BASE_URL=/api/
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

WORKDIR /vue-ui

# Copy the package.json and install dependencies
COPY package*.json ./
RUN npm install

# Copy rest of the files
COPY . .

# Build the project
RUN npm version "$version" --no-git-tag-version --allow-same-version && npm run build

FROM nginx:stable-alpine AS production-build
COPY ./.nginx/nginx.template /etc/nginx/nginx.template
COPY ./.nginx/nginx.dev.template /etc/nginx/nginx.dev.template
COPY ./.nginx/nginx.course.template /etc/nginx/nginx.course.template
COPY ./.nginx/nginx.conf /etc/nginx/nginx.conf

## Remove default nginx index page
RUN rm -rf /usr/share/nginx/html/*


# Copy from the stage 1
COPY --from=builder /vue-ui/dist /usr/share/nginx/html

EXPOSE 80
