# Deployment

The bot runs on Oracle Cloud Infrastructure (OCI) Always Free using Docker. This
directory contains the Docker build, the Oracle setup/deploy scripts, and a
couple of generic helpers.

## Layout

```
deployment/
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml          # local dev compose
├── oracle/
│   ├── README.md                   # full Oracle deployment guide
│   ├── ORACLE_SETUP_CHECKLIST.md
│   ├── docker-compose.oracle.yml   # OCI-tuned compose
│   ├── setup-oracle-vm.sh          # one-time VM setup
│   ├── deploy-to-oracle.sh         # deploy from local
│   └── oci-config.sh
└── scripts/
    ├── load-env.sh                 # safely source .env (handles JSON values)
    └── test-env.sh                 # validate .env contents
```

The container entrypoint script (`start-server.sh`) lives at the repo root because
the Dockerfile copies the whole project into `/app` and runs `./start-server.sh`.


## Quick start

### Local development (no container)
```bash
pip install -r requirements.txt
cp env_example.txt .env   # then fill in tokens
python manage.py migrate
python manage.py runbot
```

### Local Docker
```bash
docker compose -f deployment/docker/docker-compose.yml up --build
```

### Oracle Cloud (production)
See [`oracle/README.md`](oracle/README.md) for the full guide.

```bash
# from local machine, after setting up the VM once
./deployment/oracle/deploy-to-oracle.sh
```

## See also

- Project root [`README.md`](../README.md) — feature list and command reference
- [`docs/`](../docs/) — deeper documentation and historical notes
