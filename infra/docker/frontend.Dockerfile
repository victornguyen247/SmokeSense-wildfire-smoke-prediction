FROM node:20-slim

WORKDIR /app

# Install deps first for layer caching
COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 5173

# Dev server; for production build with `npm run build` and serve via nginx.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
