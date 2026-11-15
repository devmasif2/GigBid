# Railway deployment

Railway requires one service for the API, one for the React web app, and a PostgreSQL service.
The local GigSim service is optional and should be added only when simulator-backed messages and
pipeline data are needed.

## API service

Create a service from the repository and set its Dockerfile to
`infra/docker/Dockerfile.api`. Configure:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
GIGBID_MARKETPLACE_MODE=sample
GIGBID_PORTFOLIO_PATH=data/sample/portfolio_items.json
GIGBID_CORS_ORIGINS=https://YOUR-WEB-DOMAIN
```

Expose port `8000` and set the healthcheck path to `/health`. After deployment, verify the
generated API URL returns `{"status":"ok"}` at `/health`.

## Web service

Create another service from the same repository with root directory `apps/web`. The
`apps/web/railway.json` file supplies the Nixpacks build and start commands. Set this build
environment variable to the API's public URL:

```env
VITE_API_URL=https://YOUR-API-DOMAIN
```

Because Vite embeds `VITE_API_URL` during `npm run build`, redeploy the web service after changing
the API URL. Set the web service healthcheck path to `/`.

## Optional simulator

Add a third service from the repository using `infra/docker/Dockerfile.api` and override its
start command with `python -m gigsim_local`. Set:

```env
GIGSIM_HOST=0.0.0.0
GIGSIM_USER_TOKENS=gigsim-dev-token:dev-user
GIGSIM_ADMIN_TOKEN=replace-with-a-private-value
```

Then change the API variables to:

```env
GIGBID_MARKETPLACE_MODE=gigsim
GIGSIM_BASE_URL=http://PRIVATE-GIGSIM-HOST:8100
GIGSIM_API_TOKEN=gigsim-dev-token
```

Do not expose simulator admin credentials in the repository. This deployment remains an
assignment prototype: it has no secure multi-user authentication, encrypted OAuth token store,
or production tenant isolation.
