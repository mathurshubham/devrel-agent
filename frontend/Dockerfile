# Stage 1: Building the app
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the source code
COPY . .

# Build the Next.js app
# Disable linting and type checking during build to speed up and avoid failures in dev
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Stage 2: Running the app
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Copy necessary files from the builder stage
COPY --from=builder /app/next.config.ts ./
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

# Expose the port Next.js runs on
EXPOSE 3000

# Start the application
CMD ["npm", "start"]
