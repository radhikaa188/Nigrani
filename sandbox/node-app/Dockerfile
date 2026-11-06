# Pinned minimal Node.js Alpine base image
FROM node:20.18.0-alpine3.20

# Create working directory and set non-root ownership
WORKDIR /app
RUN chown node:node /app

# Switch to non-root user
USER node

# Copy package manifests first for reproducible install and layer caching
COPY --chown=node:node package*.json ./

# Install dependencies deterministically
RUN npm ci

# Copy application source code
COPY --chown=node:node . .

# Configurable application port via environment variable
ENV PORT=3000
EXPOSE ${PORT}

# Default command for standard Node.js applications
CMD ["npm", "start"]
