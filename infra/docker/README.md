# Local Docker setup

`docker compose -f infra/docker-compose.yml up --build` starts the API and PostgreSQL on
loopback-only ports. The API uses `AsyncPostgresSaver` for graph checkpoints when `DATABASE_URL`
is set; it creates the LangGraph checkpoint tables at startup. The default local database password
is for development only.

This is not a production deployment: the API has no authentication, there is no marketplace
adapter or deployed frontend, and the compose stack does not yet include Redis, a vector store,
GigSim, workers, or Ollama.
